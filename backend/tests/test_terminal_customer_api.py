"""Tests API — router `/salons/{id}/terminal/customers[...]` (adapter entrant, US-8.2, #156).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_customer_repository` → `FakeCustomerRepository` ;
- `get_audit_log`           → `FakeAuditLog` ;
- `get_terminal_lookup_rate_limiter` → `FakeLoginRateLimiter` (surchargeable) ;
- `get_user_repository`     → `FakeAuthUserRepository` (credentials du device) ;
- `get_access_policy`       → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- **POST /lookup 200** : corps **exactement** `{customer_id, first_name}` — assertions
  d'*absence* de `full_name`, `phone`, `gender`, `notes`, `user_id`, `total_visits` ;
  normalisation du téléphone (`07 00 00 00 00` → fiche retrouvée) ;
- **POST /lookup 404** neutre (sans écho du numéro soumis) ;
- **POST /lookup 422** téléphone invalide ;
- **POST /lookup 429** + `Retry-After` quand le limiteur est verrouillé ;
- **POST (create) 201** : corps minimal, champs privilégiés du corps ignorés ;
- **POST (create) 409** doublon de téléphone ;
- **POST (create) 422** champ manquant ou invalide ;
- **RBAC négatif** :
  - `401` sans credential sur les deux routes ;
  - `403` pour un JWT `CLIENT`, `MANAGER`, `HAIRDRESSER`, `ADMIN` sur les routes
    terminal ;
  - credential `TERMINAL` refusé (`403`) sur `POST /salons/{id}/customers`
    (`CUSTOMER_MANAGE`, MANAGER-seul) — moindre privilège ;
  - device du salon A → `403` sur le salon B (portée cross-salon impossible) ;
- **Invariants sécurité** : aucune route terminal dans `PUBLIC_ROUTE_PATHS` ;
  `unprotected_routes(app)` reste vide après montage du router.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.customers import get_audit_log, get_customer_repository
from coiflink_api.adapters.inbound.terminal_customers import (
    get_terminal_lookup_rate_limiter,
)
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
    unprotected_routes,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    TEST_JWT_SECRET,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeCustomerRepository,
    FakeLoginRateLimiter,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_DEVICE_ID = uuid.UUID("d0000000-0000-0000-0000-000000000001")
_SALON_ID = uuid.UUID("aaaaaa00-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbb00-0000-0000-0000-000000000002")

_MANAGER_ID = uuid.UUID("ee000000-0000-0000-0000-000000000001")
_CLIENT_ID = uuid.UUID("ee000000-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("ee000000-0000-0000-0000-000000000003")
_ADMIN_ID = uuid.UUID("ee000000-0000-0000-0000-000000000004")

_TERMINAL_TOKEN = make_access_token(_DEVICE_ID, Role.TERMINAL.value)
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
_ADMIN_TOKEN = make_access_token(_ADMIN_ID, Role.ADMIN.value)

_LOOKUP_URL = f"/salons/{_SALON_ID}/terminal/customers/lookup"
_CREATE_URL = f"/salons/{_SALON_ID}/terminal/customers"

# URL du salon B pour les tests de portée cross-salon.
_LOOKUP_URL_B = f"/salons/{_OTHER_SALON_ID}/terminal/customers/lookup"
_CREATE_URL_B = f"/salons/{_OTHER_SALON_ID}/terminal/customers"

# URL de la route gérant (CUSTOMER_MANAGE) — RBAC négatif.
_MANAGER_CUSTOMERS_URL = f"/salons/{_SALON_ID}/customers"

_CANONICAL_PHONE = "+2250700000000"


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


def _seed_customer(
    repo: FakeCustomerRepository,
    *,
    salon_id: uuid.UUID = _SALON_ID,
    full_name: str = "Awa Koné",
    phone: str = _CANONICAL_PHONE,
) -> object:
    from coiflink_api.domain.customer import CustomerToCreate

    return repo.create(
        CustomerToCreate(salon_id=salon_id, full_name=full_name, phone=phone)
    )


# ---------------------------------------------------------------------------
# Fixtures de base
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    """JWT réel signé avec le secret de test (décodage réel dans les gardes)."""
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture()
def customer_repo() -> FakeCustomerRepository:
    return FakeCustomerRepository()


@pytest.fixture()
def audit_log() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture()
def rate_limiter() -> FakeLoginRateLimiter:
    return FakeLoginRateLimiter()


# ---------------------------------------------------------------------------
# Client terminal (scope = salon A, device provisionné)
# ---------------------------------------------------------------------------


@pytest.fixture()
def terminal_client(
    customer_repo: FakeCustomerRepository,
    audit_log: FakeAuditLog,
    rate_limiter: FakeLoginRateLimiter,
) -> Generator[TestClient, None, None]:
    """TestClient avec credential `TERMINAL` dont la portée couvre `_SALON_ID`."""
    device_creds = _creds(_DEVICE_ID, Role.TERMINAL.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(_DEVICE_ID): device_creds})
    scope_repo = FakeSalonScopeRepository(scopes={_DEVICE_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_customer_repository] = lambda: customer_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_terminal_lookup_rate_limiter] = lambda: rate_limiter
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_customer_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_terminal_lookup_rate_limiter, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# Client générique pour tests RBAC (pas de fakes de cas d'usage injectés).
@pytest.fixture()
def base_client() -> Generator[TestClient, None, None]:
    """TestClient minimal pour les tests RBAC (401/403)."""
    device_creds = _creds(_DEVICE_ID, Role.TERMINAL.value)
    manager_creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    client_creds = _creds(_CLIENT_ID, Role.CLIENT.value)
    hairdresser_creds = _creds(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
    admin_creds = _creds(_ADMIN_ID, Role.ADMIN.value)
    user_repo = FakeAuthUserRepository(
        credentials_by_id={
            str(_DEVICE_ID): device_creds,
            str(_MANAGER_ID): manager_creds,
            str(_CLIENT_ID): client_creds,
            str(_HAIRDRESSER_ID): hairdresser_creds,
            str(_ADMIN_ID): admin_creds,
        }
    )
    scope_repo = FakeSalonScopeRepository(
        scopes={
            _DEVICE_ID: frozenset({_SALON_ID}),
            _MANAGER_ID: frozenset({_SALON_ID}),
            _CLIENT_ID: frozenset({_SALON_ID}),
            _HAIRDRESSER_ID: frozenset({_SALON_ID}),
        }
    )
    customer_repo = FakeCustomerRepository()
    audit_log = FakeAuditLog()
    rate_limiter = FakeLoginRateLimiter()

    app.dependency_overrides[get_customer_repository] = lambda: customer_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_terminal_lookup_rate_limiter] = lambda: rate_limiter
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_customer_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_terminal_lookup_rate_limiter, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Invariants de sécurité (deny-by-default)
# ---------------------------------------------------------------------------


class TestSecurityInvariants:
    def test_no_terminal_customers_path_in_public_route_paths(self) -> None:
        """Aucune route terminal ne doit figurer dans `PUBLIC_ROUTE_PATHS`."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "terminal/customers" not in path, (
                f"Route terminal trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )

    def test_unprotected_routes_still_empty_after_terminal_router(self) -> None:
        """Le montage du router terminal ne crée pas de route non protégée."""
        assert unprotected_routes(app) == []


