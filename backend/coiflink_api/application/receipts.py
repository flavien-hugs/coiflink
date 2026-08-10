"""Cas d'usage : **reçu numérique de paiement** côté client (US-5.5, #38).

Tranche applicative hexagonale : ces cas d'usage ne dépendent que d'un **port**
(`ReceiptRepository`) — aucune dépendance FastAPI/SQLAlchemy. Ils matérialisent le
critère d'acceptation #38 :

> Un reçu est généré/envoyé après paiement.

L'interprétation MVP (voir la spec) est **« généré + récupérable »** : le reçu est
une projection en lecture dérivée du paiement déjà persisté (#33), récupérable par
le client via un endpoint d'**appartenance**. Aucune **remise** proactive
(push/SMS) n'est effectuée — elle relève de M5 (Épic 7, ADR-0006).

`ListMyReceipts` / `GetMyReceipt` sont des **lectures pures** (patron #29/#30/#31) :
aucune écriture, aucun audit (la consultation d'un reçu n'est pas une action
§11.4). Ils **imposent** `client_id = actor_user_id` — jamais un identifiant soumis
par l'appelant (appartenance §11.2). Ni `MANAGER`, ni `HAIRDRESSER`, ni `ADMIN` ne
détiennent la permission : seule la matrice `PAYMENT_READ_OWN` (CLIENT) ouvre ces
lectures.
"""

from __future__ import annotations

import uuid

from coiflink_api.application.ports.receipt_repository import ReceiptRepository
from coiflink_api.domain.receipt import Receipt


class ListMyReceipts:
    """Liste paginée des reçus du **client authentifié** (lecture — pas d'audit).

    Retourne `(page, total)` : la page de reçus (plus récents d'abord) et le total
    (pagination correcte). L'appartenance est **forcée** : le `client_id` provient
    de l'acteur, jamais d'un paramètre soumis.
    """

    def __init__(self, receipt_repo: ReceiptRepository) -> None:
        self._receipt_repo = receipt_repo

    def execute(
        self,
        actor_user_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[tuple[Receipt, ...], int]:
        """Retourne `(page, total)` — reçus du client, plus récents d'abord."""

        page = self._receipt_repo.list_receipts_for_client(
            actor_user_id, limit=limit, offset=offset
        )
        total = self._receipt_repo.count_receipts_for_client(actor_user_id)
        return page, total


class GetMyReceipt:
    """Reçu précis du **client authentifié** ou `None` (→ `404` neutre, non-oracle).

    L'appartenance est **forcée** (`client_id = actor_user_id`) : un `payment_id`
    d'un autre client (ou inexistant) donne `None`, **indiscernable** (§11.3).
    Lecture pure : aucune écriture, aucun audit.
    """

    def __init__(self, receipt_repo: ReceiptRepository) -> None:
        self._receipt_repo = receipt_repo

    def execute(
        self, actor_user_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Receipt | None:
        """Retourne le reçu du client ou `None` (paiement inexistant/hors appartenance)."""

        return self._receipt_repo.get_receipt_for_client(actor_user_id, payment_id)


class GetSalonReceipt:
    """Reçu précis d'un paiement du **salon du gérant** — impression (ADR-0040).

    Portée **salon**, pas `client_id` : inclut les paiements comptoir sans client
    rattaché (contrairement à `GetMyReceipt`). `None` si le paiement n'existe pas
    **ou** appartient à un autre salon — indiscernable (§11.3, `require_salon_scope`
    a déjà validé que l'acteur gère bien `salon_id` en amont). Lecture pure : aucune
    écriture, aucun audit — consulter/imprimer un reçu n'est pas une action §11.4.
    """

    def __init__(self, receipt_repo: ReceiptRepository) -> None:
        self._receipt_repo = receipt_repo

    def execute(self, salon_id: uuid.UUID, payment_id: uuid.UUID) -> Receipt | None:
        """Retourne le reçu du salon ou `None` (paiement inexistant/autre salon)."""

        return self._receipt_repo.get_receipt_for_salon(salon_id, payment_id)


__all__ = ["ListMyReceipts", "GetMyReceipt", "GetSalonReceipt"]
