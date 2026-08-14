"""Modèles ORM SQLAlchemy 2.0 — schéma relationnel CoifLink (PRD §9).

Adapter **sortant** de persistance (ADR-0008) : ces tables sont un détail
d'infrastructure et ne sont jamais importées par `domain/` ni `application/`.
Le mapping ci-dessous est la **source de vérité du schéma** ; la migration
initiale (`migrations/versions/0001_schema_initial.py`) en est le reflet
versionné et exécutable.

Conventions (spec §3) :
- **PK** `UUID` avec défaut serveur `gen_random_uuid()` (fonction native PG ≥ 13,
  anti-énumération, pratique côté mobile).
- **Horodatage** `timestamptz` `created_at` / `updated_at` à défaut `now()`.
- **Montants** `NUMERIC(12,2)` (jamais de flottant) ; devise unique XOF.
- **Énumérations** stockées en `text` + contrainte `CHECK` *dérivée du domaine*
  (`coiflink_api.domain.enums`) — évolutif sans `ALTER TYPE`.
- **Isolation par salon** (PRD §11.2) : chaque table à portée salon porte
  `salon_id` indexé ; les références intra-salon utilisent une **FK composite
  `(salon_id, …)`** vers une clé unique `(salon_id, id)` de la table cible, ce
  qui interdit *au niveau base* de rattacher une entité d'un autre salon.
- **Suppression** : `ON DELETE RESTRICT` par défaut (pas de hard-delete des
  salons/paiements ; on utilise des statuts). `CASCADE` réservé aux lignes
  purement dépendantes (jonction ticket↔prestation).
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from coiflink_api.domain import enums
from coiflink_api.domain.queue_ticket import QUEUE_TICKET_STATUSES
from coiflink_api.adapters.outbound.persistence.base import Base


# --------------------------------------------------------------------------- #
# Fabriques de colonnes standard et utilitaires de contraintes.
# --------------------------------------------------------------------------- #
def _pk() -> Mapped[uuid.UUID]:
    """Clé primaire UUID générée côté serveur (`gen_random_uuid()`)."""

    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def _fk_uuid(*, nullable: bool) -> Mapped[uuid.UUID]:
    """Colonne UUID destinée à porter une clé étrangère."""

    return mapped_column(UUID(as_uuid=True), nullable=nullable)


def _created_at() -> Mapped[datetime.datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _updated_at() -> Mapped[datetime.datetime]:
    """`updated_at` à défaut serveur `now()`, rafraîchi par l'ORM à chaque flush.

    `onupdate=func.now()` (évalué côté serveur, pas en Python) fait que **toute**
    mutation flushée via SQLAlchemy sur une ligne portant cette colonne rafraîchit
    `updated_at` automatiquement — un seul endroit à maintenir plutôt qu'un bump
    manuel par méthode d'écriture (#20).
    """

    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def enum_check(column: str, enum_cls: type[enums._StrEnum], *, name: str) -> CheckConstraint:
    """Contrainte `CHECK column IN (...)` dérivée d'une énumération du domaine.

    Le nom logique court (`name`) est expansé par la convention de nommage en
    `ck_<table>_<name>`. Générer le `CHECK` depuis l'énumération garantit que les
    valeurs SQL ne divergent jamais du domaine Python.
    """

    allowed = ", ".join(f"'{value}'" for value in enums.values(enum_cls))
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


# --------------------------------------------------------------------------- #
# Entités (PRD §9).
# --------------------------------------------------------------------------- #
class User(Base):
    """Compte utilisateur, tous rôles confondus (PRD §9.1)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    # email facultatif (inscription par téléphone) ; unique seulement s'il existe.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Jamais de mot de passe en clair : on ne stocke que le condensat (PRD §11.1).
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{enums.UserStatus.ACTIVE.value}'")
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()

    __table_args__ = (
        UniqueConstraint("phone", name="uq_users_phone"),
        enum_check("role", enums.Role, name="role"),
        enum_check("status", enums.UserStatus, name="status"),
        # Unicité de l'email uniquement quand il est renseigné (index partiel).
        Index(
            "uq_users_email",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )


class Salon(Base):
    """Salon de coiffure ; racine d'isolation multi-tenant (PRD §9.2, §11.2)."""

    __tablename__ = "salons"

    id: Mapped[uuid.UUID] = _pk()
    owner_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commune: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latitude: Mapped[decimal.Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[decimal.Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    # Stocke une **clé d'objet** S3-compatible (`salons/{id}/logo/{uuid}.png`),
    # jamais une URL : l'URL signée est calculée à la lecture (ADR-0005, #15).
    logo_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{enums.SalonStatus.ACTIVE.value}'")
    )
    opening_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_salons_owner_id", ondelete="RESTRICT"
        ),
        enum_check("status", enums.SalonStatus, name="status"),
        # Index de recherche (budget perf recherche salon < 2 s — PRD §12.1).
        Index("ix_salons_city_commune", "city", "commune"),
        Index("ix_salons_status", "status"),
    )


