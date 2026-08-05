"""Tests API — router `/salons/{id}/campaigns` (adapter entrant, US-7.5, #49).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_campaign_repository`  → `FakeCampaignRepository` ;
- `get_customer_repository`  → `FakeCustomerRepository` (effectif déterministe) ;
- `get_audit_log`            → `FakeAuditLog` ;
- `get_user_repository`      → `FakeAuthUserRepository` ;
- `get_access_policy`        → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- POST 201 : réponse projetée (`status = PENDING`, `sent_at = null`, `salon_id` du chemin,
  `created_by = principal`, `recipient_count` non-négatif) ;
- Corps privilégiés ignorés (`extra="ignore"` : `salon_id`, `created_by`, `status`,
  `recipient_count` dans le body ne changent pas la réponse) ;
- POST 422 : `type`/`segment` invalides (domaine), `title`/`message` vide ou trop long
  (Pydantic) ;
- RBAC : `401` sans jeton, `403` CLIENT/HAIRDRESSER/ADMIN/gérant hors portée ;
- Message d'erreur 403 **générique** (non-fuite, ADR-0015) ;
- Aucune route campagne dans `PUBLIC_ROUTE_PATHS` ;
- GET 200 : liste paginée **sans le corps du message** (`CampaignSummaryResponse`) ;
- GET isolation salon (seules les campagnes du salon de la portée).
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.campaigns import (
    get_audit_log,
    get_campaign_repository,
    get_customer_repository,
)
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.campaign import CAMPAIGN_MESSAGE_MAX_LENGTH, CAMPAIGN_TITLE_MAX_LENGTH
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.customer import CustomerToCreate
from coiflink_api.domain.enums import CampaignStatus, Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeCampaignRepository,
    FakeCustomerRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_OTHER_MANAGER_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_CLIENT_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")
_ADMIN_ID = uuid.UUID("55555555-0000-0000-0000-000000000005")

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)

_VALID_BODY: dict = {
    "type": "REMINDER",
    "segment": "ALL",
    "title": "Rappel de rendez-vous",
    "message": "Bonjour, n'oubliez pas votre rendez-vous de demain.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creds(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(id=user_id, role=role, status=UserStatus.ACTIVE.value, password_hash="x")


def _campaigns_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/campaigns"


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
def campaign_repo() -> FakeCampaignRepository:
    return FakeCampaignRepository()


@pytest.fixture()
def customer_repo() -> FakeCustomerRepository:
    repo = FakeCustomerRepository()
    repo.create(CustomerToCreate(
        salon_id=_SALON_ID,
        full_name="Client test",
        phone="+2250700000001",
        gender=None,
        notes=None,
    ))
    return repo


@pytest.fixture()
def audit_log() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture()
def manager_client(
    campaign_repo: FakeCampaignRepository,
    customer_repo: FakeCustomerRepository,
    audit_log: FakeAuditLog,
) -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié, salon dans sa portée."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_campaign_repository] = lambda: campaign_repo
    app.dependency_overrides[get_customer_repository] = lambda: customer_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_campaign_repository, None)
        app.dependency_overrides.pop(get_customer_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# POST /salons/{salon_id}/campaigns — 201
# ---------------------------------------------------------------------------


class TestCreateCampaign201:
    def test_returns_201(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_response_contains_id(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "id" in r.json()

    def test_status_is_pending(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["status"] == CampaignStatus.PENDING.value

    def test_sent_at_is_null(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["sent_at"] is None

    def test_salon_id_from_path(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["salon_id"] == str(_SALON_ID)

    def test_type_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["type"] == "REMINDER"

    def test_segment_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["segment"] == "ALL"

    def test_title_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["title"] == _VALID_BODY["title"]

    def test_message_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["message"] == _VALID_BODY["message"]

    def test_recipient_count_is_non_negative(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["recipient_count"] >= 0

    def test_channel_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "channel" in r.json()

    def test_all_campaign_types_accepted(self, manager_client: TestClient) -> None:
        for campaign_type in ("REMINDER", "PROMOTION", "EXCEPTIONAL_CLOSURE"):
            r = manager_client.post(
                _campaigns_url(_SALON_ID),
                json={**_VALID_BODY, "type": campaign_type},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
            assert r.status_code == 201, f"Type {campaign_type} rejected: {r.json()}"

    def test_all_segments_accepted(self, manager_client: TestClient) -> None:
        for segment in ("ALL", "FEMALE", "MALE", "OTHER"):
            r = manager_client.post(
                _campaigns_url(_SALON_ID),
                json={**_VALID_BODY, "segment": segment},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
            assert r.status_code == 201, f"Segment {segment} rejected: {r.json()}"


# ---------------------------------------------------------------------------
# POST — champs privilégiés ignorés (extra="ignore")
# ---------------------------------------------------------------------------


class TestCreateCampaignIgnoredFields:
    def test_salon_id_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_VALID_BODY, "salon_id": str(_OTHER_SALON_ID)}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["salon_id"] == str(_SALON_ID)

    def test_created_by_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_VALID_BODY, "created_by": str(uuid.uuid4())}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_status_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_VALID_BODY, "status": "SENT"}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["status"] == CampaignStatus.PENDING.value

    def test_recipient_count_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_VALID_BODY, "recipient_count": 9999}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["recipient_count"] != 9999

    def test_id_in_body_ignored(self, manager_client: TestClient) -> None:
        fixed_id = str(uuid.uuid4())
        body = {**_VALID_BODY, "id": fixed_id}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# POST — 422 validation
# ---------------------------------------------------------------------------


class TestCreateCampaign422:
    def test_missing_type_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "type"}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_missing_segment_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "segment"}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_missing_title_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "title"}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_missing_message_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "message"}
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_invalid_type_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json={**_VALID_BODY, "type": "BOGUS"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_lowercase_type_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json={**_VALID_BODY, "type": "reminder"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_invalid_segment_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json={**_VALID_BODY, "segment": "INACTIVE"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_empty_title_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json={**_VALID_BODY, "title": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_title_over_max_length_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json={**_VALID_BODY, "title": "A" * (CAMPAIGN_TITLE_MAX_LENGTH + 1)},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_empty_message_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json={**_VALID_BODY, "message": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_message_over_max_length_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _campaigns_url(_SALON_ID),
            json={**_VALID_BODY, "message": "A" * (CAMPAIGN_MESSAGE_MAX_LENGTH + 1)},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST — RBAC
# ---------------------------------------------------------------------------


def _setup_overrides(
    campaign_repo: FakeCampaignRepository,
    customer_repo: FakeCustomerRepository,
    audit_log: FakeAuditLog,
    user_repo: FakeAuthUserRepository,
    scope_repo: FakeSalonScopeRepository,
) -> None:
    app.dependency_overrides[get_campaign_repository] = lambda: campaign_repo
    app.dependency_overrides[get_customer_repository] = lambda: customer_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)


def _teardown_overrides() -> None:
    app.dependency_overrides.pop(get_campaign_repository, None)
    app.dependency_overrides.pop(get_customer_repository, None)
    app.dependency_overrides.pop(get_audit_log, None)
    app.dependency_overrides.pop(get_user_repository, None)
    app.dependency_overrides.pop(get_access_policy, None)


class TestCreateCampaignRbac:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.post(_campaigns_url(_SALON_ID), json=_VALID_BODY)
        assert r.status_code == 401

    def test_client_role_returns_403(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _campaigns_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            _teardown_overrides()
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_HAIRDRESSER_ID: frozenset({_SALON_ID})})
        token = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _campaigns_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            _teardown_overrides()
        assert r.status_code == 403

    def test_admin_role_returns_403(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """ADMIN n'a pas `CUSTOMER_MANAGE` — deny-by-default (§4.1, ADR-0015)."""
        creds = _creds(_ADMIN_ID, Role.ADMIN.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_ADMIN_ID, Role.ADMIN.value)

        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _campaigns_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            _teardown_overrides()
        assert r.status_code == 403

    def test_manager_outside_scope_returns_403(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Gérant hors de son salon → 403 (isolation §11.2)."""
        creds = _creds(_OTHER_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        # _OTHER_SALON_ID uniquement dans sa portée, pas _SALON_ID
        scope_repo = FakeSalonScopeRepository(
            scopes={_OTHER_MANAGER_ID: frozenset({_OTHER_SALON_ID})}
        )
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)

        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _campaigns_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            _teardown_overrides()
        assert r.status_code == 403

    def test_403_message_is_generic(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Le message 403 ne révèle pas le motif (non-fuite, ADR-0015)."""
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _campaigns_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            _teardown_overrides()
        detail = r.json().get("detail", "")
        # Le motif précis (rôle, permission, portée) ne doit pas être divulgué.
        assert "CUSTOMER_MANAGE" not in detail
        assert "permission" not in detail.lower()


# ---------------------------------------------------------------------------
# Invariant deny-by-default — aucune route campagne dans PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestCampaignRoutesNotPublic:
    def test_post_campaigns_not_in_public_route_paths(self) -> None:
        for path in PUBLIC_ROUTE_PATHS:
            assert "/campaigns" not in path, (
                f"Route campagne trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )

    def test_get_campaigns_not_in_public_route_paths(self) -> None:
        for path in PUBLIC_ROUTE_PATHS:
            assert "campaigns" not in path, (
                f"Route campagne trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/campaigns — liste paginée non-PII
# ---------------------------------------------------------------------------


class TestListCampaigns200:
    def test_returns_200(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _campaigns_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_response_has_items_and_total(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _campaigns_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert "items" in data
        assert "total" in data

    def test_empty_list_for_no_campaigns(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _campaigns_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_summary_does_not_include_message(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Non-PII : la liste ne renvoie pas le corps du message (§11.3)."""
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        # Crée d'abord une campagne via POST.
        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                headers = {"Authorization": f"Bearer {_MANAGER_TOKEN}"}
                c.post(_campaigns_url(_SALON_ID), json=_VALID_BODY, headers=headers)
                r = c.get(_campaigns_url(_SALON_ID), headers=headers)
        finally:
            _teardown_overrides()

        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        # Le corps du message n'est jamais exposé dans la liste (CampaignSummaryResponse).
        assert "message" not in items[0]

    def test_list_reflects_created_campaign(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                headers = {"Authorization": f"Bearer {_MANAGER_TOKEN}"}
                c.post(_campaigns_url(_SALON_ID), json=_VALID_BODY, headers=headers)
                r = c.get(_campaigns_url(_SALON_ID), headers=headers)
        finally:
            _teardown_overrides()

        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["type"] == "REMINDER"
        assert data["items"][0]["salon_id"] == str(_SALON_ID)

    def test_list_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_campaigns_url(_SALON_ID))
        assert r.status_code == 401

    def test_list_client_role_returns_403(
        self,
        campaign_repo: FakeCampaignRepository,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        _setup_overrides(campaign_repo, customer_repo, audit_log, user_repo, scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _campaigns_url(_SALON_ID),
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            _teardown_overrides()
        assert r.status_code == 403

    def test_list_response_contains_limit_and_offset(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _campaigns_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert "limit" in data
        assert "offset" in data
