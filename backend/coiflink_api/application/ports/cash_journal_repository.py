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
from collections.abc import Mapping
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

    def net_revenue_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, decimal.Decimal]:
        """CA net du salon **par jour civil** sur la période (graphique d'évolution, #148).

        Variante « série » de `net_revenue_between` : renvoie `{jour: net_amount}` — la
        somme **signée** des lignes `cash_journal` `PAYMENT`/`ADJUSTMENT` du salon,
        regroupée par **jour civil** `Africa/Abidjan` (UTC+0 : `date(created_at)` = le
        jour civil, aucune conversion). Ne conserve que les lignes dont `created_at` est
        dans `[jour_début_utc(date_from), jour_fin_utc(date_to)]`. CA **net des
        corrections** (#34), cohérent avec #40. Un jour sans opération est **absent** de
        la map (le domaine `build_series` le complète à `0.00` pour un axe continu).
        Isolation §11.2 **imposée en SQL** (`WHERE salon_id`), couverte par
        `ix_cash_journal_salon_id`. `Decimal` quantifié au centime, **aucune** PII.
        Lecture pure (aucun `flush`).
        """
        ...

    def net_revenue_by_hairdresser(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[uuid.UUID, decimal.Decimal]:
        """CA net **attribué par coiffeur** du salon sur une période (US-6.5, #43).

        Variante **attribuée** de `net_revenue_between` : renvoie
        `{hairdresser_id: net_amount}` — somme **signée** des lignes `cash_journal`
        `PAYMENT`/`ADJUSTMENT` du salon dont le `payment` référence un `appointment`
        **assigné** (`hairdresser_id IS NOT NULL`) dont `appointment_date` est dans
        `[date_from, date_to]` **inclus**, `GROUP BY appointments.hairdresser_id`. Le
        CA est **net des corrections** (#34) — un paiement corrigé fait **baisser** le
        total du coiffeur (parité « montant net » de #40/#37).

        **Attribution par le RDV** : le join `cash_journal → payments.appointment_id →
        appointments` porte le `hairdresser_id` **et** la borne `appointment_date`
        (axe **planning**, pas `cash_journal.created_at`) — ce qui aligne le CA sur la
        **même période** que les prestations/annulations. Les paiements **sans RDV**
        (`appointment_id IS NULL`, prestation directe) ou liés à un RDV **non assigné**
        sont **exclus** (inattribuables) par les joins ; la somme des CA par coiffeur
        peut donc différer du CA salon #40 (résidu documenté). Isolation §11.2
        **imposée en SQL** (`WHERE cash_journal.salon_id = :salon_id`), en défense en
        profondeur de `require_salon_scope`. `Decimal` quantifié au centime. **Ne
        renvoie aucune PII** (ni `client_id`, ni `reference`, ni `recorded_by`, ni
        ligne de paiement) — seulement `(hairdresser_id, montant)`. Lecture pure
        (aucun `flush`). Un coiffeur sans CA attribué est **absent** de la map (le cas
        d'usage retombe sur `0.00`).
        """
        ...


__all__ = [
    "CashJournalRepository",
    "CASH_JOURNAL_LIMIT_DEFAULT",
    "CASH_JOURNAL_LIMIT_MIN",
    "CASH_JOURNAL_LIMIT_MAX",
]
