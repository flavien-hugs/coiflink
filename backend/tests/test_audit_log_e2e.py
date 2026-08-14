"""Tests e2e pour le journal d'audit (page gérante « Journal d'audit », PostgreSQL requis).

Groupe `TestAuditLogE2E` : exerce le **chemin SQL réel** de `SqlAuditLog` — la
jointure `audit_logs ⋈ users` (résolution `actor_name`), le filtre `category`
(traduit en `WHERE action IN (...)` via `ACTIONS_BY_CATEGORY`), le filtre de
plage de dates, le tri `created_at DESC, id DESC`, la pagination, et l'isolation
§11.2 (jamais une entrée d'un autre salon). Aucune suite unitaire/API (adossée à
un dépôt en mémoire) ne couvre ce SQL.

Scénario : un gérant crée puis modifie une prestation (déclenche réellement
`SERVICE_CREATED`/`SERVICE_UPDATED` via le chemin de production, #17) ; le
journal du salon liste ces deux entrées, avec le nom du gérant résolu ; le
filtre `category=prestations` les retrouve ; un autre salon n'en voit aucune.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_audit_log_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225076997xxxx).
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.outbound.persistence.session import get_engine
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.main import app as main_app

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_TEST_JWT_SECRET = "test-only-audit-log-e2e-jwt-secret-not-for-production"

_E2E_PHONE_PREFIX = "+225076997"
_PHONE_MANAGER_A_LOCAL = "0769970001"
_PHONE_MANAGER_B_LOCAL = "0769970002"
_PASSWORD = "audit-log-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-audit-a"
_SALON_NAME_B = "e2e-salon-audit-b"


def _wipe_test_data() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        from sqlalchemy import text

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


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e du journal d'audit.")

    orig_token_service = getattr(main_app.state, "token_service", None)
    main_app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )

    _wipe_test_data()
    try:
        yield TestClient(main_app)
    finally:
        _wipe_test_data()
        main_app.state.token_service = orig_token_service


def _register_manager(client: TestClient, *, phone: str, full_name: str) -> str:
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": full_name, "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str) -> str:
    resp = client.post(
        "/salons", json={"name": name}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(client: TestClient, token: str, salon_id: str) -> str:
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": "Coupe E2E Audit", "price": "3000.00", "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _update_service(client: TestClient, token: str, salon_id: str, service_id: str) -> None:
    resp = client.put(
        f"/salons/{salon_id}/services/{service_id}",
        json={"name": "Coupe E2E Audit", "price": "3500.00", "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Modification prestation échouée : {resp.text}"


def _list_audit_logs(client: TestClient, token: str, salon_id: str, **params: object) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/audit-logs",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Lecture du journal d'audit échouée : {resp.text}"
    return resp.json()


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestAuditLogE2E:
    """`GET /salons/{id}/audit-logs` bout-en-bout : jointure/filtres/isolation SQL réels."""

    def test_service_created_and_updated_appear_with_resolved_actor_name(
        self, _e2e_client: TestClient
    ) -> None:
        _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit E2E"
        )
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        service_id = _create_service(_e2e_client, token, salon_id)
        _update_service(_e2e_client, token, salon_id, service_id)

        page = _list_audit_logs(_e2e_client, token, salon_id)
        assert page["total"] == 2
        actions = {item["action"] for item in page["items"]}
        assert actions == {"SERVICE_CREATED", "SERVICE_UPDATED"}
        for item in page["items"]:
            assert item["category"] == "prestations"
            assert item["actor_name"] == "Gérante Audit E2E"
            assert item["entity_id"] == service_id
            assert "metadata" not in item

    def test_most_recent_entry_listed_first(self, _e2e_client: TestClient) -> None:
        _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit E2E"
        )
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        service_id = _create_service(_e2e_client, token, salon_id)
        _update_service(_e2e_client, token, salon_id, service_id)

        page = _list_audit_logs(_e2e_client, token, salon_id)
        assert page["items"][0]["action"] == "SERVICE_UPDATED"
        assert page["items"][1]["action"] == "SERVICE_CREATED"

    def test_category_filter_matches_prestations(self, _e2e_client: TestClient) -> None:
        _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit E2E"
        )
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        _create_service(_e2e_client, token, salon_id)

        page = _list_audit_logs(_e2e_client, token, salon_id, category="prestations")
        assert page["total"] == 1

    def test_category_filter_excludes_non_matching_category(
        self, _e2e_client: TestClient
    ) -> None:
        _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit E2E"
        )
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        _create_service(_e2e_client, token, salon_id)

        page = _list_audit_logs(_e2e_client, token, salon_id, category="employes")
        assert page["total"] == 0
        assert page["items"] == []

    def test_date_range_excludes_entries_outside_it(self, _e2e_client: TestClient) -> None:
        _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit E2E"
        )
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        _create_service(_e2e_client, token, salon_id)

        future = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        page = _list_audit_logs(
            _e2e_client, token, salon_id, date_from=future, date_to=future
        )
        assert page["total"] == 0

    def test_other_salon_entries_never_leak(self, _e2e_client: TestClient) -> None:
        _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit A"
        )
        _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_B_LOCAL, full_name="Gérante Audit B"
        )
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        _create_service(_e2e_client, token_a, salon_a)
        _create_service(_e2e_client, token_b, salon_b)

        page_a = _list_audit_logs(_e2e_client, token_a, salon_a)
        assert page_a["total"] == 1

        # Le gérant A n'a pas la portée du salon B → 403, jamais une fuite de données.
        resp = _e2e_client.get(
            f"/salons/{salon_b}/audit-logs", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert resp.status_code == 403

    def test_legacy_action_from_a_removed_feature_reads_gracefully(
        self, _e2e_client: TestClient
    ) -> None:
        """`audit_logs` est un journal append-only (§11.4) : une ligne dont
        l'action référence une fonctionnalité depuis supprimée (ex. les anciens
        RDV) doit rester lisible pour toujours, jamais faire échouer la lecture
        du salon — régression réelle observée en environnement de dev sur un
        salon avec de l'historique `APPOINTMENT_HAIRDRESSER_ASSIGNED`."""
        owner_id = _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit E2E"
        )
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)

        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(id, action, actor_user_id, salon_id, entity_type, entity_id, created_at) "
                    "VALUES (gen_random_uuid(), 'APPOINTMENT_HAIRDRESSER_ASSIGNED', "
                    ":actor_user_id, :salon_id, 'appointment', gen_random_uuid(), now())"
                ),
                {"actor_user_id": owner_id, "salon_id": salon_id},
            )
            conn.commit()

        page = _list_audit_logs(_e2e_client, token, salon_id)
        assert page["total"] == 1
        entry = page["items"][0]
        assert entry["action"] == "APPOINTMENT_HAIRDRESSER_ASSIGNED"
        assert entry["category"] == "salon"

    def test_hairdresser_gets_403(self, _e2e_client: TestClient) -> None:
        """`AUDIT_LOG_READ` est réservée au MANAGER — pas au coiffeur."""
        owner_id = _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_A_LOCAL, full_name="Gérante Audit E2E"
        )
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        assert owner_id

        emp_resp = _e2e_client.post(
            f"/salons/{salon_id}/employees",
            json={
                "full_name": "Coiffeuse Audit E2E",
                "phone": "+2250769970099",
                "password": "employee-audit-e2e-2024",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert emp_resp.status_code == 201, f"Création employée échouée : {emp_resp.text}"

        hairdresser_login = _e2e_client.post(
            "/auth/login",
            json={"identifier": "+2250769970099", "password": "employee-audit-e2e-2024"},
        )
        assert hairdresser_login.status_code == 200
        hairdresser_token = hairdresser_login.json()["access_token"]

        resp = _e2e_client.get(
            f"/salons/{salon_id}/audit-logs",
            headers={"Authorization": f"Bearer {hairdresser_token}"},
        )
        assert resp.status_code == 403
