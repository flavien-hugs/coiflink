"""Tests API — `GET /salons/{id}/audit-logs` (page gérante « Journal d'audit »).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_audit_log` → `FakeAuditLogRepository` (locale à ce fichier, miroir
  `FakePaymentRepository` de `conftest.py`) ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 sans filtre : page `items`/`total`/`limit`/`offset`, entrée résolue
  (`action`/`category`/`actor_name`/`created_at`) ;
- 200 avec filtre `category`/`date_from`/`date_to` — forwardés au dépôt ;
- 422 catégorie hors énumération / plage de dates incohérente — message neutre ;
- 401 sans jeton ; 403 pour tout rôle autre que MANAGER (seul détenteur
  d'`AUDIT_LOG_READ`) ;
- aucune route de type `GET /salons/{id}/audit-logs` dans `PUBLIC_ROUTE_PATHS`.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.payments import get_audit_log
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.audit import AuditLogEntry
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuthUserRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_CLIENT_ID = uuid.UUID("11111111-0000-0000-0000-000000000011")
_HAIRDRESSER_ID = uuid.UUID("22222222-0000-0000-0000-000000000022")
_TERMINAL_ID = uuid.UUID("33333333-0000-0000-0000-000000000033")

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_ENTITY_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
_TERMINAL_TOKEN = make_access_token(_TERMINAL_ID, Role.TERMINAL.value)


def _audit_logs_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/audit-logs"


def _creds(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(
        id=user_id, role=role, status=UserStatus.ACTIVE.value, password_hash="x"
    )


def _make_entry(
    *,
    action: str = "SERVICE_UPDATED",
    category: str = "prestations",
    actor_name: str = "Awa Koné",
    created_at: datetime.datetime | None = None,
) -> AuditLogEntry:
    return AuditLogEntry(
        id=uuid.uuid4(),
        action=action,
        category=category,  # type: ignore[arg-type]
        entity_type="service",
        entity_id=_ENTITY_ID,
        actor_name=actor_name,
        created_at=created_at or datetime.datetime(2026, 8, 7, 10, 0, tzinfo=datetime.timezone.utc),
    )


# ---------------------------------------------------------------------------
# Fake dépôt (miroir `FakePaymentRepository`, local à ce fichier)
# ---------------------------------------------------------------------------


class FakeAuditLogRepository:
    """Dépôt du journal d'audit en mémoire — implémente le port `AuditLog`."""

    def __init__(self, entries: list[AuditLogEntry] | None = None) -> None:
        self._entries: list[AuditLogEntry] = list(entries or [])
        self.list_calls: list[dict] = []
        self.count_calls: list[dict] = []

    def record(self, entry) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError("lecture seule dans ce test")

    def _filtered(self, *, date_from, date_to, category):  # type: ignore[no-untyped-def]
        result = self._entries
        if date_from is not None:
            result = [e for e in result if e.created_at.date() >= date_from]
        if date_to is not None:
            result = [e for e in result if e.created_at.date() <= date_to]
        if category is not None:
            result = [e for e in result if e.category == category]
        return result

    def list_for_salon(
        self, salon_id, *, date_from, date_to, category, limit, offset
    ):  # type: ignore[no-untyped-def]
        self.list_calls.append(
            {
                "salon_id": salon_id,
                "date_from": date_from,
                "date_to": date_to,
                "category": category,
                "limit": limit,
                "offset": offset,
            }
        )
        filtered = self._filtered(date_from=date_from, date_to=date_to, category=category)
        return tuple(filtered[offset : offset + limit])

    def count_for_salon(self, salon_id, *, date_from, date_to, category):  # type: ignore[no-untyped-def]
        self.count_calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to, "category": category}
        )
        return len(self._filtered(date_from=date_from, date_to=date_to, category=category))


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
def audit_log_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


@pytest.fixture()
def manager_client(
    audit_log_repo: FakeAuditLogRepository,
) -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié et salon dans sa portée."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_audit_log] = lambda: audit_log_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# 200 — sans filtre
# ---------------------------------------------------------------------------