# ---------------------------------------------------------------------------
# POST /lookup — 200 corps et projection minimale
# ---------------------------------------------------------------------------


class TestLookupFound200:
    def test_returns_200(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 200

    def test_body_contains_customer_id(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "customer_id" in r.json()

    def test_body_contains_first_name(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.json()["first_name"] == "Awa"

    def test_body_does_not_contain_full_name(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """Projection minimale : le nom complet ne doit pas fuiter (§11.3)."""
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        body = r.json()
        assert "full_name" not in body

    def test_body_does_not_contain_phone(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """Le numéro soumis ne doit pas réapparaître dans la réponse (§11.3)."""
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "phone" not in r.json()

    def test_body_does_not_contain_gender(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "gender" not in r.json()

    def test_body_does_not_contain_notes(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "notes" not in r.json()

    def test_body_does_not_contain_user_id(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "user_id" not in r.json()

    def test_body_does_not_contain_total_visits(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "total_visits" not in r.json()

    def test_spaced_phone_format_finds_customer(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """Format de saisie tactile `07 00 00 00 00` → fiche retrouvée (normalisation E.164)."""
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "07 00 00 00 00"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 200
        assert r.json()["first_name"] == "Awa"

    def test_extra_fields_in_body_ignored(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """Champs supplémentaires (`extra="ignore"`) ne causent pas d'erreur."""
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000", "salon_id": str(_OTHER_SALON_ID), "user_id": "xxx"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /lookup — 404 neutre
# ---------------------------------------------------------------------------


class TestLookupNotFound404:
    def test_returns_404_when_customer_absent(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 404

    def test_404_detail_does_not_echo_phone(self, terminal_client: TestClient) -> None:
        """Le message d'erreur ne répète jamais le numéro soumis (§11.3)."""
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        detail = r.json().get("detail", "")
        assert "0700000000" not in detail
        assert "+2250700000000" not in detail

    def test_404_neutral_detail(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.json()["detail"] == "Aucune fiche pour ce numéro dans ce salon."


# ---------------------------------------------------------------------------
# POST /lookup — 422 téléphone invalide
# ---------------------------------------------------------------------------


class TestLookupInvalidPhone422:
    def test_invalid_phone_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _LOOKUP_URL,
            json={"phone": "not-a-phone"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422

    def test_missing_phone_field_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _LOOKUP_URL,
            json={},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /lookup — 429 limiteur verrouillé + Retry-After
# ---------------------------------------------------------------------------


class TestLookupRateLimited429:
    @pytest.fixture()
    def locked_client(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> Generator[TestClient, None, None]:
        """Client avec un limiteur verrouillé et un `retry_after` configuré."""
        locked_limiter = FakeLoginRateLimiter(locked=True, retry_after=600)
        device_creds = _creds(_DEVICE_ID, Role.TERMINAL.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(_DEVICE_ID): device_creds})
        scope_repo = FakeSalonScopeRepository(scopes={_DEVICE_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_terminal_lookup_rate_limiter] = lambda: locked_limiter
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_terminal_lookup_rate_limiter, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_locked_returns_429(self, locked_client: TestClient) -> None:
        r = locked_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 429

    def test_locked_response_has_retry_after_header(self, locked_client: TestClient) -> None:
        r = locked_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "Retry-After" in r.headers

    def test_retry_after_value_matches_limiter(self, locked_client: TestClient) -> None:
        r = locked_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.headers["Retry-After"] == "600"

    def test_rate_limited_detail_is_generic(self, locked_client: TestClient) -> None:
        """Le message 429 est générique, sans information opérationnelle."""
        r = locked_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.json()["detail"] == "Trop de tentatives. Réessayez plus tard."


# ---------------------------------------------------------------------------
# POST /terminal/customers — 201 création walk-in
# ---------------------------------------------------------------------------


class TestCreateWalkIn201:
    _VALID_BODY = {"first_name": "Awa", "last_name": "Koné", "phone": "0700000000"}

    def test_returns_201(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 201

    def test_body_contains_customer_id(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "customer_id" in r.json()

    def test_body_contains_first_name(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.json()["first_name"] == "Awa"

    def test_body_does_not_contain_full_name(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "full_name" not in r.json()

    def test_body_does_not_contain_phone(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "phone" not in r.json()

    def test_body_does_not_contain_user_id(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "user_id" not in r.json()

    def test_body_does_not_contain_gender(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "gender" not in r.json()

    def test_body_does_not_contain_notes(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert "notes" not in r.json()

    def test_privileged_fields_in_body_ignored(self, terminal_client: TestClient) -> None:
        """`extra="ignore"` : `salon_id`, `user_id`, `gender`, `notes` ignorés."""
        r = terminal_client.post(
            _CREATE_URL,
            json={
                **self._VALID_BODY,
                "salon_id": str(_OTHER_SALON_ID),
                "user_id": str(uuid.uuid4()),
                "gender": "FEMALE",
                "notes": "Note interne.",
                "total_visits": 999,
            },
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 201

    def test_audit_emitted_on_create(
        self, terminal_client: TestClient, audit_log: FakeAuditLog
    ) -> None:
        terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert len(audit_log.recorded) == 1

    def test_audit_metadata_empty(
        self, terminal_client: TestClient, audit_log: FakeAuditLog
    ) -> None:
        terminal_client.post(
            _CREATE_URL,
            json=self._VALID_BODY,
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert audit_log.recorded[0].metadata == {}


# ---------------------------------------------------------------------------
# POST /terminal/customers — 409 doublon
# ---------------------------------------------------------------------------


class TestCreateWalkIn409:
    def test_duplicate_returns_409(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _CREATE_URL,
            json={"first_name": "Autre", "last_name": "Nom", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 409

    def test_duplicate_detail_is_neutral(
        self, terminal_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        _seed_customer(customer_repo)
        r = terminal_client.post(
            _CREATE_URL,
            json={"first_name": "Autre", "last_name": "Nom", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        detail = r.json()["detail"]
        # Le message neutre attendu (§11.3) ne rappelle pas le numéro.
        assert "0700000000" not in detail
        assert "+2250700000000" not in detail


# ---------------------------------------------------------------------------
# POST /terminal/customers — 422 validation
# ---------------------------------------------------------------------------


class TestCreateWalkIn422:
    def test_missing_first_name_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json={"last_name": "Koné", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422

    def test_missing_last_name_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json={"first_name": "Awa", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422

    def test_missing_phone_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json={"first_name": "Awa", "last_name": "Koné"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422

    def test_invalid_phone_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json={"first_name": "Awa", "last_name": "Koné", "phone": "not-a-phone"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422

    def test_empty_first_name_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json={"first_name": "", "last_name": "Koné", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422

    def test_whitespace_first_name_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json={"first_name": "   ", "last_name": "Koné", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422

    def test_empty_body_returns_422(self, terminal_client: TestClient) -> None:
        r = terminal_client.post(
            _CREATE_URL,
            json={},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# RBAC négatif — 401 sans credential
# ---------------------------------------------------------------------------


class TestRbacNoCredential:
    def test_lookup_no_token_returns_401(self, base_client: TestClient) -> None:
        r = base_client.post(_LOOKUP_URL, json={"phone": "0700000000"})
        assert r.status_code == 401

    def test_create_no_token_returns_401(self, base_client: TestClient) -> None:
        r = base_client.post(
            _CREATE_URL,
            json={"first_name": "Awa", "last_name": "Koné", "phone": "0700000000"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# RBAC négatif — 403 rôle non-TERMINAL sur routes terminal
# ---------------------------------------------------------------------------


class TestRbacWrongRoleOnTerminalRoutes:
    """Un JWT CLIENT/MANAGER/HAIRDRESSER/ADMIN est refusé sur les routes terminal (403)."""

    @pytest.mark.parametrize("token", [
        _MANAGER_TOKEN,
        _CLIENT_TOKEN,
        _HAIRDRESSER_TOKEN,
        _ADMIN_TOKEN,
    ])
    def test_lookup_non_terminal_role_returns_403(
        self, base_client: TestClient, token: str
    ) -> None:
        r = base_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    @pytest.mark.parametrize("token", [
        _MANAGER_TOKEN,
        _CLIENT_TOKEN,
        _HAIRDRESSER_TOKEN,
        _ADMIN_TOKEN,
    ])
    def test_create_non_terminal_role_returns_403(
        self, base_client: TestClient, token: str
    ) -> None:
        r = base_client.post(
            _CREATE_URL,
            json={"first_name": "Awa", "last_name": "Koné", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_403_detail_is_generic_and_constant(
        self, base_client: TestClient
    ) -> None:
        """Le message 403 est générique — aucun oracle sur les permissions (§11.1)."""
        r = base_client.post(
            _LOOKUP_URL,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        # Seul le code compte ; le corps est générique, on vérifie qu'il ne contient
        # pas de détail sur les permissions manquantes.
        assert r.status_code == 403
        assert "TERMINAL" not in r.json().get("detail", "")


# ---------------------------------------------------------------------------
# RBAC négatif — credential TERMINAL refusé sur routes non-terminal
# ---------------------------------------------------------------------------


class TestRbacTerminalRefusedOnManagerRoutes:
    """Un JWT TERMINAL ne peut pas atteindre `CUSTOMER_MANAGE` (MANAGER-seul).

    Le moindre privilège est vérifié ici pour la route gérant la plus proche :
    `POST /salons/{id}/customers` (`CUSTOMER_MANAGE`). Le TERMINAL ne détient que
    `CUSTOMER_LOOKUP_TERMINAL` + `CUSTOMER_CREATE_WALKIN` + `QUEUE_TICKET_CREATE`.
    """

    def test_terminal_cannot_access_customer_manage(
        self, base_client: TestClient
    ) -> None:
        r = base_client.post(
            _MANAGER_CUSTOMERS_URL,
            json={"full_name": "Awa Koné"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# RBAC négatif — portée cross-salon (device du salon A → refus salon B)
# ---------------------------------------------------------------------------


class TestRbacCrossSalonScope:
    """Un credential TERMINAL du salon A ne peut pas interroger le salon B."""

    def test_lookup_cross_salon_returns_403(
        self, terminal_client: TestClient
    ) -> None:
        r = terminal_client.post(
            _LOOKUP_URL_B,
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 403

    def test_create_cross_salon_returns_403(
        self, terminal_client: TestClient
    ) -> None:
        r = terminal_client.post(
            _CREATE_URL_B,
            json={"first_name": "Awa", "last_name": "Koné", "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert r.status_code == 403
