"""Tests API — `GET /me/receipts` et `GET /me/receipts/{payment_id}` (US-5.5, #38).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_receipt_repository` → `FakeReceiptRepository` ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- **200** liste : structure `items`/`total`/`limit`/`offset`, liste vide ≠ erreur ;
- **200** détail : schéma `ReceiptResponse`, montants en chaîne décimale, lignes ;
- **404 neutre** : reçu d'un tiers, reçu inexistant → même `404` (non-oracle §11.3) ;
- **401** sans jeton (liste et détail) ;
- **403** rôle MANAGER, HAIRDRESSER, ADMIN → `"Accès refusé."` générique ;
- **pagination** : `limit`/`offset` reflétés, `total` cohérent ;
- **`/me/receipts*` absents de `PUBLIC_ROUTE_PATHS`** (reçu financier, jamais public) ;
- **aucun verbe destructif** sur `/me/receipts*` (lecture seule) ;
- montants en **chaîne décimale** (jamais float) ;
- aucune PII tierce dans la réponse (jamais `recorded_by`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.receipts import get_receipt_repository
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.receipt import Receipt, ReceiptLine, format_receipt_number
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuthUserRepository,
    FakeReceiptRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_CLIENT_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_OTHER_CLIENT_ID = uuid.UUID("11111111-0000-0000-0000-000000000011")
_MANAGER_ID = uuid.UUID("22222222-0000-0000-0000-000000000022")
_HAIRDRESSER_ID = uuid.UUID("33333333-0000-0000-0000-000000000033")
_ADMIN_ID = uuid.UUID("44444444-0000-0000-0000-000000000044")

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_PAYMENT_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_APPT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")

_PAID_AT = datetime.datetime(2026, 7, 30, 10, 15, 0, tzinfo=datetime.timezone.utc)

_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
_ADMIN_TOKEN = make_access_token(_ADMIN_ID, Role.ADMIN.value)

_RECEIPTS_LIST_URL = "/me/receipts"


def _receipt_url(payment_id: uuid.UUID) -> str:
    return f"/me/receipts/{payment_id}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _creds(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(
        id=user_id,
        role=role,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


def _make_receipt(
    payment_id: uuid.UUID = _PAYMENT_ID,
    *,
    amount: decimal.Decimal = decimal.Decimal("5000.00"),
    appointment_id: uuid.UUID | None = None,
    lines: tuple[ReceiptLine, ...] = (),
    reference: str | None = None,
    receipt_number: int = 1,
    client_name: str | None = None,
    client_phone: str | None = None,
) -> Receipt:
    return Receipt(
        receipt_number=format_receipt_number(receipt_number),
        payment_id=payment_id,
        salon_id=_SALON_ID,
        salon_name="Salon Élégance",
        amount=amount,
        currency="XOF",
        payment_method="CASH",
        status="VALIDATED",
        reference=reference,
        paid_at=_PAID_AT,
        appointment_id=appointment_id,
        lines=lines,
        client_name=client_name,
        client_phone=client_phone,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture()
def receipt_repo() -> FakeReceiptRepository:
    return FakeReceiptRepository()


@pytest.fixture()
def client_http(receipt_repo: FakeReceiptRepository) -> Generator[TestClient, None, None]:
    """TestClient avec CLIENT authentifié."""
    creds = _creds(_CLIENT_ID, Role.CLIENT.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository()

    app.dependency_overrides[get_receipt_repository] = lambda: receipt_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_receipt_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# GET /me/receipts — 200 liste vide
# ---------------------------------------------------------------------------

class TestListReceiptsEmpty:
    def test_returns_200(self, client_http: TestClient) -> None:
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        assert r.status_code == 200

    def test_empty_items_field(self, client_http: TestClient) -> None:
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        assert r.json()["items"] == []

    def test_total_zero_on_empty(self, client_http: TestClient) -> None:
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        assert r.json()["total"] == 0

    def test_response_has_limit_field(self, client_http: TestClient) -> None:
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        assert "limit" in r.json()

    def test_response_has_offset_field(self, client_http: TestClient) -> None:
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        assert "offset" in r.json()


# ---------------------------------------------------------------------------
# GET /me/receipts — 200 avec reçus
# ---------------------------------------------------------------------------

class TestListReceiptsWithData:
    def test_returns_one_item(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        data = r.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_item_has_payment_id(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        item = r.json()["items"][0]
        assert item["payment_id"] == str(_PAYMENT_ID)

    def test_item_has_salon_name(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        item = r.json()["items"][0]
        assert item["salon_name"] == "Salon Élégance"

    def test_amount_is_decimal_string(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (
            _make_receipt(amount=decimal.Decimal("5000.00")),
        )
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        item = r.json()["items"][0]
        assert item["amount"] == "5000.00"

    def test_amount_is_string_not_float(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        item = r.json()["items"][0]
        assert isinstance(item["amount"], str)

    def test_item_has_lines_field(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        lines = (ReceiptLine(service_name="Coupe", amount=decimal.Decimal("3000.00")),)
        receipt_repo._by_client[_CLIENT_ID] = (
            _make_receipt(appointment_id=_APPT_ID, lines=lines),
        )
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        item = r.json()["items"][0]
        assert "lines" in item
        assert len(item["lines"]) == 1
        assert item["lines"][0]["service_name"] == "Coupe"

    def test_no_recorded_by_in_response(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        """Le reçu ne doit jamais exposer `recorded_by` (PII de gestion, §11.3)."""
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
        item = r.json()["items"][0]
        assert "recorded_by" not in item


# ---------------------------------------------------------------------------
# GET /me/receipts/{payment_id} — 200
# ---------------------------------------------------------------------------

class TestGetReceiptOk:
    def test_returns_200(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(
            _receipt_url(_PAYMENT_ID),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert r.status_code == 200

    def test_returns_correct_payment_id(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(
            _receipt_url(_PAYMENT_ID),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert r.json()["payment_id"] == str(_PAYMENT_ID)

    def test_amount_is_decimal_string_in_detail(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (
            _make_receipt(amount=decimal.Decimal("7500.00")),
        )
        r = client_http.get(
            _receipt_url(_PAYMENT_ID),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert r.json()["amount"] == "7500.00"

    def test_multiline_receipt_has_correct_lines(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        lines = (
            ReceiptLine(service_name="Coupe homme", amount=decimal.Decimal("3000.00")),
            ReceiptLine(service_name="Barbe", amount=decimal.Decimal("2000.00")),
        )
        receipt_repo._by_client[_CLIENT_ID] = (
            _make_receipt(appointment_id=_APPT_ID, lines=lines),
        )
        r = client_http.get(
            _receipt_url(_PAYMENT_ID),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        data = r.json()
        assert len(data["lines"]) == 2
        names = {line["service_name"] for line in data["lines"]}
        assert "Coupe homme" in names
        assert "Barbe" in names

    def test_receipt_number_present_and_non_empty(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = (_make_receipt(),)
        r = client_http.get(
            _receipt_url(_PAYMENT_ID),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert r.json()["receipt_number"] != ""


# ---------------------------------------------------------------------------
# GET /me/receipts/{payment_id} — 404 neutre (non-oracle §11.3)
# ---------------------------------------------------------------------------

class TestGetReceiptNotFound:
    def test_nonexistent_payment_id_returns_404(
        self, client_http: TestClient
    ) -> None:
        nonexistent = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        r = client_http.get(
            _receipt_url(nonexistent),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert r.status_code == 404

    def test_other_client_payment_returns_404(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        """Reçu d'un autre client → 404 indiscernable (non-oracle §11.3)."""
        other_receipt = _make_receipt(_PAYMENT_ID)
        receipt_repo._by_client[_OTHER_CLIENT_ID] = (other_receipt,)
        r = client_http.get(
            _receipt_url(_PAYMENT_ID),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert r.status_code == 404

    def test_404_message_is_neutral(
        self, client_http: TestClient
    ) -> None:
        """Message 404 neutre — ne révèle pas si le paiement existe (non-oracle §11.3)."""
        nonexistent = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
        r = client_http.get(
            _receipt_url(nonexistent),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        detail = r.json().get("detail", "")
        assert detail != ""
        assert "autre" not in detail.lower()
        assert "client_id" not in detail.lower()


# ---------------------------------------------------------------------------
# 401 — sans jeton
# ---------------------------------------------------------------------------

class TestReceiptsUnauthorized:
    def test_list_without_token_returns_401(self, client_http: TestClient) -> None:
        r = client_http.get(_RECEIPTS_LIST_URL)
        assert r.status_code == 401

    def test_list_401_includes_www_authenticate_header(
        self, client_http: TestClient
    ) -> None:
        r = client_http.get(_RECEIPTS_LIST_URL)
        assert "WWW-Authenticate" in r.headers

    def test_detail_without_token_returns_401(self, client_http: TestClient) -> None:
        r = client_http.get(_receipt_url(_PAYMENT_ID))
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 — rôle insuffisant
# ---------------------------------------------------------------------------

class TestReceiptsForbidden:
    def _client_with_role(
        self,
        receipt_repo: FakeReceiptRepository,
        user_id: uuid.UUID,
        role: str,
    ) -> TestClient:
        creds = _creds(user_id, role)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(user_id): creds})
        scope_repo = FakeSalonScopeRepository()
        app.dependency_overrides[get_receipt_repository] = lambda: receipt_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        return TestClient(app, raise_server_exceptions=False)

    def test_manager_gets_403_on_list(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        c = self._client_with_role(receipt_repo, _MANAGER_ID, Role.MANAGER.value)
        try:
            r = c.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_receipt_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_hairdresser_gets_403_on_list(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        c = self._client_with_role(receipt_repo, _HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        try:
            r = c.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_receipt_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_admin_gets_403_on_list(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        c = self._client_with_role(receipt_repo, _ADMIN_ID, Role.ADMIN.value)
        try:
            r = c.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_receipt_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_manager_gets_403_on_detail(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        c = self._client_with_role(receipt_repo, _MANAGER_ID, Role.MANAGER.value)
        try:
            r = c.get(
                _receipt_url(_PAYMENT_ID),
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_receipt_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_403_message_is_generic(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        c = self._client_with_role(receipt_repo, _MANAGER_ID, Role.MANAGER.value)
        try:
            r = c.get(_RECEIPTS_LIST_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
            assert r.json()["detail"] == "Accès refusé."
        finally:
            app.dependency_overrides.pop(get_receipt_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestListReceiptsPagination:
    def _repo_with_n(self, n: int) -> FakeReceiptRepository:
        receipts = tuple(
            _make_receipt(
                uuid.UUID(f"0000{i:04d}-0000-0000-0000-000000000001")
            )
            for i in range(n)
        )
        return FakeReceiptRepository(receipts_by_client={_CLIENT_ID: receipts})

    def test_limit_param_reflected(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = tuple(
            _make_receipt(uuid.UUID(f"0000{i:04d}-0000-0000-0000-000000000001"))
            for i in range(5)
        )
        r = client_http.get(
            _RECEIPTS_LIST_URL,
            params={"limit": 2},
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        data = r.json()
        assert data["limit"] == 2
        assert len(data["items"]) == 2

    def test_offset_param_reflected(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        r = client_http.get(
            _RECEIPTS_LIST_URL,
            params={"offset": 5},
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert r.json()["offset"] == 5

    def test_total_reflects_all_regardless_of_limit(
        self, client_http: TestClient, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_client[_CLIENT_ID] = tuple(
            _make_receipt(uuid.UUID(f"0000{i:04d}-0000-0000-0000-000000000001"))
            for i in range(7)
        )
        r = client_http.get(
            _RECEIPTS_LIST_URL,
            params={"limit": 3},
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 7
        assert len(data["items"]) == 3


# ---------------------------------------------------------------------------
# Sécurité — PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------

class TestReceiptsNotPublic:
    def test_receipts_list_path_not_in_public_routes(self) -> None:
        """GET /me/receipts : reçu financier, jamais public (§11.2)."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "/me/receipts" not in path, (
                f"Route reçu trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )

    def test_no_destructive_methods_on_receipts_routes(self) -> None:
        """Aucun verbe destructif sur /me/receipts* (lecture seule)."""
        from fastapi.routing import APIRoute

        destructive = {"DELETE", "PUT", "PATCH", "POST"}
        bad: list[str] = []
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            if "/me/receipts" not in route.path:
                continue
            for method in route.methods or set():
                if method in destructive:
                    bad.append(f"{method} {route.path}")
        assert bad == [], f"Verbes destructifs sur /me/receipts : {bad}"


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/payments/{payment_id}/receipt — reçu gérant (ADR-0040)
# ---------------------------------------------------------------------------

_MANAGER_RECEIPT_URL = f"/salons/{_SALON_ID}/payments/{_PAYMENT_ID}/receipt"


def _make_manager_receipt(
    *,
    client_name: str | None = "Awa Koné",
    client_phone: str | None = "+2250700000001",
) -> Receipt:
    return _make_receipt(client_name=client_name, client_phone=client_phone)


class TestManagerReceiptEndpoint:
    """`GET /salons/{id}/payments/{id}/receipt` : gérant, `CASH_JOURNAL_READ` (ADR-0040)."""

    def _client_with_scope(
        self, receipt_repo: FakeReceiptRepository
    ) -> TestClient:
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(_MANAGER_ID): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})
        app.dependency_overrides[get_receipt_repository] = lambda: receipt_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        return TestClient(app, raise_server_exceptions=False)

    def _teardown(self) -> None:
        app.dependency_overrides.pop(get_receipt_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)

    def test_returns_200_with_client_identity(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_salon[_SALON_ID] = (_make_manager_receipt(),)
        c = self._client_with_scope(receipt_repo)
        try:
            r = c.get(
                _MANAGER_RECEIPT_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
            )
            assert r.status_code == 200
            body = r.json()
            assert body["client_name"] == "Awa Koné"
            assert body["client_phone"] == "+2250700000001"
        finally:
            self._teardown()

    def test_walk_in_payment_has_null_client(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        receipt_repo._by_salon[_SALON_ID] = (
            _make_manager_receipt(client_name=None, client_phone=None),
        )
        c = self._client_with_scope(receipt_repo)
        try:
            r = c.get(
                _MANAGER_RECEIPT_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
            )
            body = r.json()
            assert body["client_name"] is None
            assert body["client_phone"] is None
        finally:
            self._teardown()

    def test_amount_is_decimal_string(self, receipt_repo: FakeReceiptRepository) -> None:
        receipt_repo._by_salon[_SALON_ID] = (
            _make_manager_receipt(),
        )
        c = self._client_with_scope(receipt_repo)
        try:
            r = c.get(
                _MANAGER_RECEIPT_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
            )
            assert isinstance(r.json()["amount"], str)
        finally:
            self._teardown()

    def test_unknown_payment_returns_404(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        """Reçu jamais seedé (`_by_salon` vide) → 404 neutre, pas de trace serveur."""
        c = self._client_with_scope(receipt_repo)
        try:
            r = c.get(
                _MANAGER_RECEIPT_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
            )
            assert r.status_code == 404
        finally:
            self._teardown()

    def test_manager_without_scope_gets_403(
        self, receipt_repo: FakeReceiptRepository
    ) -> None:
        """Gérant authentifié mais **sans** portée sur ce salon → 403 (avant tout accès au dépôt)."""
        receipt_repo._by_salon[_SALON_ID] = (_make_manager_receipt(),)
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(_MANAGER_ID): creds})
        scope_repo = FakeSalonScopeRepository()  # aucune portée accordée
        app.dependency_overrides[get_receipt_repository] = lambda: receipt_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            r = TestClient(app, raise_server_exceptions=False).get(
                _MANAGER_RECEIPT_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
            )
            assert r.status_code == 403
        finally:
            self._teardown()

    def test_client_role_gets_403(self, receipt_repo: FakeReceiptRepository) -> None:
        """Un CLIENT (même détenteur de `PAYMENT_READ_OWN`) n'a pas `CASH_JOURNAL_READ`."""
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(_CLIENT_ID): creds})
        scope_repo = FakeSalonScopeRepository()
        app.dependency_overrides[get_receipt_repository] = lambda: receipt_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            r = TestClient(app, raise_server_exceptions=False).get(
                _MANAGER_RECEIPT_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
            )
            assert r.status_code == 403
        finally:
            self._teardown()

    def test_no_token_returns_401(self) -> None:
        r = TestClient(app).get(_MANAGER_RECEIPT_URL)
        assert r.status_code == 401