class SalonMember(Base):
    """Appartenance d'un compte (employé) à un salon (US-1.4, #13, ADR-0016).

    Table d'autorité de la **portée** d'un employé (PRD §11.2) : un `HAIRDRESSER`
    « voit » les salons dont il est membre `ACTIVE`, indépendamment des rendez-vous
    qui lui sont assignés. Le rôle est stocké en `text` + `CHECK` dérivé de `Role`
    (MVP : `HAIRDRESSER`), laissant la porte ouverte à d'autres rôles employés
    sans `ALTER`.
    """

    __tablename__ = "salon_members"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    user_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text(f"'{enums.UserStatus.ACTIVE.value}'"),
    )
    # Champs professionnels facultatifs (Dashboard Manager, gestion des
    # coiffeuses) : texte libre composé par le gérant, aucune contrainte
    # fermée au MVP. Migration 0011.
    specialties: Mapped[str | None] = mapped_column(Text, nullable=True)
    hired_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_salon_members_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_salon_members_user_id", ondelete="RESTRICT"
        ),
        # Un utilisateur n'est employé qu'une fois par salon.
        UniqueConstraint("salon_id", "user_id", name="uq_salon_members_salon_user"),
        # Cible de futures FK composites (salon_id, member_id) d'isolation.
        UniqueConstraint("salon_id", "id", name="uq_salon_members_salon_id"),
        enum_check("role", enums.Role, name="role"),
        enum_check("status", enums.UserStatus, name="status"),
        Index("ix_salon_members_user_id", "user_id"),
        Index("ix_salon_members_salon_id", "salon_id"),
    )


class SalonPhoto(Base):
    """Photo d'un salon (US-2.1, #15). Comble l'absence de « photos » du §9.2.

    Le §9.2 (et la table `salons`) ne portent qu'un logo singulier ; US-2.1 et
    §7.2 demandent des **photos** (pluriel). Chaque ligne référence une **clé
    d'objet** S3-compatible (jamais une URL) : l'URL signée est calculée à la
    lecture (ADR-0005). Une photo est **purement dépendante** de son salon (elle
    n'a aucun sens seule) → `ON DELETE CASCADE`, par exception à la convention
    `RESTRICT` du module (même logique que `queue_ticket_services`).
    """

    __tablename__ = "salon_photos"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Clé d'objet du bucket (jamais une URL publique) ; bornée à 1024 caractères.
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Ordre d'affichage (0-indexé, croissant).
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_salon_photos_salon_id", ondelete="CASCADE"
        ),
        # Cible de futures FK composites (salon_id, photo_id) — convention d'isolation.
        UniqueConstraint("salon_id", "id", name="uq_salon_photos_salon_id"),
        # Pas de doublon de média au sein d'un salon.
        UniqueConstraint("salon_id", "object_key", name="uq_salon_photos_salon_object_key"),
        CheckConstraint("position >= 0", name="position_positive"),
        Index("ix_salon_photos_salon_id", "salon_id", "position"),
    )


