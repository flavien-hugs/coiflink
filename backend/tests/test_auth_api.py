"""Tests API pour `POST /auth/register` (adapter entrant, #8).

Utilise FastAPI `TestClient` avec override de `get_inscrire_client` pour
injecter un `InscrireClient` à ports fakes — aucune base de données réelle.
Vérifie : 201 succès, non-fuite du mot de passe, 409 doublon, 422 validation.
"""

from __future__ import annotations

import datetime
from collections.abc import Generator
from random import Random

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.entrant.auth import get_inscrire_client
from coiflink_api.application.inscription import InscrireClient
from coiflink_api.domaine.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FakeDepotOtp,
    FakeDepotUtilisateur,
    FakeExpediteurOtp,
    FakeHacheur,
)

_MAINTENANT = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

_CORPS_VALIDE = {
    "full_name": "Awa Koné",
    "phone": "0700000000",
    "password": "motdepasse-solide",
}


def _construire_usecase(
    telephones_existants: set[str] | None = None,
    otp_active: bool = False,
) -> InscrireClient:
    return InscrireClient(
        depot=FakeDepotUtilisateur(telephones_existants=telephones_existants),
        hacheur=FakeHacheur(),
        otp_active=otp_active,
        expediteur_otp=FakeExpediteurOtp(),
        depot_otp=FakeDepotOtp(),
        rng=Random(42),
        horloge=lambda: _MAINTENANT,
    )


@pytest.fixture()
def client_sans_db() -> Generator[TestClient, None, None]:
    """TestClient dont `get_inscrire_client` est remplacé par un fake."""

    def _fake_inscrire_client() -> InscrireClient:
        return _construire_usecase()

    app.dependency_overrides[get_inscrire_client] = _fake_inscrire_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_inscrire_client, None)


@pytest.fixture()
def client_doublon() -> Generator[TestClient, None, None]:
    """TestClient dont le dépôt contient déjà le téléphone normalisé."""

    def _fake_inscrire_client() -> InscrireClient:
        return _construire_usecase(telephones_existants={"+2250700000000"})

    app.dependency_overrides[get_inscrire_client] = _fake_inscrire_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_inscrire_client, None)


