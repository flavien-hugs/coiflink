"""Tests e2e pour US-2.3 — CRUD des prestations & journalisation §11.4 (#17).

Groupe TestServiceCrudE2E (PostgreSQL requis) :
    pile complète : HTTP (TestClient) → router → cas d'usage → dépôt SQL réel
    + journal d'audit réel (`audit_logs`) + JWT réel.

Scénarios :
    1. Parcours CRUD complet :
       inscription gérant → connexion → création salon → création prestation →
       liste (la prestation apparaît) → modification (valeurs à jour, audit) →
       consultation (valeurs mises à jour) → désactivation (is_active=false, audit).
    2. Traçabilité complète : SERVICE_CREATED → SERVICE_UPDATED → SERVICE_DEACTIVATED
       enregistrées dans l'ordre avec le bon acteur ; aucun secret ni PII dans
       les métadonnées (invariant §11.3/§11.4).
    3. Isolation inter-salons : le jeton du gérant A est refusé sur les services
       du salon du gérant B (403 générique, message constant, aucune donnée fuitée).
    4. Validation bout-en-bout : prix ou durée manquants/invalides → 422 ;
       aucune entrée d'audit créée sur validation échouée (atomicité).
    5. Deny-by-default : accès sans jeton → 401 sur toutes les routes.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_service_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225074999xxxx).
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
_TEST_JWT_SECRET = "test-only-service-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e de gestion des prestations.
_E2E_PHONE_PREFIX = "+225074999"
_PHONE_A_LOCAL = "0749990001"   # gérant A — parcours CRUD principal
_PHONE_B_LOCAL = "0749990002"   # gérant B — isolation inter-salons
_PASSWORD = "service-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-service-a"
_SALON_NAME_B = "e2e-salon-service-b"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → services → salon_members → salons → users.
    - `audit_logs.actor_user_id → users.id RESTRICT` et
      `audit_logs.salon_id → salons.id RESTRICT` : journal supprimé en premier.
    - `services.salon_id → salons.id RESTRICT` : prestations avant les salons.
    """
    engine = get_engine()
    with engine.connect() as conn:
        # Journal d'audit (FK vers users et salons).
        conn.execute(
            text(
                "DELETE FROM audit_logs WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        # Prestations (FK salon_id → salons RESTRICT).
        conn.execute(
            text(
                "DELETE FROM services WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        # Membres du salon (FK salon_id → salons et user_id → users RESTRICT).
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
        # Salons (FK owner_id → users RESTRICT).
        conn.execute(
            text(
                "DELETE FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        # Comptes utilisateurs.
        conn.execute(
            text("DELETE FROM users WHERE phone LIKE :prefix"),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT).

    - Injecte un JwtTokenService de test (secret local, jamais en production) sur app.state.
    - Supprime les données de test (plage +225074999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e de gestion des prestations.")

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
        json={"full_name": "Gérant E2E Services", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post(
        "/auth/login", json={"identifier": phone, "password": _PASSWORD}
    )
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str = _SALON_NAME_A) -> str:
    """Crée un salon via l'API et retourne son UUID."""
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _services_url(salon_id: str) -> str:
    return f"/salons/{salon_id}/services"


def _service_url(salon_id: str, service_id: str) -> str:
    return f"/salons/{salon_id}/services/{service_id}"


def _count_audit_entries(service_id: str, action: str | None = None) -> int:
    """Compte les entrées d'audit `audit_logs` pour une prestation donnée."""
    engine = get_engine()
    with engine.connect() as conn:
        if action:
            result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_logs "
                    "WHERE entity_type = 'service' AND entity_id = :eid AND action = :action"
                ),
                {"eid": service_id, "action": action},
            )
        else:
            result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_logs "
                    "WHERE entity_type = 'service' AND entity_id = :eid"
                ),
                {"eid": service_id},
            )
        return result.scalar_one()


def _fetch_audit_entries(service_id: str) -> list[dict]:
    """Récupère toutes les entrées d'audit pour une prestation, en ordre chronologique."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT action, actor_user_id, salon_id, entity_type, entity_id, "
                "metadata FROM audit_logs "
                "WHERE entity_type = 'service' AND entity_id = :eid "
                "ORDER BY created_at"
            ),
            {"eid": service_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestServiceCrudE2E:
    """CRUD prestations bout-en-bout : HTTP → cas d'usage → SQL réel + audit réel."""

    # ── Parcours 1 : création ────────────────────────────────────────────────

    def test_create_service_returns_201(self, _e2e_client: TestClient) -> None:
        """POST /salons/{id}/services → 201 avec une prestation active."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    def test_create_service_response_is_active(self, _e2e_client: TestClient) -> None:
        """La prestation créée est active (`is_active=true`)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["is_active"] is True

    def test_create_service_salon_id_matches_path(self, _e2e_client: TestClient) -> None:
        """La réponse `salon_id` correspond à la portée du chemin, jamais au corps."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["salon_id"] == salon_id

    def test_create_service_records_service_created_audit_entry(
        self, _e2e_client: TestClient
    ) -> None:
        """La création enregistre une entrée `SERVICE_CREATED` dans `audit_logs`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp.json()["id"]
        assert _count_audit_entries(service_id, "SERVICE_CREATED") == 1

    def test_create_service_response_contains_no_token(
        self, _e2e_client: TestClient
    ) -> None:
        """La réponse de création ne révèle pas le jeton d'accès (PRD §11.1)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert token not in resp.text

    # ── Parcours 2 : liste ────────────────────────────────────────────────────

    def test_list_services_shows_created_service(self, _e2e_client: TestClient) -> None:
        """La prestation créée apparaît dans `GET /salons/{id}/services`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        resp_list = _e2e_client.get(
            _services_url(salon_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_list.status_code == 200
        ids = [s["id"] for s in resp_list.json()]
        assert service_id in ids

    def test_list_services_empty_salon_returns_empty_list(
        self, _e2e_client: TestClient
    ) -> None:
        """Un salon sans prestation retourne une liste vide (200 [])."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.get(
            _services_url(salon_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    # ── Parcours 3 : modification journalisée (cœur du critère §11.4) ─────────

    def test_update_service_returns_200(self, _e2e_client: TestClient) -> None:
        """PUT /salons/{id}/services/{sid} → 200 avec les nouvelles valeurs."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        resp_update = _e2e_client.put(
            _service_url(salon_id, service_id),
            json={"name": "Coupe femme", "price": "6000.00", "duration_minutes": 45},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_update.status_code == 200

    def test_get_after_update_reflects_new_values(
        self, _e2e_client: TestClient
    ) -> None:
        """GET après PUT reflète les nouvelles valeurs de la prestation."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        _e2e_client.put(
            _service_url(salon_id, service_id),
            json={"name": "Coupe femme", "price": "6000.00", "duration_minutes": 45},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp_get = _e2e_client.get(
            _service_url(salon_id, service_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_get.status_code == 200
        body = resp_get.json()
        assert body["name"] == "Coupe femme"
        assert body["duration_minutes"] == 45

    def test_update_service_records_service_updated_audit_entry(
        self, _e2e_client: TestClient
    ) -> None:
        """PUT enregistre une entrée `SERVICE_UPDATED` dans `audit_logs` (critère §11.4)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        _e2e_client.put(
            _service_url(salon_id, service_id),
            json={"name": "Coupe femme", "price": "6000.00", "duration_minutes": 45},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert _count_audit_entries(service_id, "SERVICE_UPDATED") == 1

    def test_update_audit_entry_contains_changed_fields(
        self, _e2e_client: TestClient
    ) -> None:
        """L'entrée `SERVICE_UPDATED` liste les champs modifiés dans `metadata.changed`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        _e2e_client.put(
            _service_url(salon_id, service_id),
            json={"name": "Coupe femme", "price": "6000.00", "duration_minutes": 45},
            headers={"Authorization": f"Bearer {token}"},
        )

        entries = _fetch_audit_entries(service_id)
        update_entry = next(e for e in entries if e["action"] == "SERVICE_UPDATED")
        changed = update_entry["metadata"]["changed"]
        assert "name" in changed
        assert "price" in changed
        assert "duration_minutes" in changed

    # ── Parcours 4 : désactivation (soft-delete §ADR-0019) ────────────────────

    def test_deactivate_service_returns_204(self, _e2e_client: TestClient) -> None:
        """DELETE /salons/{id}/services/{sid} → 204 (désactivation, pas suppression physique)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        resp_delete = _e2e_client.delete(
            _service_url(salon_id, service_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_delete.status_code == 204

    def test_deactivated_service_is_soft_deleted_in_db(
        self, _e2e_client: TestClient
    ) -> None:
        """La prestation désactivée passe `is_active=false` en base (la ligne est conservée)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]
        _e2e_client.delete(
            _service_url(salon_id, service_id),
            headers={"Authorization": f"Bearer {token}"},
        )

        engine = get_engine()
        with engine.connect() as conn:
            is_active = conn.execute(
                text("SELECT is_active FROM services WHERE id = :sid"),
                {"sid": service_id},
            ).scalar_one()
        assert is_active is False

    def test_deactivation_records_service_deactivated_audit_entry(
        self, _e2e_client: TestClient
    ) -> None:
        """DELETE enregistre une entrée `SERVICE_DEACTIVATED` dans `audit_logs`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]
        _e2e_client.delete(
            _service_url(salon_id, service_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert _count_audit_entries(service_id, "SERVICE_DEACTIVATED") == 1

    # ── Parcours 5 : traçabilité complète du cycle de vie ─────────────────────

    def test_full_lifecycle_creates_three_audit_entries(
        self, _e2e_client: TestClient
    ) -> None:
        """Création → modification → désactivation → 3 entrées d'audit au total."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        _e2e_client.put(
            _service_url(salon_id, service_id),
            json={"name": "Coupe femme", "price": "6000.00", "duration_minutes": 45},
            headers={"Authorization": f"Bearer {token}"},
        )
        _e2e_client.delete(
            _service_url(salon_id, service_id),
            headers={"Authorization": f"Bearer {token}"},
        )

        assert _count_audit_entries(service_id) == 3

    def test_full_lifecycle_audit_actions_in_chronological_order(
        self, _e2e_client: TestClient
    ) -> None:
        """Les actions d'audit sont SERVICE_CREATED → SERVICE_UPDATED → SERVICE_DEACTIVATED."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        _e2e_client.put(
            _service_url(salon_id, service_id),
            json={"name": "Coupe femme", "price": "6000.00", "duration_minutes": 45},
            headers={"Authorization": f"Bearer {token}"},
        )
        _e2e_client.delete(
            _service_url(salon_id, service_id),
            headers={"Authorization": f"Bearer {token}"},
        )

        actions = [e["action"] for e in _fetch_audit_entries(service_id)]
        assert actions == ["SERVICE_CREATED", "SERVICE_UPDATED", "SERVICE_DEACTIVATED"]

    def test_audit_actor_user_id_matches_manager(self, _e2e_client: TestClient) -> None:
        """L'`actor_user_id` des entrées d'audit correspond à l'UUID du gérant authentifié."""
        manager_id = _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        entries = _fetch_audit_entries(service_id)
        assert len(entries) == 1
        assert str(entries[0]["actor_user_id"]) == manager_id

    # ── Parcours 6 : invariants de non-fuite §11.3/§11.4 ─────────────────────

    def test_audit_metadata_contains_no_access_token(
        self, _e2e_client: TestClient
    ) -> None:
        """Les métadonnées d'audit ne contiennent jamais le jeton d'accès (secret)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        _e2e_client.put(
            _service_url(salon_id, service_id),
            json={"name": "Coupe femme", "price": "6000.00", "duration_minutes": 45},
            headers={"Authorization": f"Bearer {token}"},
        )

        for entry in _fetch_audit_entries(service_id):
            assert token not in str(entry["metadata"])

    def test_audit_metadata_contains_no_phone_pii(
        self, _e2e_client: TestClient
    ) -> None:
        """Les métadonnées d'audit ne contiennent pas le numéro de téléphone (PII §11.3)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp_create = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        service_id = resp_create.json()["id"]

        for entry in _fetch_audit_entries(service_id):
            assert _PHONE_A_LOCAL not in str(entry["metadata"])
            assert _E2E_PHONE_PREFIX not in str(entry["metadata"])

    # ── Parcours 7 : isolation inter-salons (§11.2) ───────────────────────────

    def test_cross_salon_create_returns_403(self, _e2e_client: TestClient) -> None:
        """Gérant A ne peut pas créer une prestation dans le salon du gérant B → 403."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.post(
            _services_url(salon_b_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    def test_cross_salon_403_message_is_generic(self, _e2e_client: TestClient) -> None:
        """Le 403 inter-salons est générique — il ne révèle pas l'existence du salon B."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.post(
            _services_url(salon_b_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.json()["detail"] == "Accès refusé."
        assert salon_b_id not in resp.text

    def test_cross_salon_list_returns_403(self, _e2e_client: TestClient) -> None:
        """Gérant A ne peut pas lister les prestations du salon du gérant B → 403."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.get(
            _services_url(salon_b_id),
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    # ── Parcours 8 : validation bout-en-bout (domaine → HTTP) ─────────────────

    def test_missing_price_returns_422(self, _e2e_client: TestClient) -> None:
        """Prix manquant → 422 (prix obligatoire, critère US-2.3)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_missing_duration_returns_422(self, _e2e_client: TestClient) -> None:
        """Durée manquante → 422 (durée obligatoire, critère US-2.3)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_negative_price_returns_422(self, _e2e_client: TestClient) -> None:
        """Prix négatif → 422 (validation domaine `validate_price` avant écriture)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "-1.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_zero_duration_returns_422(self, _e2e_client: TestClient) -> None:
        """Durée nulle → 422 (validation domaine : `duration_minutes > 0` requis)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_validation_failure_leaves_no_audit_entry(
        self, _e2e_client: TestClient
    ) -> None:
        """Validation échouée (prix négatif) → aucune entrée d'audit créée (atomicité §11.4)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "-1.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {token}"},
        )

        engine = get_engine()
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM audit_logs WHERE salon_id = :sid"),
                {"sid": salon_id},
            ).scalar_one()
        assert count == 0

    # ── Parcours 9 : deny-by-default (ADR-0015) ───────────────────────────────

    def test_no_token_on_create_returns_401(self, _e2e_client: TestClient) -> None:
        """POST sans jeton → 401 (deny-by-default, ADR-0015)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.post(
            _services_url(salon_id),
            json={"name": "Coupe homme", "price": "5000.00", "duration_minutes": 30},
        )
        assert resp.status_code == 401

    def test_no_token_on_list_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.get(_services_url(salon_id))
        assert resp.status_code == 401