class Service(Base):
    """Prestation proposée par un salon (PRD §9.3)."""

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_services_salon_id", ondelete="RESTRICT"
        ),
        # Cible des FK composites (salon_id, service_id) : garantit l'appartenance salon.
        UniqueConstraint("salon_id", "id", name="uq_services_salon_id"),
        CheckConstraint("price >= 0", name="price_positive"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        Index("ix_services_salon_id", "salon_id"),
    )


class ServicePhoto(Base):
    """Photo d'une prestation (galerie multi-images, miroir `SalonPhoto`).

    Remplace l'ancien champ scalaire `Service.image_object_key` (migration
    0010, retiré par la migration 0020) : une prestation peut désormais porter
    **plusieurs** illustrations, la position 0 servant de couverture pour le
    catalogue. FK **composite** `(salon_id, service_id)` (et non une simple FK
    vers `services.id`) : convention d'isolation §11.2 des tables qui référencent
    une entité déjà scopée-salon (miroir `Payment.service_id`), plutôt que la FK
    simple de `salon_photos → salons.id` (le salon **est** la racine d'isolation,
    une prestation ne l'est pas). `ON DELETE CASCADE` : une photo n'a aucun sens
    sans sa prestation.
    """

    __tablename__ = "service_photos"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    service_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Clé d'objet du bucket (jamais une URL publique) ; bornée à 1024 caractères.
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Ordre d'affichage (0-indexé, croissant) ; position 0 = couverture.
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_service_photos_service",
            ondelete="CASCADE",
        ),
        # Cible de futures FK composites (salon_id, photo_id) — convention d'isolation.
        UniqueConstraint("salon_id", "id", name="uq_service_photos_salon_id"),
        # Pas de doublon de média au sein d'un salon.
        UniqueConstraint("salon_id", "object_key", name="uq_service_photos_salon_object_key"),
        CheckConstraint("position >= 0", name="position_positive"),
        Index("ix_service_photos_salon_id_service_id", "salon_id", "service_id", "position"),
    )


