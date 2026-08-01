"""Cas d'usage : **gestion des fiches clients d'un salon** (US-4.1, #28).

Tranche applicative hexagonale calquée sur #17 : ces cas d'usage ne dépendent que
de **ports** (`CustomerRepository`, `AuditLog`) — aucune dépendance
FastAPI/SQLAlchemy. Ils orchestrent le domaine (`domain/customer.py`,
`domain/audit.py`) et laissent l'adapter entrant traduire les erreurs en HTTP.

Trois invariants structurants :

- **`salon_id` imposé par la portée** : le salon d'une fiche provient toujours de
  la portée validée (`require_salon_scope`), passé en argument d'`execute` ; il
  n'est **jamais** lu du corps de requête (garde-fou anti-élévation).
- **Journalisation §11.4/§11.3 dans la même unité de travail** : la création
  enregistre une `AuditEntry` via le port `AuditLog`, dans la **même `Session`**
  que l'écriture métier — commit/rollback atomique. Créer une fiche est une
  **collecte de données personnelles** : c'est un « accès sensible » au sens du
  PRD §11.3, d'où la trace.
- **Aucune PII journalisée** : `metadata` est **vide**. Ni le nom, ni le
  téléphone, ni le genre, ni les notes n'entrent au journal d'audit.

Le cas d'usage n'interroge **jamais** la table `users` par téléphone (ni pour
rattacher un `user_id`, ni pour suggérer un compte) : ce serait offrir au gérant
un **oracle d'existence de compte** (§11.1/§11.3, ADR-0026). Les fiches créées
ici sont des fiches **walk-in** (`user_id = NULL`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.customer_repository import CustomerRepository
from coiflink_api.domain.audit import ENTITY_TYPE_CUSTOMER, AuditAction, AuditEntry
from coiflink_api.domain.customer import (
    Customer,
    CustomerFilter,
    CustomerToCreate,
    normalize_customer_phone,
    normalize_gender,
    normalize_notes,
    validate_customer_name,
)
from coiflink_api.domain.errors import CustomerAlreadyExists, CustomerNotFound
from coiflink_api.domain.visit import (
    HISTORY_STATUSES,
    CustomerServiceStats,
    VisitHistory,
    build_history,
    favourite_services,
)


@dataclass(frozen=True)
class CustomerCommand:
    """Champs saisissables d'une fiche client (US-4.1 : « nom, téléphone, genre
    optionnel, notes internes »).

    Ni `salon_id`, ni `id`, ni `user_id`, ni `total_visits`/`last_visit_at` : le
    salon vient de la portée, l'identité est générée, le rattachement à un compte
    est hors périmètre (#28 crée des fiches walk-in) et les compteurs de visites
    sont alimentés par #29. Seul `full_name` est **obligatoire**.
    """

    full_name: str
    phone: str | None = None
    gender: str | None = None
    notes: str | None = None


def _validate(command: CustomerCommand) -> tuple[str, str | None, str | None, str | None]:
    """Valide la commande (nom → téléphone → genre → notes) ; retourne les champs normalisés.

    La validation précède **toute** écriture (aucun appel au dépôt si un champ est
    invalide, donc aucune fiche ni aucune trace d'audit). L'ordre est stable pour
    des messages d'erreur déterministes.
    """

    full_name = validate_customer_name(command.full_name)
    phone = normalize_customer_phone(command.phone)
    gender = normalize_gender(command.gender)
    notes = normalize_notes(command.notes)
    return full_name, phone, gender, notes


class CreateCustomer:
    """Crée une fiche client rattachée au salon de la portée et journalise (§11.4)."""

    def __init__(self, repository: CustomerRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        command: CustomerCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> Customer:
        """Valide, refuse le doublon de téléphone, persiste, puis journalise.

        Séquence : validation domaine → pré-contrôle d'unicité `(salon_id, phone)`
        → `repository.create(...)` → `audit.record(CUSTOMER_CREATED)`. Le
        `salon_id` provient de la portée validée. Le pré-contrôle produit un `409`
        explicite dans le cas nominal ; en concurrence, c'est l'index unique base
        qui tranche (le dépôt retraduit alors l'`IntegrityError` en
        `CustomerAlreadyExists`).
        """

        full_name, phone, gender, notes = _validate(command)

        if phone is not None and self._repository.phone_exists(salon_id, phone):
            # Message **neutre** : il ne rappelle jamais le numéro soumis (§11.3).
            raise CustomerAlreadyExists(
                "Une fiche existe déjà pour ce numéro dans ce salon."
            )

        customer = self._repository.create(
            CustomerToCreate(
                salon_id=salon_id,
                full_name=full_name,
                phone=phone,
                gender=gender,
                notes=notes,
            )
        )
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.CUSTOMER_CREATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_CUSTOMER,
                entity_id=customer.id,
                # `metadata` **vide** : aucune PII au journal (§11.3/§11.4).
                metadata={},
            )
        )
        return customer


class UpdateCustomerNote:
    """Édite la **note privée** d'une fiche du salon et journalise (§11.3/§11.4, US-4.5, #32).

    Variante à **un seul champ** du patron d'écriture-avec-diff-neutre
    (`UpdateSalon` #20, `UpdateService` #17) : validation domaine
    (`normalize_notes`) **avant** toute écriture → `repository.update_notes(...)`
    (résout la fiche dans le salon, `CustomerNotFound` si hors salon/inconnue,
    **avant** l'audit) → `audit.record(CUSTOMER_NOTE_UPDATED)`.

    Deux invariants structurants :

    - **`salon_id` imposé par la portée** : le salon vient toujours de la portée
      validée (`require_salon_scope`), jamais du corps de requête.
    - **Aucune PII journalisée** : `metadata` est **vide** — ni le contenu de la
      note, ni l'ancienne valeur, ni un booléen de présence n'entre au journal
      (la note peut contenir des données de santé, §11.3). L'action
      `CUSTOMER_NOTE_UPDATED` porte à elle seule l'information de traçabilité.

    Une note vide/`null`/blanche est normalisée en `None` : « éditer » couvre
    naturellement « retirer une note obsolète » (`notes = NULL`). Une note trop
    longue lève `InvalidCustomerNotes` **avant** toute mutation → aucune écriture,
    aucun audit. La fiche hors salon/inconnue lève `CustomerNotFound` **avant**
    l'audit → aucune trace pour une cible inexistante.
    """

    def __init__(self, repository: CustomerRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        customer_id: uuid.UUID,
        notes: str | None,
        *,
        actor_user_id: uuid.UUID,
    ) -> Customer:
        # Validation avant écriture : `None` si vide/blanc → efface la note.
        normalized = normalize_notes(notes)
        # Résout la fiche DANS le salon et remplace la note ; `CustomerNotFound`
        # (hors salon/inconnue) est levée AVANT l'audit → aucune trace sans écriture.
        customer = self._repository.update_notes(salon_id, customer_id, normalized)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.CUSTOMER_NOTE_UPDATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_CUSTOMER,
                entity_id=customer.id,
                # `metadata` **vide** : aucune PII (ni contenu, ni ancienne valeur, §11.3/§11.4).
                metadata={},
            )
        )
        return customer


class ListSalonCustomers:
    """Liste paginée des fiches d'un salon (lecture — pas d'audit)."""

    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        filter: CustomerFilter,
        limit: int,
        offset: int,
    ) -> tuple[tuple[Customer, ...], int]:
        """Retourne `(page, total)` **sous le filtre donné** — les plus récentes d'abord.

        Le total accompagne la page pour permettre une pagination correcte côté
        interface sans seconde requête.
        """

        page = self._repository.list_for_salon(
            salon_id, filter=filter, limit=limit, offset=offset
        )
        total = self._repository.count_for_salon(salon_id, filter=filter)
        return page, total


class GetCustomer:
    """Consulte une fiche dans le périmètre du salon (lecture — pas d'audit)."""

    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    def execute(self, salon_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
        customer = self._repository.find_by_id(salon_id, customer_id)
        if customer is None:
            raise CustomerNotFound("Fiche client introuvable.")
        return customer


class GetCustomerVisitHistory:
    """Historique des visites terminées d'une fiche (lecture — pas d'audit, US-4.2, #29).

    Lecture **fiche-scopée** : la fiche est d'abord résolue **dans le salon**
    (réutilise `GetCustomer` → `CustomerNotFound`/`404` **après** portée, sans
    oracle — une fiche d'un autre salon est indiscernable d'une inexistante). Puis
    les RDV `COMPLETED` liés sont lus via le port (le lien `user_id` reste
    encapsulé côté dépôt, la lecture refiltre `salon_id`), et le résumé dérivé est
    construit **en mémoire** (`build_history`, pur). Aucune écriture, aucun audit
    (patron des lectures `ListSalonCustomers` / `ListSalonAppointments`).
    """

    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    def execute(
        self, salon_id: uuid.UUID, customer_id: uuid.UUID
    ) -> VisitHistory:
        # 1. Résout la fiche DANS le salon (404 après portée si hors salon/inconnue).
        GetCustomer(self._repository).execute(salon_id, customer_id)
        # 2. Lit les RDV terminés liés (COMPLETED) — `user_id` encapsulé côté dépôt,
        #    salon_id refiltré en SQL (défense en profondeur §11.2).
        visits = self._repository.list_visits(salon_id, customer_id, HISTORY_STATUSES)
        # 3. Construit le résumé dérivé (pur, jamais persisté).
        return build_history(visits)


class GetCustomerServiceStats:
    """Prestations préférées d'une fiche (lecture — pas d'audit, US-4.3, #31).

    Lecture **fiche-scopée**, dérivée de la brique #29 (**aucun nouvel accès
    base**) : la fiche est d'abord résolue **dans le salon** (réutilise
    `GetCustomer` → `CustomerNotFound`/`404` **après** portée, sans oracle — une
    fiche d'un autre salon est indiscernable d'une inexistante). Puis les visites
    `COMPLETED` liées sont lues via la **même** `list_visits(HISTORY_STATUSES)`
    (le lien `user_id` reste encapsulé côté dépôt, `salon_id` refiltré en SQL), et
    le classement des prestations préférées est agrégé **en mémoire**
    (`favourite_services`, pur). Aucune écriture, aucun audit (patron des lectures
    `GetCustomerVisitHistory` / `ListSalonCustomers`).
    """

    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    def execute(
        self, salon_id: uuid.UUID, customer_id: uuid.UUID
    ) -> CustomerServiceStats:
        # 1. Résout la fiche DANS le salon (404 après portée si hors salon/inconnue).
        GetCustomer(self._repository).execute(salon_id, customer_id)
        # 2. Lit les visites terminées liées (COMPLETED) — `user_id` encapsulé côté
        #    dépôt, `salon_id`/`client_id` refiltrés en SQL (défense en profondeur §11.2).
        visits = self._repository.list_visits(salon_id, customer_id, HISTORY_STATUSES)
        # 3. Agrège le classement des prestations préférées (pur, jamais persisté).
        return favourite_services(visits)


__all__ = [
    "CustomerCommand",
    "CreateCustomer",
    "UpdateCustomerNote",
    "ListSalonCustomers",
    "GetCustomer",
    "GetCustomerVisitHistory",
    "GetCustomerServiceStats",
]