class TestListAuditLogs200NoFilter:
    def test_returns_200(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 200

    def test_empty_repo_total_is_zero(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["total"] == 0
        assert r.json()["items"] == []

    def test_seeded_entry_returns_one_item(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        audit_log_repo._entries.append(_make_entry())
        r = manager_client.get(
            _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        data = r.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_item_fields_resolved(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        audit_log_repo._entries.append(
            _make_entry(action="EMPLOYEE_CREATED", category="employes", actor_name="Fatou")
        )
        r = manager_client.get(
            _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert item["action"] == "EMPLOYEE_CREATED"
        assert item["category"] == "employes"
        assert item["actor_name"] == "Fatou"
        assert item["entity_type"] == "service"
        assert "id" in item
        assert "entity_id" in item
        assert "created_at" in item

    def test_item_never_exposes_metadata(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        audit_log_repo._entries.append(_make_entry())
        r = manager_client.get(
            _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "metadata" not in r.json()["items"][0]

    def test_response_has_pagination_fields(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        data = r.json()
        assert "limit" in data
        assert "offset" in data


# ---------------------------------------------------------------------------
# 200 — filtres
# ---------------------------------------------------------------------------


class TestListAuditLogsFilters:
    def test_category_filter_forwarded(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID),
            params={"category": "employes"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        assert audit_log_repo.list_calls[-1]["category"] == "employes"

    def test_category_filter_excludes_other_categories(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        audit_log_repo._entries.append(_make_entry(category="prestations"))
        audit_log_repo._entries.append(
            _make_entry(action="EMPLOYEE_CREATED", category="employes")
        )
        r = manager_client.get(
            _audit_logs_url(_SALON_ID),
            params={"category": "employes"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["category"] == "employes"

    def test_date_range_forwarded(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID),
            params={"date_from": "2026-08-01", "date_to": "2026-08-07"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        call = audit_log_repo.list_calls[-1]
        assert str(call["date_from"]) == "2026-08-01"
        assert str(call["date_to"]) == "2026-08-07"

    def test_limit_offset_forwarded(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID),
            params={"limit": 10, "offset": 5},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["limit"] == 10
        assert data["offset"] == 5


# ---------------------------------------------------------------------------
# 422 — filtre invalide
# ---------------------------------------------------------------------------


class TestListAuditLogs422:
    def test_unknown_category_raises_422(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID),
            params={"category": "not-a-real-category"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_date_from_gt_date_to_raises_422(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID),
            params={"date_from": "2026-08-07", "date_to": "2026-08-01"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_422_message_does_not_repeat_invalid_category(
        self, manager_client: TestClient, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        r = manager_client.get(
            _audit_logs_url(_SALON_ID),
            params={"category": "super-secret-xyz"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "super-secret-xyz" not in r.text


# ---------------------------------------------------------------------------
# 401 / 403 — RBAC
# ---------------------------------------------------------------------------


class TestListAuditLogsAuthz:
    def test_no_token_returns_401(self) -> None:
        r = TestClient(app).get(_audit_logs_url(_SALON_ID))
        assert r.status_code == 401

    def test_client_role_gets_403(self, audit_log_repo: FakeAuditLogRepository) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        app.dependency_overrides[get_audit_log] = lambda: audit_log_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
            FakeSalonScopeRepository()
        )
        try:
            r = TestClient(app).get(
                _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_hairdresser_role_gets_403(self, audit_log_repo: FakeAuditLogRepository) -> None:
        """Le coiffeur n'a pas `AUDIT_LOG_READ` — outil de preuve réservé au gérant."""
        creds = _creds(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        app.dependency_overrides[get_audit_log] = lambda: audit_log_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
            FakeSalonScopeRepository(scopes={_HAIRDRESSER_ID: frozenset({_SALON_ID})})
        )
        try:
            r = TestClient(app).get(
                _audit_logs_url(_SALON_ID),
                headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_terminal_role_gets_403(self, audit_log_repo: FakeAuditLogRepository) -> None:
        creds = _creds(_TERMINAL_ID, Role.TERMINAL.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        app.dependency_overrides[get_audit_log] = lambda: audit_log_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
            FakeSalonScopeRepository()
        )
        try:
            r = TestClient(app).get(
                _audit_logs_url(_SALON_ID),
                headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_manager_without_scope_gets_403(
        self, audit_log_repo: FakeAuditLogRepository
    ) -> None:
        """Gérant authentifié mais **sans** portée sur ce salon → 403 (avant tout accès au dépôt)."""
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        app.dependency_overrides[get_audit_log] = lambda: audit_log_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
            FakeSalonScopeRepository()  # aucune portée accordée
        )
        try:
            r = TestClient(app).get(
                _audit_logs_url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Absence de la route dans les chemins publics
# ---------------------------------------------------------------------------


class TestAuditLogsNotPublic:
    def test_audit_logs_path_not_in_public_route_paths(self) -> None:
        assert "/salons/{salon_id}/audit-logs" not in PUBLIC_ROUTE_PATHS