class CustomerProfile(Base):
    """Fiche client propre à un salon (PRD §9.5). Supporte les clients walk-in."""

    __tablename__ = "customer_profiles"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Nullable : un client « walk-in » peut ne pas avoir de compte utilisateur.
    user_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Genre **optionnel** (US-4.1, #28) : `NULL` = non renseigné. Domaine fermé,
    # dérivé de `enums.Gender` par le `CHECK` ci-dessous (migration 0005).
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_visit_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_visits: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_customer_profiles_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_customer_profiles_user_id", ondelete="RESTRICT"
        ),
        CheckConstraint("total_visits >= 0", name="total_visits_positive"),
        enum_check("gender", enums.Gender, name="gender"),
        # Un même utilisateur n'a qu'une fiche par salon (quand il a un compte).
        Index(
            "uq_customer_profiles_salon_user",
            "salon_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        # Un même **téléphone** n'a qu'une fiche par salon (#28) : deux fiches pour
        # le même numéro fausseraient l'historique de visites (#29) et les
        # statistiques (#31). Partiel — le téléphone est optionnel (walk-in), et
        # deux salons distincts peuvent ficher le même numéro (cloisonnement §11.2).
        Index(
            "uq_customer_profiles_salon_phone",
            "salon_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
        Index("ix_customer_profiles_salon_id", "salon_id"),
    )


class Payment(Base):
    """Paiement / transaction (PRD §9.6). Lié à une prestation ou un ticket walk-in."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Référence prestation directe (PRD §8.2 : « lié à une prestation OU un ticket »).
    service_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    # Référence ticket walk-in (migration 0016, jalon M7) — second rattachement
    # possible (avec `service_id`). Le prix encaissé est résolu **en direct**
    # depuis `Service.price` au moment du paiement (aucune colonne de gel de
    # prix côté `queue_ticket_services`, décision produit).
    queue_ticket_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    client_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'XOF'")
    )
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text(f"'{enums.PaymentStatus.PENDING.value}'"),
    )
    # Utilisateur responsable de l'encaissement (PRD §8.2) — obligatoire.
    recorded_by: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Téléphone utilisé pour la transaction Mobile Money (migration 0019) — même
    # borne que `users.phone`. Obligatoire uniquement pour `MOBILE_MONEY_MANUAL`,
    # imposé **uniquement** côté application (`domain/payment.py`, appelé par
    # `RecordPayment.execute` avant toute écriture) — délibérément **pas** de
    # `CHECK` en base : celui-ci s'appliquerait à tout `UPDATE` de la ligne, y
    # compris `mark_adjusted` (correction, US-5.3) qui ne touche pourtant que
    # `status` — un paiement Mobile Money antérieur à cette colonne (donc
    # `NULL` de façon permanente) deviendrait alors indéfiniment impossible à
    # corriger (voir la migration 0019 pour le détail). Toujours `NULL` pour
    # les autres modes (jamais une donnée orpheline sans rapport avec le paiement).
    mobile_money_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Numéro de reçu séquentiel par salon (impression gérant, migration 0012) — alloué
    # atomiquement à la création (`SqlPaymentRepository.create`), jamais recalculé en lecture.
    receipt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_payments_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_payments_service",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["salon_id", "queue_ticket_id"],
            ["queue_tickets.salon_id", "queue_tickets.id"],
            name="fk_payments_queue_ticket",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["client_id"], ["users.id"], name="fk_payments_client_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["recorded_by"], ["users.id"], name="fk_payments_recorded_by", ondelete="RESTRICT"
        ),
        # Cible de la FK composite (salon_id, transaction_id) du journal de caisse.
        UniqueConstraint("salon_id", "id", name="uq_payments_salon_id"),
        UniqueConstraint(
            "salon_id", "receipt_number", name="uq_payments_salon_receipt_number"
        ),
        enum_check("payment_method", enums.PaymentMethod, name="payment_method"),
        enum_check("status", enums.PaymentStatus, name="status"),
        CheckConstraint("amount >= 0", name="amount_positive"),
        # Un paiement référence au moins une prestation ou un ticket walk-in.
        CheckConstraint(
            "service_id IS NOT NULL OR queue_ticket_id IS NOT NULL",
            name="ref_present",
        ),
        Index("ix_payments_salon_id", "salon_id", "created_at"),
        Index("ix_payments_queue_ticket_id", "queue_ticket_id"),
    )


class CashJournal(Base):
    """Journal de caisse horodaté et **append-only** (PRD §8.2, §9.7).

    Aucune ligne n'est supprimée ni modifiée : une correction crée une nouvelle
    opération `ADJUSTMENT`/`REFUND`. L'immuabilité stricte sera renforcée côté
    application (M4) et, si retenu, par révocation des privilèges UPDATE/DELETE.
    """

    __tablename__ = "cash_journal"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    performed_by: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_cash_journal_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["salon_id", "transaction_id"],
            ["payments.salon_id", "payments.id"],
            name="fk_cash_journal_transaction",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["performed_by"], ["users.id"], name="fk_cash_journal_performed_by", ondelete="RESTRICT"
        ),
        enum_check("operation_type", enums.CashOperationType, name="operation_type"),
        Index("ix_cash_journal_salon_id", "salon_id", "created_at"),
    )


class Campaign(Base):
    """Campagne/message aux clients d'un salon (PRD §8.4, US-7.5, #49).

    Une **action manuelle du gérant** : composer un message (`type` + `title` +
    `message` en **texte libre**) et le diffuser à un **segment** de son fichier
    clients (#28). N'est **pas** rattachée à un destinataire précis : elle porte
    un **effectif** (`recipient_count`, entier non-PII) snapshot du segment à la
    création, jamais la liste des téléphones (résolus **à l'envoi** par le worker
    de remise M5+, ADR-0006).

    **Non-fuite de PII (§11.3)** : aucune colonne ne porte de téléphone, nom ni
    identité de destinataire. Le `message` est du **contenu métier** composé par le
    gérant (diffusé à l'identique à tout le segment), pas une donnée client.

    `status = PENDING` + `sent_at = NULL` au MVP : la campagne est **émise/tracée**,
    jamais remise (le worker M5+ passera `SENT`/`FAILED`). FK **RESTRICT** vers
    `salons` et `users` (convention du module ; une campagne garde sa trace même si
    le salon/l'auteur change d'état).
    """

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Auteur (le gérant) — imposé serveur (`principal.id`), jamais lu du corps.
    created_by: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    segment: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Effectif **snapshot** du segment à la création (entier, non-PII).
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text(f"'{enums.CampaignStatus.PENDING.value}'"),
    )
    sent_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_campaigns_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_campaigns_created_by", ondelete="RESTRICT"
        ),
        enum_check("type", enums.CampaignType, name="type"),
        enum_check("segment", enums.CampaignSegment, name="segment"),
        enum_check("channel", enums.NotificationChannel, name="channel"),
        enum_check("status", enums.CampaignStatus, name="status"),
        CheckConstraint("recipient_count >= 0", name="recipient_count_positive"),
        # Liste des campagnes du salon, la plus récente d'abord.
        Index("ix_campaigns_salon_id", "salon_id", "created_at"),
    )


class AuditLog(Base):
    """Journal d'audit §11.4 — trace *qui* fait *quelle* action sur *quelle*
    entité de *quel* salon, *quand* (US-2.3, #17).

    Première matérialisation de la « Journalisation des accès sensibles » (§11.3)
    et de la liste §11.4. Câblée au MVP sur les **prestations** ; le vocabulaire
    (`domain.audit.AuditAction`) et cette table sont conçus pour être réutilisés
    par les actions §11.4 suivantes (RDV, paiement, caisse, désactivation salon).

    **Invariant de non-fuite** : aucune ligne ne porte de secret ni de PII.
    `actor_user_id` est un UUID **opaque** (pas le nom ni le téléphone), `metadata`
    ne contient que du contexte neutre (p. ex. `{"changed": ["price"]}`).

    **`ON DELETE RESTRICT`** sur `actor_user_id` et `salon_id` : un journal d'audit
    ne doit **pas** perdre ses lignes quand un compte/salon disparaît (traçabilité).
    Cohérent avec la convention `RESTRICT` par défaut du module.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _pk()
    # Valeur d'`AuditAction` (domaine fermé), stockée en texte borné.
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # Qui : le `Principal` authentifié — jamais nul (une action a toujours un auteur).
    actor_user_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Portée : le salon concerné, `NULL` pour une action hors portée salon.
    salon_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    # Ressource visée : type ("service") + identifiant.
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Contexte **neutre** (noms de champs modifiés…) ; jamais de secret ni de PII.
    # L'attribut Python est renommé (`metadata` est réservé par SQLAlchemy sur
    # `Base.metadata`) mais la colonne SQL reste bien `metadata`.
    event_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_audit_logs_actor_user_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_audit_logs_salon_id", ondelete="RESTRICT"
        ),
        # Lecture chronologique par salon (base de la supervision §11.3).
        Index(
            "ix_audit_logs_salon_id_created_at",
            "salon_id",
            text("created_at DESC"),
        ),
        # Historique d'une entité donnée (une prestation).
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        # Actions d'un acteur donné.
        Index("ix_audit_logs_actor", "actor_user_id"),
    )


# Valeurs SQL du `CHECK` `status` du ticket, **dérivées du domaine**
# (`QUEUE_TICKET_STATUSES`) : les valeurs base ne divergent jamais du Python.
_QUEUE_TICKET_STATUS_SQL = ", ".join(f"'{value}'" for value in QUEUE_TICKET_STATUSES)


class QueueTicket(Base):
    """Ticket de passage walk-in (US-8.3, #157, ADR-0042).

    CoifLink fonctionne en **file d'attente exclusive** : aucune réservation à
    l'avance, un client se présente et reçoit un ticket. Le ticket porte son
    propre numéro séquentiel par salon **et** jour civil (`ticket_number`/
    `issued_date`), une estimation d'attente **figée à l'émission**, et son
    propre cycle de vie (`waiting`/`called`/`in_progress`/`done`/`expired`).

    `hairdresser_id` référence **`users.id`** (identifiant de **compte**,
    appartenance salon vérifiée **applicativement**) ; `customer_profile_id`
    est **nullable** (ticket anonyme possible).
    """

    __tablename__ = "queue_tickets"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    ticket_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Jour civil du salon (Africa/Abidjan) : scope du compteur `ticket_number`.
    issued_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    customer_profile_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    hairdresser_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'waiting'")
    )
    # Estimation d'attente (minutes) **figée à l'émission**, jamais recalculée.
    estimated_wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()
    # Horodatages du cycle de vie, distincts du `status`, posés à chaque
    # transition.
    called_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Motif d'annulation manuelle (no-show), posé uniquement à l'annulation
    # (`status = "expired"`, motif obligatoire côté domaine) — colonne `TEXT`
    # non bornée en base, borne applicative `CANCELLATION_REASON_MAX_LENGTH`.
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_queue_tickets_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["customer_profile_id"],
            ["customer_profiles.id"],
            name="fk_queue_tickets_customer_profile_id",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["hairdresser_id"],
            ["users.id"],
            name="fk_queue_tickets_hairdresser_id",
            ondelete="RESTRICT",
        ),
        # Cible des FK composites (salon_id, queue_ticket_id) de la jonction.
        UniqueConstraint("salon_id", "id", name="uq_queue_tickets_salon_id"),
        # Garantie **base** du compteur : un numéro par salon et par jour civil.
        UniqueConstraint(
            "salon_id",
            "issued_date",
            "ticket_number",
            name="uq_queue_tickets_salon_day_number",
        ),
        CheckConstraint(f"status IN ({_QUEUE_TICKET_STATUS_SQL})", name="status"),
        CheckConstraint("estimated_wait_minutes >= 0", name="estimated_wait_positive"),
        # Lectures filtrées par statut (file gérant, compteur d'attente).
        Index("ix_queue_tickets_salon_id", "salon_id", "issued_date"),
        Index("ix_queue_tickets_salon_status", "salon_id", "status"),
    )


