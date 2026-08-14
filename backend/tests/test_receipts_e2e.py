"""Tests e2e pour US-5.5 — reçu numérique de paiement (client, #38).

Groupe `TestReceiptsE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlReceiptRepository` — la jointure
    `payments ⋈ salons`, la résolution des lignes de prestation (`services` pour
    une prestation directe), le tri `created_at DESC, id DESC` et la pagination.
    Aucune suite unitaire/API (adossée à un dépôt en mémoire) ne couvre ce SQL :
    c'est le seul code qui satisfait réellement le critère d'acceptation #38
    *« le client consulte ses reçus, jamais ceux d'un tiers »*.

Scénarios (spec `specs/*.md`, cf. finding de revue automatisée sur la PR #118) :
    - paiement lié à une **prestation seule** → reçu avec **une** ligne
      (`services.name`/`price`) ;
    - `salon_name` résolu via la jointure `salons` (identité publique) ;
    - appartenance §11.2/§11.3 : le reçu d'un autre client est **indiscernable**
      d'un reçu inexistant (`404` neutre sur `GET /me/receipts/{id}`, absent de
      `GET /me/receipts`) ;
    - tri plus-récent-d'abord et pagination (`limit`/`offset`/`total`) ;
    - `401` sans jeton, `403` pour un rôle autre que `CLIENT` ;
    - aucune PII tierce (jeton, `recorded_by`, autre client) dans la réponse.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_receipts_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225076996xxxx).
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
_TEST_JWT_SECRET = "test-only-receipts-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des reçus.
_E2E_PHONE_PREFIX = "+225076996"
_PHONE_MANAGER_LOCAL = "0769960001"   # gérant — encaissement
_PHONE_CLIENT_A_LOCAL = "0769960002"   # client A — parcours principal
_PHONE_CLIENT_B_LOCAL = "0769960003"   # client B — appartenance/non-oracle
_PASSWORD = "receipts-e2e-strong-password-2024"

_SALON_NAME = "e2e-salon-receipts"

_ME_RECEIPTS_URL = "/me/receipts"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → cash_journal → payments → services → salon_members →
    salons → users.
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
                "DELETE FROM cash_journal WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM payments WHERE salon_id IN "
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

    - Injecte un JwtTokenService de test (secret local, jamais en production) sur app.state.
    - Supprime les données de test (plage +225076996) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e des reçus.")

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


def _register_manager(client: TestClient, *, phone: str = _PHONE_MANAGER_LOCAL) -> str:
    """Inscrit un compte gérant via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Reçus", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte client via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E Reçus", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str = _SALON_NAME) -> str:
    """Crée un salon via l'API et retourne son UUID."""
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(
    client: TestClient, token: str, salon_id: str, *, name: str, price: str
) -> str:
    """Crée une prestation active via l'API et retourne son UUID."""
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": name, "price": price, "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _record_payment(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    amount: str,
    service_id: str,
    client_id: str,
) -> str:
    """Enregistre un paiement `VALIDATED` rattaché au client et retourne son UUID."""
    resp = client.post(
        f"/salons/{salon_id}/payments",
        json={
            "amount": amount,
            "payment_method": "CASH",
            "service_id": service_id,
            "client_id": client_id,
        },
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Enregistrement paiement échoué : {resp.text}"
    return resp.json()["id"]


def _list_receipts(client: TestClient, token: str, **params: object) -> dict:
    """`GET /me/receipts` (page des reçus du client, US-5.5, #38)."""
    resp = client.get(
        _ME_RECEIPTS_URL, params=params, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, f"Liste des reçus échouée : {resp.text}"
    return resp.json()


def _get_receipt(client: TestClient, token: str, payment_id: str):
    """`GET /me/receipts/{payment_id}` — renvoie la réponse brute (statut variable)."""
    return client.get(
        f"{_ME_RECEIPTS_URL}/{payment_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestReceiptsE2E:
    """`GET /me/receipts[/{id}]` bout-en-bout : jointures/résolution de lignes SQL réelles."""

    # ── Parcours 1 : reçu d'une prestation seule (une ligne) ──────────────────

    def test_service_payment_receipt_has_one_line(self, _e2e_client: TestClient) -> None:
        """Un paiement lié à une prestation seule produit un reçu à **une** ligne."""
        _register_manager(_e2e_client)
        client_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe homme", price="1500.00"
        )
        _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1500.00",
            service_id=service_id,
            client_id=client_id,
        )

        page = _list_receipts(_e2e_client, client_token)
        assert len(page["items"]) == 1
        receipt = page["items"][0]
        assert len(receipt["lines"]) == 1
        assert receipt["lines"][0]["service_name"] == "Coupe homme"
        assert receipt["lines"][0]["amount"] == "1500.00"

    def test_receipt_salon_name_resolved_via_join(self, _e2e_client: TestClient) -> None:
        """`salon_name` reflète `salons.name` via la jointure (identité publique)."""
        _register_manager(_e2e_client)
        client_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe homme", price="1500.00"
        )
        _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1500.00",
            service_id=service_id,
            client_id=client_id,
        )

        page = _list_receipts(_e2e_client, client_token)
        assert page["items"][0]["salon_name"] == _SALON_NAME
        assert page["items"][0]["salon_id"] == salon_id

    # ── Parcours 3 : appartenance §11.2/§11.3 — non-oracle ────────────────────

    def test_other_client_receipt_absent_from_list(self, _e2e_client: TestClient) -> None:
        """Le reçu du client B n'apparaît jamais dans la liste du client A."""
        _register_manager(_e2e_client)
        client_a_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        client_b_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_B_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_a_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="1000.00"
        )
        _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1000.00",
            service_id=service_id,
            client_id=client_b_id,
        )
        assert client_a_id

        page = _list_receipts(_e2e_client, client_a_token)
        assert page["items"] == []
        assert page["total"] == 0

    def test_other_client_receipt_returns_404_not_403(
        self, _e2e_client: TestClient
    ) -> None:
        """Consulter le reçu d'un autre client → 404 neutre (indiscernable d'un id inexistant)."""
        _register_manager(_e2e_client)
        client_a_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        client_b_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_B_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_a_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="1000.00"
        )
        payment_b_id = _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1000.00",
            service_id=service_id,
            client_id=client_b_id,
        )
        assert client_a_id

        resp = _get_receipt(_e2e_client, client_a_token, payment_b_id)
        assert resp.status_code == 404

    def test_404_message_does_not_leak_other_client_existence(
        self, _e2e_client: TestClient
    ) -> None:
        """Le message 404 est identique pour un id inexistant et un reçu d'un tiers."""
        import uuid as uuid_module

        _register_manager(_e2e_client)
        client_a_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        client_b_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_B_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_a_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="1000.00"
        )
        payment_b_id = _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1000.00",
            service_id=service_id,
            client_id=client_b_id,
        )
        assert client_a_id

        resp_third_party = _get_receipt(_e2e_client, client_a_token, payment_b_id)
        resp_nonexistent = _get_receipt(
            _e2e_client, client_a_token, str(uuid_module.uuid4())
        )
        assert resp_third_party.json()["detail"] == resp_nonexistent.json()["detail"]

    def test_own_receipt_returns_200(self, _e2e_client: TestClient) -> None:
        """Consulter son propre reçu → 200 avec le détail complet."""
        _register_manager(_e2e_client)
        client_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="1000.00"
        )
        payment_id = _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1000.00",
            service_id=service_id,
            client_id=client_id,
        )

        resp = _get_receipt(_e2e_client, client_token, payment_id)
        assert resp.status_code == 200
        assert resp.json()["payment_id"] == payment_id

    # ── Parcours 4 : tri et pagination ────────────────────────────────────────

    def test_receipts_ordered_most_recent_first(self, _e2e_client: TestClient) -> None:
        """Deux reçus successifs apparaissent triés du plus récent au plus ancien."""
        _register_manager(_e2e_client)
        client_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        service_first_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="1000.00"
        )
        service_second_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Barbe", price="500.00"
        )
        payment_first_id = _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1000.00",
            service_id=service_first_id,
            client_id=client_id,
        )
        payment_second_id = _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="500.00",
            service_id=service_second_id,
            client_id=client_id,
        )

        page = _list_receipts(_e2e_client, client_token)
        ids = [item["payment_id"] for item in page["items"]]
        assert ids.index(payment_second_id) < ids.index(payment_first_id)

    def test_pagination_total_reflects_all_receipts(self, _e2e_client: TestClient) -> None:
        """`total` compte tous les reçus du client, indépendamment de `limit`."""
        _register_manager(_e2e_client)
        client_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        for name, price in (("A", "1000.00"), ("B", "2000.00"), ("C", "3000.00")):
            service_id = _create_service(
                _e2e_client, manager_token, salon_id, name=name, price=price
            )
            _record_payment(
                _e2e_client,
                manager_token,
                salon_id,
                amount=price,
                service_id=service_id,
                client_id=client_id,
            )

        page = _list_receipts(_e2e_client, client_token, limit=1, offset=0)
        assert page["total"] == 3
        assert len(page["items"]) == 1

    # ── Parcours 5 : deny-by-default et RBAC (ADR-0015) ───────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        resp = _e2e_client.get(_ME_RECEIPTS_URL)
        assert resp.status_code == 401

    def test_manager_role_returns_403(self, _e2e_client: TestClient) -> None:
        """Un gérant (pas CLIENT) n'a pas `PAYMENT_READ_OWN` sur `/me/receipts`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)

        resp = _e2e_client.get(
            _ME_RECEIPTS_URL, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403

    # ── Parcours 6 : absence de PII tierce (§11.3) ────────────────────────────

    def test_response_contains_no_third_party_pii(self, _e2e_client: TestClient) -> None:
        """La réponse ne révèle aucune PII tierce (jeton, auteur, autre client)."""
        _register_manager(_e2e_client)
        client_id = _register_client(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        client_token = _login(_e2e_client, phone=_PHONE_CLIENT_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="1000.00"
        )
        _record_payment(
            _e2e_client,
            manager_token,
            salon_id,
            amount="1000.00",
            service_id=service_id,
            client_id=client_id,
        )

        resp = _e2e_client.get(
            _ME_RECEIPTS_URL, headers={"Authorization": f"Bearer {client_token}"}
        )
        assert client_token not in resp.text
        for forbidden in ("recorded_by", "owner_id"):
            assert forbidden not in resp.text
