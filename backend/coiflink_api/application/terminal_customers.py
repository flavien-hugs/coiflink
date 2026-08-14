"""Cas d'usage : **identité walk-in depuis la borne terminal** (US-8.2, #156).

Tranche applicative hexagonale dédiée à la borne libre-service (PRD §17), calquée
sur `application/customers.py` (gérant) mais **volontairement séparée** : les cas
d'usage gérant restent inchangés. Ces cas d'usage ne dépendent que de **ports** —
`CustomerRepository`, `AuditLog`, `LoginRateLimiter` — jamais de FastAPI/SQLAlchemy.

**Anti-oracle ADR-0026, miroir exécutable.** Ce module n'importe **aucun** port
`users` : la recherche par téléphone porte **exclusivement** sur
`customer_profiles` (`CustomerRepository.find_by_phone`). Un numéro titulaire d'un
compte CoifLink mais sans fiche dans le salon répond « introuvable » — aucun repli
vers `users`, aucun oracle d'existence de **compte** (§11.1/§11.3). La distinction
compte (`users`, mot de passe, portée plateforme) vs fiche (`customer_profiles`,
sans authentification, portée salon) fonde toute l'analyse de sécurité de #156.

Deux invariants structurants (comme #28) :

- **`salon_id` imposé par la portée** : le salon provient toujours de la portée
  validée (`require_salon_scope`), passé en argument d'`execute` ; il n'est
  **jamais** lu du corps de requête (garde-fou anti-élévation).
- **Aucune PII journalisée / loggée** : la création journalise `CUSTOMER_CREATED`
  avec `metadata` **vide** (parité stricte #28) ; les lookups ne sont **pas**
  audités (ADR-0026 — et un terminal public inonderait le journal par usage
  nominal). Le numéro soumis n'entre dans aucun log, message d'erreur ou clé de
  débit (opaque : device + IP).
"""

from __future__ import annotations

import uuid

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.customer_repository import CustomerRepository
from coiflink_api.application.ports.login_rate_limiter import LoginRateLimiter
from coiflink_api.domain.audit import ENTITY_TYPE_CUSTOMER, AuditAction, AuditEntry
from coiflink_api.domain.customer import (
    CustomerToCreate,
    WalkInCustomerCommand,
    WalkInIdentity,
    validate_walk_in_customer,
    walk_in_first_name,
)
from coiflink_api.domain.errors import CustomerAlreadyExists, InvalidPhone
from coiflink_api.domain.phone import normalize_phone


class IdentifyWalkInCustomer:
    """Retrouve une fiche par téléphone dans le salon de la borne (lecture — pas d'audit).

    Réponse **minimale** (`WalkInIdentity` : prénom seul) exigée par le critère
    d'acceptation. La surface d'énumération (composer des numéros pour associer un
    nom à un numéro) est bornée par la **limitation de débit** sur les échecs
    (réutilise le port `LoginRateLimiter`, comme le login terminal #155). Ne comptent
    que les **échecs** (fiche absente, format invalide) ; une identification réussie
    réinitialise la fenêtre — un salon à fort trafic légitime n'est jamais pénalisé.
    """

    def __init__(
        self, repository: CustomerRepository, rate_limiter: LoginRateLimiter
    ) -> None:
        self._repository = repository
        self._rate_limiter = rate_limiter

    def execute(
        self, salon_id: uuid.UUID, raw_phone: str, *, rate_key: str
    ) -> WalkInIdentity | None:
        """Normalise puis cherche `(salon_id, phone)` ; `WalkInIdentity` ou `None`.

        Séquence :

        1. `rate_limiter.check(rate_key)` — lève `TooManyLoginAttempts` si la
           fenêtre est verrouillée (**avant** tout accès base) ;
        2. `normalize_phone(raw_phone)` — un format invalide lève `InvalidPhone`
           **et** compte comme tentative (`record_failure`) : sonder des formats ne
           contourne pas la limite, **aucun** appel au dépôt ;
        3. `repository.find_by_phone(salon_id, phone)` — le `salon_id` provient de
           la **portée validée**, jamais du corps ;
        4. trouvée → `reset` puis projection `WalkInIdentity(id, prénom)` ;
           absente → `record_failure` puis `None` (l'adapter mappe en `404` neutre).
        """

        self._rate_limiter.check(rate_key)

        try:
            phone = normalize_phone(raw_phone)
        except InvalidPhone:
            # Sonder des formats invalides est aussi une tentative (anti-énumération).
            self._rate_limiter.record_failure(rate_key)
            raise

        customer = self._repository.find_by_phone(salon_id, phone)
        if customer is None:
            self._rate_limiter.record_failure(rate_key)
            return None

        self._rate_limiter.reset(rate_key)
        return WalkInIdentity(
            customer_id=customer.id,
            first_name=walk_in_first_name(customer.full_name),
        )


class CreateWalkInCustomer:
    """Crée une fiche walk-in (nom/prénom/téléphone, sans mot de passe) et journalise (§11.4).

    Miroir de `CreateCustomer` (#28) restreint à la collecte minimale de la borne :
    validation/composition domaine → pré-contrôle d'unicité `(salon_id, phone)` →
    `create` (`user_id = NULL`, `gender`/`notes` `None`) → `CUSTOMER_CREATED`
    (`metadata` vide) dans la même unité de travail. Retourne la projection
    **minimale** (`WalkInIdentity`), jamais la fiche complète.
    """

    def __init__(self, repository: CustomerRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        command: WalkInCustomerCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> WalkInIdentity:
        """Valide, refuse le doublon de téléphone, persiste, puis journalise.

        `actor_user_id` est `principal.id` du **compte de service** de la borne
        (une ligne `users` `role=TERMINAL`, ADR-0041) : il satisfait la FK NOT NULL
        `audit_logs.actor_user_id` sans traitement spécial. Le `salon_id` provient
        de la portée validée. Le pré-contrôle produit un `409` explicite dans le
        cas nominal ; en concurrence, l'index unique base tranche (le dépôt
        retraduit l'`IntegrityError` en `CustomerAlreadyExists`).
        """

        # Validation/composition domaine AVANT tout accès base (aucune écriture ni
        # audit si un champ est invalide).
        full_name, phone = validate_walk_in_customer(command)

        if self._repository.phone_exists(salon_id, phone):
            # Message **neutre** : il ne rappelle jamais le numéro soumis (§11.3).
            raise CustomerAlreadyExists(
                "Une fiche existe déjà pour ce numéro dans ce salon."
            )

        customer = self._repository.create(
            CustomerToCreate(
                salon_id=salon_id,
                full_name=full_name,
                phone=phone,
                # Genre et notes ne sont **jamais** collectés par la borne (§11.3).
                gender=None,
                notes=None,
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
        return WalkInIdentity(
            customer_id=customer.id,
            first_name=walk_in_first_name(customer.full_name),
        )


__all__ = ["IdentifyWalkInCustomer", "CreateWalkInCustomer"]