class TestInscriptionSucces:
    def test_statut_201(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert r.status_code == 201

    def test_corps_contient_id(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert "id" in r.json()

    def test_corps_contient_full_name(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert r.json()["full_name"] == "Awa Koné"

    def test_corps_contient_phone(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert "phone" in r.json()

    def test_corps_contient_role_client(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert r.json()["role"] == Role.CLIENT.value

    def test_corps_contient_statut_active(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert r.json()["status"] == UserStatus.ACTIVE.value

    def test_corps_contient_created_at(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert "created_at" in r.json()

    def test_email_optionnel_absent_retourne_null(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert r.json()["email"] is None

    def test_avec_email_optionnel(self, client_sans_db: TestClient) -> None:
        corps = {**_CORPS_VALIDE, "email": "awa@example.com"}
        r = client_sans_db.post("/auth/register", json=corps)
        assert r.status_code == 201


class TestNonFuiteSecret:
    def test_password_absent_de_la_reponse(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        corps = r.json()
        assert "password" not in corps

    def test_password_hash_absent_de_la_reponse(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        corps = r.json()
        assert "password_hash" not in corps

    def test_valeur_du_mot_de_passe_absente_du_corps_json(self, client_sans_db: TestClient) -> None:
        mdp = "motdepasse-solide"
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "password": mdp})
        assert mdp not in r.text

    def test_condensat_absent_du_corps_json(self, client_sans_db: TestClient) -> None:
        """Le condensat fake 'hash:motdepasse-solide' ne doit pas apparaître dans la réponse."""
        mdp = "motdepasse-solide"
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "password": mdp})
        assert f"hash:{mdp}" not in r.text


class TestDoublonTelephone:
    def test_doublon_retourne_409(self, client_doublon: TestClient) -> None:
        r = client_doublon.post("/auth/register", json=_CORPS_VALIDE)
        assert r.status_code == 409

    def test_doublon_format_local_retourne_409(self, client_doublon: TestClient) -> None:
        """0700000000 (local) est normalisé → reconnu comme doublon."""
        r = client_doublon.post("/auth/register", json={**_CORPS_VALIDE, "phone": "0700000000"})
        assert r.status_code == 409

    def test_doublon_format_e164_retourne_409(self, client_doublon: TestClient) -> None:
        r = client_doublon.post("/auth/register", json={**_CORPS_VALIDE, "phone": "+2250700000000"})
        assert r.status_code == 409


class TestValidationPydantic:
    def test_champ_full_name_manquant_retourne_422(self, client_sans_db: TestClient) -> None:
        corps = {k: v for k, v in _CORPS_VALIDE.items() if k != "full_name"}
        r = client_sans_db.post("/auth/register", json=corps)
        assert r.status_code == 422

    def test_champ_phone_manquant_retourne_422(self, client_sans_db: TestClient) -> None:
        corps = {k: v for k, v in _CORPS_VALIDE.items() if k != "phone"}
        r = client_sans_db.post("/auth/register", json=corps)
        assert r.status_code == 422

    def test_champ_password_manquant_retourne_422(self, client_sans_db: TestClient) -> None:
        corps = {k: v for k, v in _CORPS_VALIDE.items() if k != "password"}
        r = client_sans_db.post("/auth/register", json=corps)
        assert r.status_code == 422

    def test_email_invalide_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "email": "pas-un-email"})
        assert r.status_code == 422

    def test_full_name_vide_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "full_name": ""})
        assert r.status_code == 422

    def test_password_trop_court_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "password": "court"})
        assert r.status_code == 422

    def test_corps_json_vide_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={})
        assert r.status_code == 422


class TestValidationDomaine:
    def test_telephone_invalide_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "phone": "abcdefg"})
        assert r.status_code == 422

    def test_telephone_trop_court_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "phone": "123"})
        assert r.status_code == 422


class TestContentType:
    def test_content_type_json(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json=_CORPS_VALIDE)
        assert "application/json" in r.headers.get("content-type", "")


class TestLimitesChamps:
    def test_full_name_256_caracteres_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "full_name": "a" * 256})
        assert r.status_code == 422

    def test_phone_33_caracteres_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "phone": "0" * 33})
        assert r.status_code == 422

    def test_password_129_caracteres_retourne_422(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "password": "a" * 129})
        assert r.status_code == 422

    def test_full_name_255_caracteres_accepte(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "full_name": "a" * 255})
        assert r.status_code == 201

    def test_password_128_caracteres_accepte(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post(
            "/auth/register", json={**_CORPS_VALIDE, "password": "a" * 128}
        )
        assert r.status_code == 201


class TestNormalisationReponse:
    def test_phone_local_retourne_e164_dans_reponse(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.post("/auth/register", json={**_CORPS_VALIDE, "phone": "0700000000"})
        assert r.status_code == 201
        assert r.json()["phone"] == "+2250700000000"

    def test_doublon_reponse_contient_detail_non_vide(self, client_doublon: TestClient) -> None:
        r = client_doublon.post("/auth/register", json=_CORPS_VALIDE)
        assert r.status_code == 409
        corps = r.json()
        assert "detail" in corps
        assert corps["detail"]

    def test_doublon_reponse_detail_ne_contient_pas_le_telephone(
        self, client_doublon: TestClient
    ) -> None:
        """Le message d'erreur 409 ne doit pas exposer le numéro de téléphone."""
        r = client_doublon.post("/auth/register", json=_CORPS_VALIDE)
        assert r.status_code == 409
        assert "0700000000" not in r.text
        assert "+2250700000000" not in r.text


class TestMethodeHTTP:
    def test_get_register_retourne_405(self, client_sans_db: TestClient) -> None:
        r = client_sans_db.get("/auth/register")
        assert r.status_code == 405