class QueueTicketService(Base):
    """Jonction ticket ↔ prestation (US-8.3, #157).

    Les deux FK composites partagent `salon_id`, ce qui force *au niveau base* le
    ticket **et** la prestation à appartenir au même salon. `CASCADE` sur
    `queue_ticket_id` (jonction pure-dépendante du ticket) ; `RESTRICT` sur la
    prestation (une prestation référencée n'est jamais hard-deletée).
    """

    __tablename__ = "queue_ticket_services"

    queue_ticket_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    service_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        PrimaryKeyConstraint(
            "queue_ticket_id", "service_id", name="pk_queue_ticket_services"
        ),
        ForeignKeyConstraint(
            ["salon_id", "queue_ticket_id"],
            ["queue_tickets.salon_id", "queue_tickets.id"],
            name="fk_queue_ticket_services_ticket",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_queue_ticket_services_service",
            ondelete="RESTRICT",
        ),
        Index("ix_queue_ticket_services_service_id", "service_id"),
    )


__all__ = [
    "User",
    "Salon",
    "SalonMember",
    "SalonPhoto",
    "Service",
    "CustomerProfile",
    "Payment",
    "CashJournal",
    "Campaign",
    "AuditLog",
    "QueueTicket",
    "QueueTicketService",
    "enum_check",
]
