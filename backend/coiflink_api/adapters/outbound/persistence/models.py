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
  purement dépendantes (jonction RDV↔prestation).
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSRANGE, UUID
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from coiflink_api.domain import enums
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
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
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


class Appointment(Base):
    """Rendez-vous (PRD §9.4). Lié à un salon + ≥ 1 prestation (PRD §8.1)."""

    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    client_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    hairdresser_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    appointment_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[datetime.time] = mapped_column(Time(timezone=False), nullable=False)
    end_time: Mapped[datetime.time] = mapped_column(Time(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text(f"'{enums.AppointmentStatus.PENDING.value}'"),
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Créneau dérivé (fuseau d'Abidjan = UTC+0, d'où `tsrange` plutôt que `tstzrange`),
    # support de la contrainte anti double-réservation.
    slot: Mapped[object] = mapped_column(
        TSRANGE,
        Computed(
            "tsrange((appointment_date + start_time), (appointment_date + end_time))",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_appointments_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["client_id"], ["users.id"], name="fk_appointments_client_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["hairdresser_id"],
            ["users.id"],
            name="fk_appointments_hairdresser_id",
            ondelete="RESTRICT",
        ),
        # Cible des FK composites (salon_id, appointment_id).
        UniqueConstraint("salon_id", "id", name="uq_appointments_salon_id"),
        enum_check("status", enums.AppointmentStatus, name="status"),
        CheckConstraint("end_time > start_time", name="time_order"),
        # Anti double-réservation d'un même coiffeur sur des créneaux qui se
        # chevauchent (PRD §8.1) — uniquement pour les RDV actifs et assignés.
        ExcludeConstraint(
            ("hairdresser_id", "="),
            ("slot", "&&"),
            using="gist",
            where=text(
                "hairdresser_id IS NOT NULL AND status IN ('PENDING', 'CONFIRMED')"
            ),
            name="ex_appointments_hairdresser_slot",
        ),
        Index("ix_appointments_salon_id", "salon_id", "appointment_date"),
        Index("ix_appointments_client_id", "client_id"),
    )


class AppointmentService(Base):
    """Jonction RDV ↔ prestation : porte le « ≥ 1 prestation » du PRD §8.1.

    La cardinalité « au moins une prestation » se garantit par insertion
    transactionnelle (RDV + ≥ 1 ligne ici dans la même transaction) côté
    applicatif (M3). Les deux FK composites partagent `salon_id`, ce qui force
    *au niveau base* le RDV **et** la prestation à appartenir au même salon.
    """

    __tablename__ = "appointment_services"

    appointment_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    service_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    # Prix figé au moment de la réservation (un changement de tarif ne réécrit
    # pas l'historique).
    price_at_booking: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        PrimaryKeyConstraint(
            "appointment_id", "service_id", name="pk_appointment_services"
        ),
        # Cohérence salon : RDV et prestation partagent forcément le même salon.
        ForeignKeyConstraint(
            ["salon_id", "appointment_id"],
            ["appointments.salon_id", "appointments.id"],
            name="fk_appointment_services_appointment",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_appointment_services_service",
            ondelete="RESTRICT",
        ),
        CheckConstraint("price_at_booking >= 0", name="price_positive"),
        Index("ix_appointment_services_service_id", "service_id"),
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
        # Un même utilisateur n'a qu'une fiche par salon (quand il a un compte).
        Index(
            "uq_customer_profiles_salon_user",
            "salon_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index("ix_customer_profiles_salon_id", "salon_id"),
    )


class Payment(Base):
    """Paiement / transaction (PRD §9.6). Lié à une prestation ou un RDV (PRD §8.2)."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = _pk()
    salon_id: Mapped[uuid.UUID] = _fk_uuid(nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    # Référence prestation directe (PRD §8.2 : « lié à une prestation OU un RDV »).
    service_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
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
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_payments_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["salon_id", "appointment_id"],
            ["appointments.salon_id", "appointments.id"],
            name="fk_payments_appointment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_payments_service",
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
        enum_check("payment_method", enums.PaymentMethod, name="payment_method"),
        enum_check("status", enums.PaymentStatus, name="status"),
        CheckConstraint("amount >= 0", name="amount_positive"),
        # PRD §8.2 : un paiement référence au moins un RDV ou une prestation.
        CheckConstraint(
            "appointment_id IS NOT NULL OR service_id IS NOT NULL", name="ref_present"
        ),
        Index("ix_payments_salon_id", "salon_id", "created_at"),
        Index("ix_payments_appointment_id", "appointment_id"),
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


class Notification(Base):
    """Notification émise vers un utilisateur / salon (PRD §9.8, §8.4)."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    salon_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    appointment_id: Mapped[uuid.UUID | None] = _fk_uuid(nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text(f"'{enums.NotificationStatus.PENDING.value}'"),
    )
    sent_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notifications_user_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_notifications_salon_id", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name="fk_notifications_appointment_id",
            ondelete="RESTRICT",
        ),
        enum_check("type", enums.NotificationType, name="type"),
        enum_check("channel", enums.NotificationChannel, name="channel"),
        enum_check("status", enums.NotificationStatus, name="status"),
        Index("ix_notifications_user_id", "user_id"),
        Index("ix_notifications_salon_id", "salon_id", "created_at"),
    )


__all__ = [
    "User",
    "Salon",
    "SalonMember",
    "Service",
    "Appointment",
    "AppointmentService",
    "CustomerProfile",
    "Payment",
    "CashJournal",
    "Notification",
    "enum_check",
]
