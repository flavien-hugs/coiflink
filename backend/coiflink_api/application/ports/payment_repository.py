"""Port de persistance des **paiements** (`Protocol`, US-5.1/5.3, #33/#34).

Le cas d'usage (`application/payments.py`, `application/cash_journal.py`) déclare
ici ses besoins ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/payment_repository.py`. Conformément à l'hexagonal
(ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Invariant append-only / non-suppression (§8.2).** Ce port n'expose **aucune**
méthode `delete` : un paiement validé n'est **jamais** supprimé. La seule mutation
autorisée est `mark_adjusted` — un passage de statut `VALIDATED → ADJUSTED` (la
ligne et son montant d'origine subsistent). L'absence de verbe destructif **dans le
port** est un choix de conception, vérifié par les tests de sécurité.

**Isolation §11.2 au niveau du dépôt** : toutes les méthodes portant sur un
paiement existant prennent `salon_id` **en plus** de l'identifiant et filtrent sur
le couple `(salon_id, id)`. Un paiement d'un autre salon est **indiscernable d'un
paiement inexistant** — impossible de le lire/corriger même si l'`id` est deviné.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.discrepancy import CashDiscrepancy, DiscrepancyFilter
from coiflink_api.domain.payment import Payment, PaymentToCreate
from coiflink_api.domain.transaction import Transaction, TransactionFilter

# Bornes de pagination de la liste des transactions (US-5.2, #35 — garde de coût
# §12.1). Alignées sur `CASH_JOURNAL_LIMIT_*` (50/1/200) pour la cohérence des
# surfaces « caisse » (journal #34 ↔ historique #35).
PAYMENTS_LIMIT_DEFAULT = 50
PAYMENTS_LIMIT_MIN = 1
PAYMENTS_LIMIT_MAX = 200


class PaymentRepository(Protocol):
    """Contrat de persistance des paiements d'un salon (append + statut, jamais delete)."""

    def create(self, payment: PaymentToCreate) -> Payment:
        """Insère et retourne le paiement enregistré (statut `VALIDATED`, US-5.1).

        Le `salon_id` et l'auteur (`recorded_by`) proviennent de la portée validée
        et du principal — jamais du corps. `created_at` est généré côté serveur
        (horodatage non falsifiable §8.2).
        """
        ...

    def get(self, salon_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        """Retourne le paiement `(salon_id, payment_id)` ; lève `PaymentNotFound`.

        Le filtre porte sur `salon_id` **et** `id` (isolation §11.2) : un paiement
        d'un autre salon est indiscernable d'un paiement inexistant (aucun oracle).
        """
        ...

    def mark_adjusted(self, salon_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        """Passe le paiement `(salon_id, payment_id)` à `status = ADJUSTED` (US-5.3).

        **Jamais** une suppression : une mutation de **statut** bornée
        (`VALIDATED → ADJUSTED`). Le filtre `(salon_id, id)` (isolation §11.2) et la
        garde de transition (seul un `VALIDATED` est corrigible) évitent d'altérer
        un paiement hors salon ou dans un état non corrigible — lève
        `PaymentNotFound` (hors salon/inconnu) ou `PaymentNotAdjustable` (état
        incompatible). `flush()` sans `commit()` (atomicité avec le journal/l'audit).
        """
        ...

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        filter: TransactionFilter,
        limit: int,
        offset: int,
    ) -> tuple[Transaction, ...]:
        """Page **filtrée** des transactions du salon (US-5.2, #35) — lecture seule.

        Applique **inconditionnellement** le filtre `salon_id` (isolation §11.2 en
        profondeur : aucune transaction d'un autre salon, quel que soit le filtre),
        puis **conditionnellement** les clauses présentes dans `filter` (date,
        client, montant, mode — combinées en **ET**). Tri déterministe
        `created_at DESC, id DESC`, bornes `limit`/`offset` appliquées **en SQL**
        (jamais en mémoire). La projection résout `client_id → users.full_name`
        (colonne non sensible **uniquement**, §11.3). **Aucune** écriture.
        """
        ...

    def count_for_salon(
        self, salon_id: uuid.UUID, *, filter: TransactionFilter
    ) -> int:
        """Nombre total de transactions du salon **sous le même filtre** (pagination).

        Applique **exactement** les mêmes clauses que `list_for_salon` (filtre
        `salon_id` inconditionnel + clauses conditionnelles) pour un `total`
        cohérent avec la page.
        """
        ...

    def has_paid_payment(
        self, salon_id: uuid.UUID, queue_ticket_id: uuid.UUID
    ) -> bool:
        """Vrai si le ticket `(salon_id, queue_ticket_id)` a déjà un paiement payé (§8.2).

        Réutilise **exactement** la même notion de « payé » que la détection des
        écarts de caisse (`PAID_PAYMENT_STATUSES` de `domain/discrepancy.py`) :
        renvoie `True` **ssi** un paiement pour ce couple porte le statut
        `VALIDATED` **ou** `ADJUSTED`. Sert de garde à `RecordPayment` pour refuser
        un second encaissement sur un ticket déjà couvert (`QueueTicketAlreadyPaid`).
        Filtre `salon_id` inconditionnel (isolation §11.2). Lecture seule.
        """
        ...

    def list_completed_without_payment(
        self,
        salon_id: uuid.UUID,
        *,
        filter: DiscrepancyFilter,
        limit: int,
        offset: int,
    ) -> tuple[CashDiscrepancy, ...]:
        """Page des **écarts de caisse** du salon (US-5.4, #36) — lecture seule.

        Liste les tickets walk-in `done` du salon **auxquels aucun paiement
        `VALIDATED`/`ADJUSTED` n'est rattaché** (rapprochement `NOT EXISTS` sur
        `payments.queue_ticket_id`). Applique **inconditionnellement** le filtre
        `salon_id` (isolation §11.2 en profondeur : jamais un ticket d'un autre
        salon, et un paiement d'un autre salon ne « couvre » jamais un ticket), puis
        **conditionnellement** les bornes de dates du `filter` (sur `issued_date`,
        jour civil `Africa/Abidjan`). Chaque écart porte le **montant attendu**
        (somme des `Service.price` **actuels** des prestations du ticket) et résout
        `customer_profile_id → customer_profiles.full_name` (colonne non sensible
        **uniquement**, §11.3). Tri déterministe, bornes `limit`/`offset` appliquées
        **en SQL** (jamais en mémoire). **Aucune** écriture.
        """
        ...

    def count_completed_without_payment(
        self, salon_id: uuid.UUID, *, filter: DiscrepancyFilter
    ) -> int:
        """Nombre total d'écarts du salon **sous le même filtre** (pagination).

        Applique **exactement** les mêmes clauses `WHERE`/`NOT EXISTS` que
        `list_completed_without_payment` (filtre `salon_id` inconditionnel + bornes de
        dates), en comptant les **tickets** (jamais les lignes de prestation) pour un
        `total` cohérent avec la page.
        """
        ...


__all__ = [
    "PaymentRepository",
    "PAYMENTS_LIMIT_DEFAULT",
    "PAYMENTS_LIMIT_MIN",
    "PAYMENTS_LIMIT_MAX",
]
