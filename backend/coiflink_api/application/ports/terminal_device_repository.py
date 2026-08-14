"""Port de persistance des **bornes terminal** (`Protocol`, US-8.1, #155).

Le cas d'usage de provisioning (`application/terminal_devices.py`) et
l'authentification du device (`application/terminal_authentication.py`) déclarent ici
leurs besoins ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/terminal_device_repository.py`.

**Encapsulation (décision d'architecture d'ADR-0041)** : ce port cache que la
borne vit comme un compte de service `users` (rôle `TERMINAL`) + un rattachement
`salon_members` (portée mono-salon). Les cas d'usage n'en savent rien — un port
dédié permettrait de migrer plus tard vers une table propre sans toucher aux
gardes ni aux cas d'usage.

**Portée salon (§11.2)** : les lectures/écritures de gestion (`list_for_salon`,
`find_by_id`, `revoke`) sont **salon-scopées** — une borne d'un autre salon est
indiscernable d'une borne inexistante (aucun oracle). Seul `find_credentials`
(chemin de login) est scopé par `device_id` seul : il résout la portée du device
et n'expose **jamais** rien au client (échec → `401` générique).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.terminal_device import (
    TerminalDevice,
    TerminalDeviceCredentials,
    TerminalDeviceToCreate,
)


class TerminalDeviceRepository(Protocol):
    """Contrat de persistance des bornes terminal (compte de service encapsulé)."""

    def create(self, device: TerminalDeviceToCreate) -> TerminalDevice:
        """Provisionne une borne (compte `users` `TERMINAL` + rattachement `salon_members`).

        Les deux écritures partagent la **même `Session`** (commit piloté par
        `get_session`) : une borne provisionnée = deux lignes atomiques. Retourne
        l'entité **sans** secret ni condensat.
        """
        ...

    def list_for_salon(self, salon_id: uuid.UUID) -> tuple[TerminalDevice, ...]:
        """Liste les bornes du salon (actives **et** révoquées, traçabilité §11.4).

        L'isolation §11.2 est imposée **en SQL** (`WHERE salon_id`), en défense en
        profondeur de la garde HTTP `require_salon_scope`. Lecture pure, jamais de
        secret.
        """
        ...

    def find_by_id(
        self, salon_id: uuid.UUID, device_id: uuid.UUID
    ) -> TerminalDevice | None:
        """Charge la borne `(salon_id, device_id)`, ou `None`.

        Le filtre porte sur `salon_id` **et** `device_id` : une borne d'un autre
        salon est indiscernable d'un identifiant inexistant (aucun oracle, §11.2).
        Le cas d'usage lève alors `TerminalDeviceNotFound` (`404` **après** la portée).
        """
        ...

    def find_credentials(
        self, device_id: uuid.UUID
    ) -> TerminalDeviceCredentials | None:
        """Charge le credential d'une borne pour l'**authentification** ; `None` sinon.

        Scopé au seul `device_id` (le login ne connaît pas encore le salon). Ne
        résout **que** les comptes de service `TERMINAL` : un `device_id` pointant un
        compte personnel renvoie `None` (aucun oracle). L'entité renvoyée porte le
        `password_hash` — elle n'est **jamais** sérialisée.
        """
        ...

    def set_password_hash(self, device_id: uuid.UUID, password_hash: str) -> None:
        """Remplace le condensat de la borne (activation, US-8.1, #155).

        Écrase le condensat placeholder posé au provisioning par le condensat du
        secret réel, généré au moment de l'activation. Idempotent au sens où un
        `device_id` inconnu ne doit jamais lever (aucun oracle) — mais en pratique
        `ActivateTerminalDevice` n'appelle ceci qu'après avoir résolu un `device_id`
        valide via `find_by_code`, donc ce cas ne devrait pas se produire.
        """
        ...

    def revoke(
        self, salon_id: uuid.UUID, device_id: uuid.UUID
    ) -> TerminalDevice | None:
        """Révoque une borne (suspension logique) ; `None` si hors salon / inexistante.

        Défense en profondeur : suspend le compte de service (`users.status =
        SUSPENDED`, coupe l'accès à la requête suivante via `get_current_principal`)
        **et** vide la portée (`salon_members.status = INACTIVE`). Révocation
        **logique** — jamais une suppression physique (traçabilité §11.4). `None`
        (jamais une exception) si `(salon_id, device_id)` ne correspond à aucune borne.
        """
        ...


__all__ = ["TerminalDeviceRepository"]
