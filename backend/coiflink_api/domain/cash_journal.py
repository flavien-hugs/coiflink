"""Entités et règles de domaine « journal de caisse » (domaine pur, US-5.3, #34).

Le journal de caisse (`cash_journal`) est **horodaté et append-only** (PRD §8.2,
§9.7) : aucune ligne n'est supprimée ni modifiée ; une correction crée une
**nouvelle** opération `ADJUSTMENT`. Ce module porte, sans aucune dépendance
framework/I/O (ADR-0008) :

- les entités de lecture/commande (`CashJournalEntry`, `CashJournalToAppend`),
  toutes rattachées à un salon (`salon_id`) — miroir de l'isolation §11.2 ;
- la **validation** propre à la correction : le montant d'un `ADJUSTMENT` est un
  **delta signé** (il *peut* être négatif, à la différence d'un `PAYMENT` qui est
  `>= 0`) mais **jamais nul** (une correction doit changer quelque chose) ;
- la normalisation de la `description` (motif de correction) : bornée et *trim*.

Points de sécurité/qualité de donnée (PRD §8.2/§11.3) :

- l'**auteur** (`performed_by`) est **imposé par le principal** authentifié, jamais
  lu du corps de requête (non-répudiation §8.2) ;
- le **motif** (`description`) n'est **pas** de la PII mais reste **hors du journal
  d'audit** (`audit_logs`) : il vit dans `cash_journal`, accès borné par permission.

Aucune de ces règles ne connaît HTTP : l'adapter entrant traduit les erreurs de
domaine (`InvalidAdjustment`) en `422` (cf. `adapters/inbound/payments.py`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.errors import InvalidAdjustment

# Borne de robustesse du delta d'ajustement, alignée sur `NUMERIC(12,2)` de
# `cash_journal.amount` (la colonne n'a **pas** de `CHECK amount >= 0`, ce qui
# autorise le delta négatif — vérifié sur `models.CashJournal`/migration 0001).
ADJUSTMENT_ABS_MAX = decimal.Decimal("9999999999.99")

# Borne applicative du motif de correction. La colonne est `TEXT` (non bornée) :
# cette borne évite d'accepter un corps de requête non borné (§12.1).
DESCRIPTION_MAX_LENGTH = 500


def validate_adjustment_amount(
    delta: decimal.Decimal | int | None,
) -> decimal.Decimal:
    """Valide le **delta d'ajustement** : requis, **≠ 0**, borné, ≤ 2 décimales.

    Contrairement à un paiement, le delta d'un `ADJUSTMENT` **peut être négatif**
    (correction à la baisse). Il ne peut en revanche **jamais** être nul (une
    correction qui ne corrige rien n'a pas de sens), ni non fini, ni hors borne, ni
    comporter plus de deux décimales (précision `NUMERIC(12,2)`). Lève
    `InvalidAdjustment` sinon. Le message ne reprend jamais la valeur (§11.3).
    """

    if isinstance(delta, bool) or delta is None:
        raise InvalidAdjustment("Le montant de l'ajustement est requis.")
    if isinstance(delta, int):
        delta = decimal.Decimal(delta)
    if not isinstance(delta, decimal.Decimal):
        raise InvalidAdjustment("Le montant de l'ajustement est requis.")
    if not delta.is_finite():
        raise InvalidAdjustment("Le montant de l'ajustement est invalide.")
    if delta == 0:
        raise InvalidAdjustment("Le montant de l'ajustement ne peut pas être nul.")
    if abs(delta) > ADJUSTMENT_ABS_MAX:
        raise InvalidAdjustment("Le montant de l'ajustement est hors des bornes autorisées.")
    exponent = delta.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise InvalidAdjustment(
            "Le montant de l'ajustement ne doit pas comporter plus de deux décimales."
        )
    return delta


def normalize_description(description: str | None) -> str | None:
    """Normalise le motif **optionnel** : trim, `None` si vide, ≤ `DESCRIPTION_MAX_LENGTH`.

    Le motif est un texte libre borné ; sa longueur est déjà contrôlée en amont
    (Pydantic `max_length`). Cette fonction normalise : `strip()`, `None` si vide,
    troncature défensive. Le motif n'entre **jamais** dans le journal d'**audit**.
    """

    if not isinstance(description, str):
        return None
    cleaned = description.strip()
    if not cleaned:
        return None
    return cleaned[:DESCRIPTION_MAX_LENGTH]


@dataclass(frozen=True)
class CashJournalToAppend:
    """Intention d'écriture d'une ligne de journal (**append-only**, US-5.3, #34).

    `salon_id` et `performed_by` sont **imposés** (portée validée + principal
    authentifié), jamais lus du corps. Pas d'`id` ni de `created_at` (générés côté
    serveur : horodatage non falsifiable §8.2). Le port de dépôt ne fait qu'un
    `INSERT` (jamais d'`update`/`delete`) : l'immuabilité est structurelle.
    """

    salon_id: uuid.UUID
    operation_type: str
    amount: decimal.Decimal
    performed_by: uuid.UUID
    transaction_id: uuid.UUID | None = None
    description: str | None = None


@dataclass(frozen=True)
class CashJournalEntry:
    """Ligne de journal de caisse persistée, rattachée à un salon (PRD §9.7).

    Projection de **lecture** : porte l'horodatage (`created_at`), l'auteur
    (`performed_by`) et son **nom d'affichage résolu** (`performed_by_name`, staff du
    salon — non sensible dans ce périmètre), le type d'opération, le montant **signé**
    (positif pour un `PAYMENT`, signé pour un `ADJUSTMENT`), la devise, le lien vers
    la transaction (`transaction_id`) et le motif (`description`).
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    operation_type: str
    amount: decimal.Decimal
    currency: str
    performed_by: uuid.UUID
    performed_by_name: str | None
    transaction_id: uuid.UUID | None
    description: str | None
    created_at: datetime.datetime


__all__ = [
    "ADJUSTMENT_ABS_MAX",
    "DESCRIPTION_MAX_LENGTH",
    "validate_adjustment_amount",
    "normalize_description",
    "CashJournalToAppend",
    "CashJournalEntry",
]
