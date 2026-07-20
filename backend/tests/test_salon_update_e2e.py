"""Tests e2e pour US-2.5 — Modification des informations du salon & réflexion client (#20).

Groupe TestSalonUpdateReflectionE2E (PostgreSQL requis) :
    pile complète : HTTP (TestClient) → router → cas d'usage → dépôt SQL réel
    + journal d'audit réel (`audit_logs`) + JWT réel.

Le chemin d'écriture (`PUT /salons/{id}`) est déjà livré avec #15 : ce fichier ne
le ré-implémente pas — il **verrouille le second membre du critère d'acceptation**
(« les changements sont reflétés côté client »), aujourd'hui vrai « par
construction » (le catalogue #18 / la fiche #19 relisent les mêmes lignes `salons`,
sans cache) mais couvert par aucun test bout-en-bout.

Scénarios :
    1. Réflexion catalogue + fiche : après `PUT /salons/{id}`, les nouvelles valeurs
       (nom, ville, commune, description, téléphone, coordonnées) apparaissent dans
       `GET /catalog/salons` (liste/recherche) **et** `GET /catalog/salons/{id}`.
    2. Fraîcheur : `updated_at` est rafraîchi par la modification.
    3. Étanchéité de projection : la réponse catalogue n'expose jamais `owner_id`,
       `status`, ni clé d'objet brute — quelle que soit la modification.
    4. Audit : une entrée `SALON_UPDATED` existe pour le bon acteur/salon, et
       `metadata` ne contient aucune valeur de champ ni PII (§11.3/§11.4).
    5. Visibilité §8.3 : un salon rendu non `ACTIVE` reste absent du catalogue et sa
       fiche renvoie 404, même après un `PUT /salons/{id}` réussi (pas de fuite).
    6. Isolation inter-gérants : le jeton du gérant A est refusé sur le salon de B
       (403 générique, aucune donnée fuitée).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_salon_update_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225074998xxxx).
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.outbound.persistence.session import get_engine
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-salon-update-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e de modification de salon (distincte de
# celle de `test_service_e2e.py` pour un nettoyage sans collision).
_E2E_PHONE_PREFIX = "+225074998"
_PHONE_A_LOCAL = "0749980001"   # gérant A — parcours de réflexion principal
_PHONE_B_LOCAL = "0749980002"   # gérant B — isolation inter-gérants
_PASSWORD = "salon-update-e2e-strong-password-2024"

# Valeurs initiales et cibles (le nom pivote pour prouver que la recherche suit).
_OLD_NAME = "e2e-salon-avant-modif"
_NEW_NAME = "e2e-salon-apres-modif"
_SALON_NAME_B = "e2e-salon-update-b"

_OLD_CITY = "Abidjan"
_NEW_CITY = "Bouaké"
_OLD_COMMUNE = "Cocody"
_NEW_COMMUNE = "Marcory"
_NEW_PHONE_LOCAL = "0700112233"
_NEW_DESCRIPTION = "Salon rénové : coupe, tresses et soins."
_NEW_LATITUDE = 7.689
_NEW_LONGITUDE = -5.030

_VALID_HOURS = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → services → salon_members → salons → users.
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "DELETE FROM audit_logs WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM services WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE user_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text("DELETE FROM users WHERE phone LIKE :prefix"),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT).

    - Injecte un JwtTokenService de test (secret local, jamais en production).
    - Supprime les données de test (plage +225074998) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e de modification de salon.")

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)

    main_app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    main_app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=10,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )

    _wipe_test_data()
    try:
        yield TestClient(main_app)
    finally:
        _wipe_test_data()
        main_app.state.token_service = orig_token_service
        main_app.state.login_rate_limiter = orig_rate_limiter


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _register_manager(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    """Inscrit un compte gérant via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Modif", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str = _OLD_NAME) -> str:
    """Crée un salon (valeurs initiales) via l'API et retourne son UUID."""
    resp = client.post(
        "/salons",
        json={
            "name": name,
            "description": "Salon d'origine.",
            "city": _OLD_CITY,
            "commune": _OLD_COMMUNE,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _set_opening_hours(client: TestClient, token: str, salon_id: str) -> None:
    """Enregistre des horaires valides (rend le salon réservable, §8.3)."""
    resp = client.put(
        f"/salons/{salon_id}/opening-hours",
        json=_VALID_HOURS,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Horaires refusés : {resp.text}"


def _new_body(name: str = _NEW_NAME) -> dict:
    """Corps de `PUT /salons/{id}` portant les nouvelles informations."""
    return {
        "name": name,
        "description": _NEW_DESCRIPTION,
        "phone": _NEW_PHONE_LOCAL,
        "city": _NEW_CITY,
        "commune": _NEW_COMMUNE,
        "latitude": _NEW_LATITUDE,
        "longitude": _NEW_LONGITUDE,
    }


def _update_salon(client: TestClient, token: str, salon_id: str, body: dict) -> None:
    """Modifie les informations d'un salon via `PUT /salons/{id}`."""
    resp = client.put(
        f"/salons/{salon_id}",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Modification refusée : {resp.text}"


def _catalog_item(client: TestClient, salon_id: str, *, q: str | None = None) -> dict | None:
    """Retourne l'entrée catalogue d'un salon donné, ou `None` s'il est absent."""
    params = {"q": q} if q is not None else None
    resp = client.get("/catalog/salons", params=params)
    assert resp.status_code == 200, f"Catalogue indisponible : {resp.text}"
    for item in resp.json()["items"]:
        if item["id"] == salon_id:
            return item
    return None


def _set_status_in_db(salon_id: str, status_value: str) -> None:
    """Force le `status` d'un salon en base (aucune route ne le modifie, §8.3)."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE salons SET status = :status WHERE id = :sid"),
            {"status": status_value, "sid": salon_id},
        )
        conn.commit()


def _fetch_salon_audit_entries(salon_id: str) -> list[dict]:
    """Récupère les entrées d'audit `salon` pour un salon, en ordre chronologique."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT action, actor_user_id, salon_id, entity_type, entity_id, "
                "metadata FROM audit_logs "
                "WHERE entity_type = 'salon' AND entity_id = :sid "
                "ORDER BY created_at"
            ),
            {"sid": salon_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _fetch_updated_at(salon_id: str) -> datetime.datetime:
    """Lit `updated_at` d'un salon directement en base."""
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT updated_at FROM salons WHERE id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestSalonUpdateReflectionE2E:
    """Réflexion client bout-en-bout : PUT gérant → catalogue/fiche + audit + §8.3."""

    # ── Parcours 1 : lecture initiale (avant modification) ───────────────────

    def test_catalog_shows_old_values_before_update(
        self, _e2e_client: TestClient
    ) -> None:
        """Avant modification, le catalogue renvoie le salon avec ses valeurs initiales."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)

        item = _catalog_item(_e2e_client, salon_id, q=_OLD_NAME)
        assert item is not None
        assert item["name"] == _OLD_NAME
        assert item["city"] == _OLD_CITY

    # ── Parcours 2 : réflexion en liste/recherche ────────────────────────────

    def test_catalog_reflects_new_name_after_update(
        self, _e2e_client: TestClient
    ) -> None:
        """Après PUT, le salon apparaît sous son **nouveau** nom dans la recherche."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)

        _update_salon(_e2e_client, token, salon_id, _new_body())

        item = _catalog_item(_e2e_client, salon_id, q=_NEW_NAME)
        assert item is not None
        assert item["name"] == _NEW_NAME
        assert item["city"] == _NEW_CITY
        assert item["commune"] == _NEW_COMMUNE

    def test_catalog_no_longer_matches_old_name_after_update(
        self, _e2e_client: TestClient
    ) -> None:
        """Après PUT, une recherche sur l'ancien nom ne renvoie plus ce salon."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)

        _update_salon(_e2e_client, token, salon_id, _new_body())

        assert _catalog_item(_e2e_client, salon_id, q=_OLD_NAME) is None

    def test_catalog_reflects_new_coordinates_after_update(
        self, _e2e_client: TestClient
    ) -> None:
        """Après PUT, la localisation (coordonnées) est reflétée dans le catalogue."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)

        _update_salon(_e2e_client, token, salon_id, _new_body())

        item = _catalog_item(_e2e_client, salon_id, q=_NEW_NAME)
        assert item is not None
        assert item["latitude"] == pytest.approx(_NEW_LATITUDE)
        assert item["longitude"] == pytest.approx(_NEW_LONGITUDE)

    # ── Parcours 3 : réflexion en fiche publique ─────────────────────────────

    def test_detail_reflects_new_values_after_update(
        self, _e2e_client: TestClient
    ) -> None:
        """Après PUT, la fiche publique renvoie les nouvelles valeurs (dont `phone`, #19)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)

        _update_salon(_e2e_client, token, salon_id, _new_body())

        resp = _e2e_client.get(f"/catalog/salons/{salon_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == _NEW_NAME
        assert body["city"] == _NEW_CITY
        assert body["commune"] == _NEW_COMMUNE
        assert body["description"] == _NEW_DESCRIPTION
        # `phone` est normalisé au format international par le domaine.
        assert body["phone"] is not None
        assert body["phone"].endswith("0112233")

    # ── Parcours 4 : fraîcheur (`updated_at` rafraîchi) ──────────────────────

    def test_update_refreshes_updated_at(self, _e2e_client: TestClient) -> None:
        """La modification rafraîchit `updated_at` (fraîcheur observable, #20)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        before = _fetch_updated_at(salon_id)
        _update_salon(_e2e_client, token, salon_id, _new_body())
        after = _fetch_updated_at(salon_id)

        assert after > before

    # ── Parcours 5 : étanchéité de la projection publique ────────────────────

    def test_catalog_item_hides_management_fields(
        self, _e2e_client: TestClient
    ) -> None:
        """La vitrine catalogue n'expose ni `owner_id`, ni `status`, ni clé brute."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)
        _update_salon(_e2e_client, token, salon_id, _new_body())

        item = _catalog_item(_e2e_client, salon_id, q=_NEW_NAME)
        assert item is not None
        assert "owner_id" not in item
        assert "status" not in item
        assert "logo_object_key" not in item

    def test_detail_hides_management_fields(self, _e2e_client: TestClient) -> None:
        """La fiche de détail n'expose ni `owner_id`, ni `status`, ni clé brute."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)
        _update_salon(_e2e_client, token, salon_id, _new_body())

        resp = _e2e_client.get(f"/catalog/salons/{salon_id}")
        body = resp.json()
        assert "owner_id" not in body
        assert "status" not in body
        assert "logo_object_key" not in body

    # ── Parcours 6 : audit §11.4 (présence + neutralité) ─────────────────────

    def test_update_records_salon_updated_audit_entry(
        self, _e2e_client: TestClient
    ) -> None:
        """Le PUT enregistre une entrée `SALON_UPDATED` pour le bon acteur/salon."""
        manager_id = _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _update_salon(_e2e_client, token, salon_id, _new_body())

        entries = _fetch_salon_audit_entries(salon_id)
        updates = [e for e in entries if e["action"] == "SALON_UPDATED"]
        assert len(updates) == 1
        entry = updates[0]
        assert str(entry["actor_user_id"]) == manager_id
        assert str(entry["salon_id"]) == salon_id

    def test_audit_metadata_contains_only_field_names(
        self, _e2e_client: TestClient
    ) -> None:
        """`metadata.changed` ne liste que des noms de champs, jamais des valeurs/PII."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _update_salon(_e2e_client, token, salon_id, _new_body())

        entry = next(
            e for e in _fetch_salon_audit_entries(salon_id)
            if e["action"] == "SALON_UPDATED"
        )
        assert set(entry["metadata"].keys()) == {"changed"}
        changed = entry["metadata"]["changed"]
        assert "name" in changed
        assert "city" in changed
        # Aucune valeur ni PII ne doit fuiter dans les métadonnées.
        blob = str(entry["metadata"])
        assert _NEW_NAME not in blob
        assert _NEW_CITY not in blob
        assert _NEW_DESCRIPTION not in blob
        assert _NEW_PHONE_LOCAL not in blob

    def test_update_response_contains_no_token(self, _e2e_client: TestClient) -> None:
        """La réponse de modification ne révèle pas le jeton d'accès (PRD §11.1)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.put(
            f"/salons/{salon_id}",
            json=_new_body(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert token not in resp.text

    # ── Parcours 7 : visibilité §8.3 (la réflexion n'ouvre pas de fuite) ─────

    def test_inactive_salon_absent_from_catalog_after_update(
        self, _e2e_client: TestClient
    ) -> None:
        """Un salon non `ACTIVE` reste absent du catalogue, même après un PUT réussi."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)
        _set_status_in_db(salon_id, "INACTIVE")

        # Le gérant garde la main sur son salon (portée conservée) : le PUT réussit.
        _update_salon(_e2e_client, token, salon_id, _new_body())

        assert _catalog_item(_e2e_client, salon_id, q=_NEW_NAME) is None

    def test_inactive_salon_detail_returns_404_after_update(
        self, _e2e_client: TestClient
    ) -> None:
        """La fiche d'un salon non `ACTIVE` renvoie 404 (pas d'oracle), même après PUT."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _set_opening_hours(_e2e_client, token, salon_id)
        _set_status_in_db(salon_id, "INACTIVE")
        _update_salon(_e2e_client, token, salon_id, _new_body())

        resp = _e2e_client.get(f"/catalog/salons/{salon_id}")
        assert resp.status_code == 404

    # ── Parcours 8 : isolation inter-gérants (§11.2) ─────────────────────────

    def test_cross_manager_update_returns_403(self, _e2e_client: TestClient) -> None:
        """Le gérant A ne peut pas modifier le salon du gérant B → 403 générique."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.put(
            f"/salons/{salon_b_id}",
            json=_new_body(),
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Accès refusé."
        assert salon_b_id not in resp.text

    def test_cross_manager_update_does_not_mutate_target(
        self, _e2e_client: TestClient
    ) -> None:
        """Le 403 inter-gérants ne modifie pas le salon cible (aucune écriture)."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        _set_opening_hours(_e2e_client, token_b, salon_b_id)

        _e2e_client.put(
            f"/salons/{salon_b_id}",
            json=_new_body(),
            headers={"Authorization": f"Bearer {token_a}"},
        )

        # Le salon de B garde son nom d'origine dans le catalogue.
        item = _catalog_item(_e2e_client, salon_b_id, q=_SALON_NAME_B)
        assert item is not None
        assert item["name"] == _SALON_NAME_B

    # ── Parcours 9 : deny-by-default ─────────────────────────────────────────

    def test_no_token_on_update_returns_401(self, _e2e_client: TestClient) -> None:
        """PUT sans jeton → 401 (deny-by-default, ADR-0015)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.put(f"/salons/{salon_id}", json=_new_body())
        assert resp.status_code == 401
