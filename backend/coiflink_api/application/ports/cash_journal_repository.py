"""Port de persistance du **journal de caisse** (`Protocol`, US-5.3, #34).

Le cas d'usage (`application/cash_journal.py`, `application/payments.py`) déclare
ici ses besoins ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/cash_journal_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Invariant append-only (§8.2), porté par le contrat lui-même.** Ce port n'expose
**que** `append` (un `INSERT`) et deux lectures. Il ne déclare **aucune** méthode
`update`/`delete` : l'immuabilité du journal est **structurelle** (on ne peut pas
appeler ce qui n'existe pas), pas seulement une convention. Une correction est une
**nouvelle** ligne `ADJUSTMENT`, jamais une réécriture.

**Isolation §11.2 au niveau du dépôt** : les lectures prennent `salon_id` et
refiltrent systématiquement dessus ; l'écriture porte le `salon_id` de la portée
validée (et la FK composite `(salon_id, transaction_id) → payments` garantit en base
que la transaction liée appartient au même salon).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Protocol

from coiflink_api.domain.cash_journal import CashJournalEntry, CashJournalToAppend

# Bornes de pagination de la lecture du journal (garde de coût §12.1 — mêmes
# bornes que la liste des fiches clients #28, pour la cohérence des surfaces).
CASH_JOURNAL_LIMIT_DEFAULT = 50
CASH_JOURNAL_LIMIT_MIN = 1
CASH_JOURNAL_LIMIT_MAX = 200


class CashJournalRepository(Protocol):
    """Contrat de persistance du journal de caisse d'un salon (append + lectures)."""

    def append(self, entry: CashJournalToAppend) -> CashJournalEntry:
        """Insère **une** ligne de journal (`INSERT` seul — append-only, §8.2).

        `flush()` sans `commit()` : la ligne est matérialisée (contraintes FK
        vérifiées) mais committée **avec** l'action métier et l'audit par
        `get_session` (atomicité). Retourne la ligne créée, horodatage serveur inclus.
        """
        ...

    def list_for_salon(
        self, salon_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[CashJournalEntry, ...]:
        """Page d'opérations du salon, **de la plus récente à la plus ancienne**.

        Tri `created_at DESC, id DESC` (déterministe). La projection **résout le nom
        d'affichage de l'auteur** (`performed_by → users.full_name`) pour l'UI, sans
        exposer d'autre donnée sensible de l'auteur (§11.3). Bornes appliquées en SQL.
        """
        ...

    def count_for_salon(self, salon_id: uuid.UUID) -> int:
        """Nombre total d'opérations du salon (total de pagination)."""
        ...

    def net_revenue_between(
        self,
        salon_id: uuid.UUID,
        *,
        created_at_from: datetime.datetime,
        created_at_to: datetime.datetime,
    ) -> decimal.Decimal:
        """Somme **signée** du CA du salon sur `[created_at_from, created_at_to]` (US-6.2, #40).

        Renvoie la somme des `cash_journal.amount` du salon dont `created_at` est
        dans l'intervalle **inclus**, **restreinte aux opérations `PAYMENT` /
        `ADJUSTMENT`** : le CA est **net des corrections** (#34) — un paiement
        corrigé fait baisser le total (parité « montant net » de #37). Les autres
        types (`REFUND`/`CASH_OPENING`/`CASH_CLOSING`) ne sont pas du chiffre
        d'affaires et n'existent pas au MVP.

        Isolation §11.2 **imposée en SQL** (`WHERE salon_id = :salon_id`), défense en
        profondeur de `require_salon_scope`. Lecture pure (aucun `flush`) : agrégat
        calculé **en base**, sans rapatrier de ligne ni de PII. `Decimal` quantifié
        au centime (`NUMERIC(12,2)`, jamais un flottant) ; `Decimal("0.00")` si aucune
        ligne dans l'intervalle.
        """
        ...


__all__ = [
    "CashJournalRepository",
    "CASH_JOURNAL_LIMIT_DEFAULT",
    "CASH_JOURNAL_LIMIT_MIN",
    "CASH_JOURNAL_LIMIT_MAX",
]
