"""Faux adaptateurs partagés entre les suites de tests (inscription #8).

Chaque fake implémente le protocole du port correspondant sans I/O réelle.
Aucune valeur secrète réelle ni PII n'est utilisée dans ces fixtures.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from coiflink_api.domaine.erreurs import TelephoneDejaUtilise
from coiflink_api.domaine.otp import DefiOtp
from coiflink_api.domaine.utilisateur import Utilisateur, UtilisateurACreer

_CREATED_AT = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_UUID_FIXE = uuid.UUID("00000000-0000-0000-0000-000000000001")


class FakeHacheur:
    """Hacheur déterministe (préfixe « hash: »). Ne produit jamais le clair tel quel."""

    def hacher(self, clair: str) -> str:
        return f"hash:{clair}"

    def verifier(self, clair: str, condensat: str) -> bool:
        return condensat == f"hash:{clair}"


class FakeDepotUtilisateur:
    """Dépôt en mémoire pour les tests unitaires et API."""

    def __init__(self, telephones_existants: set[str] | None = None) -> None:
        self._telephones: set[str] = set(telephones_existants or [])
        self.crees: list[UtilisateurACreer] = []

    def telephone_existe(self, telephone: str) -> bool:
        return telephone in self._telephones

    def creer(self, utilisateur: UtilisateurACreer) -> Utilisateur:
        self.crees.append(utilisateur)
        self._telephones.add(utilisateur.telephone)
        return Utilisateur(
            id=_UUID_FIXE,
            full_name=utilisateur.full_name,
            telephone=utilisateur.telephone,
            email=utilisateur.email,
            role=utilisateur.role,
            status=utilisateur.status,
            created_at=_CREATED_AT,
        )


class FakeDepotUtilisateurLeveDublon:
    """Depot dont `creer` lève TelephoneDejaUtilise (simulation d'IntegrityError concurrente)."""

    def telephone_existe(self, telephone: str) -> bool:  # noqa: ARG002
        return False

    def creer(self, utilisateur: UtilisateurACreer) -> Utilisateur:  # noqa: ARG002
        raise TelephoneDejaUtilise("Contrainte base violée (race condition simulée).")


class FakeExpediteurOtp:
    """Expéditeur OTP en mémoire ; ne journalise rien."""

    def __init__(self) -> None:
        self.envois: list[tuple[str, str]] = []

    def envoyer(self, telephone: str, code: str) -> None:
        self.envois.append((telephone, code))


class FakeDepotOtp:
    """Dépôt OTP en mémoire."""

    def __init__(self) -> None:
        self.defis: dict[str, DefiOtp] = {}

    def enregistrer(self, telephone: str, defi: DefiOtp) -> None:
        self.defis[telephone] = defi

    def recuperer(self, telephone: str) -> DefiOtp | None:
        return self.defis.get(telephone)

    def supprimer(self, telephone: str) -> None:
        self.defis.pop(telephone, None)


# ── Fixtures pytest partagées ──────────────────────────────────────────────


@pytest.fixture()
def fake_hacheur() -> FakeHacheur:
    return FakeHacheur()


@pytest.fixture()
def fake_depot() -> FakeDepotUtilisateur:
    return FakeDepotUtilisateur()


@pytest.fixture()
def fake_expediteur() -> FakeExpediteurOtp:
    return FakeExpediteurOtp()


@pytest.fixture()
def fake_depot_otp() -> FakeDepotOtp:
    return FakeDepotOtp()
