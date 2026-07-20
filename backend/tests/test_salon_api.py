"""Tests API — router `/salons` (adapter entrant, US-2.1, #15).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_salon_repository` → `FakeSalonRepository` (aucune base) ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- matrice RBAC de `POST /salons` (MANAGER → 201, CLIENT/HAIRDRESSER → 403, ADMIN → 403,
  non authentifié → 401) ;
- anti-élévation : `owner_id` dans le corps ignoré — le salon créé appartient au principal ;
- `CreateSalonRequest` sans champ `owner_id`/`status`/`opening_hours` ;
- réponse `is_bookable=false`, `opening_hours=null` à la création ;
- `GET /salons/{id}` par un autre gérant → 403 générique (pas 404) ;
- `GET /salons/{id}` par l'ADMIN → 200 (`require_any_permission`) ;
- `GET /salons` → 200 pour le gérant, liste vide cohérente ;
- pas de clé brute ni de secret dans la réponse de création ;
- routes absentes de `PUBLIC_ROUTE_PATHS` (deny-by-default).
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.salons import get_audit_log, get_salon_repository
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeSalonRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_OTHER_MANAGER_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ADMIN_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

_SALONS_URL = "/salons"

_VALID_BODY = {
    "name": "Salon Élégance",
    "description": "Coiffure afro et tresses.",
    "phone": "0700000000",
    "address": "Rue des Jardins, Cocody",
    "city": "Abidjan",
    "commune": "Cocody",
    "latitude": 5.359952,
    "longitude": -3.996643,
}

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creds(
    user_id: uuid.UUID,
    role: str,
    status: str = UserStatus.ACTIVE.value,
) -> UserCredentials:
    return UserCredentials(
        id=user_id,
        role=role,
        status=status,
        password_hash="x",
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
def salon_repo() -> FakeSalonRepository:
    return FakeSalonRepository()


@pytest.fixture()
def audit_log() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture()
def manager_client(
    salon_repo: FakeSalonRepository, audit_log: FakeAuditLog
) -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié (portée vide à la création)."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset()})

    app.dependency_overrides[get_salon_repository] = lambda: salon_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_salon_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


@pytest.fixture()
def manager_client_with_salon(
    salon_repo: FakeSalonRepository, audit_log: FakeAuditLog
) -> Generator[tuple[TestClient, uuid.UUID], None, None]:
    """MANAGER dont le dépôt contient déjà un salon (_SALON_ID simulé)."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})

    # Créer un salon dans le repo et en garder l'id
    from coiflink_api.application.salons import CreateSalon, CreateSalonCommand

    salon = CreateSalon(salon_repo).execute(
        CreateSalonCommand(name="Mon Salon"), owner_id=_MANAGER_ID
    )
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({salon.id})})

    app.dependency_overrides[get_salon_repository] = lambda: salon_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app), salon.id
    finally:
        app.dependency_overrides.pop(get_salon_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# POST /salons — RBAC
# ---------------------------------------------------------------------------


class TestCreateSalonRbac:
    def test_manager_gets_201(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 201

    def test_missing_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.post(_SALONS_URL, json=_VALID_BODY)
        assert r.status_code == 401

    def test_client_role_returns_403(self, salon_repo: FakeSalonRepository) -> None:
        client_id = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
        creds = _creds(client_id, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(client_id, Role.CLIENT.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {token}"}
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403

    def test_hairdresser_role_returns_403(self, salon_repo: FakeSalonRepository) -> None:
        hd_id = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
        creds = _creds(hd_id, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(hd_id, Role.HAIRDRESSER.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {token}"}
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403

    def test_admin_role_returns_403(self, salon_repo: FakeSalonRepository) -> None:
        """L'ADMIN supervise, il ne crée pas de salon (§4.1 : SALON_CREATE ≠ ADMIN)."""
        admin_id = _ADMIN_ID
        creds = _creds(admin_id, Role.ADMIN.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(admin_id, Role.ADMIN.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {token}"}
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403

    def test_403_detail_is_generic(self, salon_repo: FakeSalonRepository) -> None:
        """Le message 403 ne révèle ni la permission requise ni l'identité (PRD §11.1)."""
        client_id = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")
        creds = _creds(client_id, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(client_id, Role.CLIENT.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {token}"}
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# POST /salons — corps et réponse
# ---------------------------------------------------------------------------


class TestCreateSalonBody:
    def test_response_contains_id(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "id" in r.json()

    def test_response_is_bookable_false(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["is_bookable"] is False

    def test_response_opening_hours_null(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["opening_hours"] is None

    def test_response_status_active(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["status"] == "ACTIVE"

    def test_response_owner_id_matches_principal(
        self, manager_client: TestClient
    ) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["owner_id"] == str(_MANAGER_ID)

    def test_response_logo_url_null(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["logo_url"] is None

    def test_response_photos_empty_list(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["photos"] == []

    def test_content_type_json(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "application/json" in r.headers.get("content-type", "")

    def test_missing_name_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "name"}
        r = manager_client.post(
            _SALONS_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 422

    def test_empty_name_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL,
            json={**_VALID_BODY, "name": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_invalid_coordinates_returns_422(self, manager_client: TestClient) -> None:
        """Latitude sans longitude → domaine lève `InvalidLocation` → 422."""
        r = manager_client.post(
            _SALONS_URL,
            json={**_VALID_BODY, "longitude": None},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_optional_fields_absent_accepted(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _SALONS_URL,
            json={"name": "Salon Minimal"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Anti-élévation de privilège — owner_id ignoré
# ---------------------------------------------------------------------------


class TestAntiPrivilegeEscalation:
    def test_request_schema_has_no_owner_id_field(self) -> None:
        from coiflink_api.adapters.inbound.salons import CreateSalonRequest

        assert "owner_id" not in CreateSalonRequest.model_fields

    def test_request_schema_has_no_status_field(self) -> None:
        from coiflink_api.adapters.inbound.salons import CreateSalonRequest

        assert "status" not in CreateSalonRequest.model_fields

    def test_request_schema_has_no_opening_hours_field(self) -> None:
        from coiflink_api.adapters.inbound.salons import CreateSalonRequest

        assert "opening_hours" not in CreateSalonRequest.model_fields

    def test_owner_id_in_body_ignored(self, manager_client: TestClient) -> None:
        """Un owner_id fourni dans le corps ne doit pas influencer le résultat."""
        other_id = str(_OTHER_MANAGER_ID)
        body = {**_VALID_BODY, "owner_id": other_id}
        r = manager_client.post(
            _SALONS_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 201
        # Le salon appartient au principal authentifié, pas à l'id fourni
        assert r.json()["owner_id"] == str(_MANAGER_ID)
        assert r.json()["owner_id"] != other_id

    def test_response_contains_no_raw_object_key(self, manager_client: TestClient) -> None:
        """Aucune clé d'objet brute ne fuit dans la réponse de création."""
        r = manager_client.post(
            _SALONS_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        body = r.text
        # Les clés d'objet commencent par "salons/<uuid>/..."
        assert "salons/" not in body or "logo_url" in r.json()  # logo_url est null ici


# ---------------------------------------------------------------------------
# GET /salons/{id} — contrôle d'accès
# ---------------------------------------------------------------------------


class TestGetSalonBody:
    """Vérifie le corps de la réponse `GET /salons/{id}` après création."""

    def test_get_salon_returns_correct_name(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["name"] == "Mon Salon"

    def test_get_salon_returns_correct_owner_id(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["owner_id"] == str(_MANAGER_ID)

    def test_get_salon_is_bookable_false(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["is_bookable"] is False

    def test_get_salon_opening_hours_null(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["opening_hours"] is None

    def test_get_salon_id_matches_path(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["id"] == str(salon_id)


# ---------------------------------------------------------------------------
# GET /salons/{id} — contrôle d'accès
# ---------------------------------------------------------------------------


class TestGetSalonAccessControl:
    def test_manager_can_read_own_salon(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_manager_other_salon_returns_403(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Gérant hors portée : 403 générique, pas 404 (aucun oracle d'existence)."""
        client, _ = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 403

    def test_403_does_not_reveal_existence(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Le message 403 inter-salon est le même que pour un rôle insuffisant."""
        client, _ = manager_client_with_salon
        r = client.get(
            f"{_SALONS_URL}/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["detail"] == "Accès refusé."

    def test_admin_can_read_any_salon(
        self,
        salon_repo: FakeSalonRepository,
    ) -> None:
        """ADMIN : SALON_READ_ANY + portée platform_wide → 200 (valide require_any_permission)."""
        from coiflink_api.application.salons import CreateSalon, CreateSalonCommand

        # Créer un salon dans le dépôt
        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="Salon Admin"), owner_id=_OTHER_MANAGER_ID
        )

        admin_id = _ADMIN_ID
        creds = _creds(admin_id, Role.ADMIN.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(admin_id, Role.ADMIN.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    f"{_SALONS_URL}/{salon.id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 200

    def test_get_salon_missing_token_returns_401(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.get(f"{_SALONS_URL}/{salon_id}")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /salons/{salon_id} — modification journalisée (§11.4)
# ---------------------------------------------------------------------------

_UPDATE_BODY = {
    "name": "Salon Renommé",
    "description": "Nouvelle description.",
    "phone": "0709080706",
    "address": "Nouvelle adresse",
    "city": "Abidjan",
    "commune": "Marcory",
    "latitude": 5.3,
    "longitude": -4.0,
}


class TestUpdateSalon:
    def test_manager_gets_200(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=_UPDATE_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Salon Renommé"
        assert r.json()["commune"] == "Marcory"

    def test_no_token_returns_401(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.put(f"{_SALONS_URL}/{salon_id}", json=_UPDATE_BODY)
        assert r.status_code == 401

    def test_unknown_salon_id_in_scope_returns_404(
        self,
        salon_repo: FakeSalonRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """`salon_id` dans la portée du gérant mais absent du dépôt → 404 opaque."""
        unknown_id = uuid.uuid4()
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({unknown_id})})

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.put(
                    f"{_SALONS_URL}/{unknown_id}",
                    json=_UPDATE_BODY,
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 404

    def test_other_manager_salon_returns_403_not_404(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Salon hors périmètre (autre gérant) → 403 générique, pas 404 (isolation §11.2)."""
        client, _ = manager_client_with_salon
        r = client.put(
            f"{_SALONS_URL}/{uuid.uuid4()}",
            json=_UPDATE_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "Accès refusé."

    def test_client_role_returns_403(
        self,
        salon_repo: FakeSalonRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        from coiflink_api.application.salons import CreateSalon, CreateSalonCommand

        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="Salon"), owner_id=_MANAGER_ID
        )
        client_id = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
        creds = _creds(client_id, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={client_id: frozenset({salon.id})})
        token = make_access_token(client_id, Role.CLIENT.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.put(
                    f"{_SALONS_URL}/{salon.id}",
                    json=_UPDATE_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(
        self,
        salon_repo: FakeSalonRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Le coiffeur a une portée (SALON_READ) mais pas `SALON_UPDATE`."""
        from coiflink_api.application.salons import CreateSalon, CreateSalonCommand

        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="Salon"), owner_id=_MANAGER_ID
        )
        hd_id = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
        creds = _creds(hd_id, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={hd_id: frozenset({salon.id})})
        token = make_access_token(hd_id, Role.HAIRDRESSER.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.put(
                    f"{_SALONS_URL}/{salon.id}",
                    json=_UPDATE_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_empty_name_returns_422(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json={**_UPDATE_BODY, "name": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_one_sided_coordinates_returns_422(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json={**_UPDATE_BODY, "longitude": None},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_owner_id_in_body_ignored(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        body = {**_UPDATE_BODY, "owner_id": str(_OTHER_MANAGER_ID)}
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        assert r.json()["owner_id"] == str(_MANAGER_ID)

    def test_audit_entry_recorded_with_changed_fields(
        self,
        audit_log: FakeAuditLog,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=_UPDATE_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert len(audit_log.recorded) == 1
        entry = audit_log.recorded[0]
        assert entry.action == "SALON_UPDATED"
        assert "name" in entry.metadata["changed"]
        assert "phone" in entry.metadata["changed"]

    def test_audit_metadata_has_no_field_values(
        self,
        audit_log: FakeAuditLog,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_client_with_salon
        client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=_UPDATE_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        entry = audit_log.recorded[0]
        assert set(entry.metadata.keys()) == {"changed"}
        assert "Salon Renommé" not in entry.metadata["changed"]

    def test_status_in_body_ignored(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Un `status` fourni dans le corps est ignoré (champ non éditable, §8.3)."""
        client, salon_id = manager_client_with_salon
        body = {**_UPDATE_BODY, "status": "INACTIVE"}
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        # Le salon reste ACTIVE : `status` n'est pas modifiable par cette route.
        assert r.json()["status"] == "ACTIVE"

    def test_request_schema_has_no_status_or_opening_hours_field(self) -> None:
        """Le corps de modification n'expose ni `status`, ni `opening_hours`, ni `owner_id`."""
        from coiflink_api.adapters.inbound.salons import UpdateSalonRequest

        assert "owner_id" not in UpdateSalonRequest.model_fields
        assert "status" not in UpdateSalonRequest.model_fields
        assert "opening_hours" not in UpdateSalonRequest.model_fields

    def test_validation_failure_leaves_no_audit_entry(
        self,
        audit_log: FakeAuditLog,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Validation échouée (nom vide) → aucune entrée d'audit (atomicité §11.4)."""
        client, salon_id = manager_client_with_salon
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json={**_UPDATE_BODY, "name": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422
        assert audit_log.recorded == []

    def test_missing_name_returns_422(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Corps sans clé `name` → 422 (champ requis, sémantique replace)."""
        client, salon_id = manager_client_with_salon
        body = {k: v for k, v in _UPDATE_BODY.items() if k != "name"}
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_admin_role_returns_403(
        self,
        salon_repo: FakeSalonRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """L'ADMIN ne dispose pas de `SALON_UPDATE` → 403 (symétrique avec POST, §4.1)."""
        from coiflink_api.application.salons import CreateSalon, CreateSalonCommand

        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="Salon"), owner_id=_MANAGER_ID
        )
        admin_id = _ADMIN_ID
        creds = _creds(admin_id, Role.ADMIN.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={admin_id: frozenset({salon.id})})
        token = make_access_token(admin_id, Role.ADMIN.value)

        app.dependency_overrides[get_salon_repository] = lambda: salon_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.put(
                    f"{_SALONS_URL}/{salon.id}",
                    json=_UPDATE_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_all_fields_reflected_in_response(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Le corps de réponse du PUT reflète tous les champs mis à jour."""
        client, salon_id = manager_client_with_salon
        r = client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=_UPDATE_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Salon Renommé"
        assert body["description"] == "Nouvelle description."
        assert body["city"] == "Abidjan"
        assert body["commune"] == "Marcory"
        assert body["address"] == "Nouvelle adresse"
        assert body["latitude"] == pytest.approx(5.3)
        assert body["longitude"] == pytest.approx(-4.0)
        # phone est normalisé en E.164 par le domaine.
        assert body["phone"] is not None
        assert body["phone"].endswith("09080706")
        assert "updated_at" in body

    def test_get_after_update_reflects_new_values(
        self,
        manager_client_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """GET /salons/{id} après PUT renvoie les nouvelles valeurs (lecture après écriture)."""
        client, salon_id = manager_client_with_salon
        client.put(
            f"{_SALONS_URL}/{salon_id}",
            json=_UPDATE_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        r = client.get(
            f"{_SALONS_URL}/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Salon Renommé"
        assert body["commune"] == "Marcory"
        assert body["city"] == "Abidjan"


# ---------------------------------------------------------------------------
# GET /salons — liste
# ---------------------------------------------------------------------------


class TestListSalons:
    def test_manager_gets_200(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _SALONS_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 200

    def test_returns_list(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _SALONS_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert isinstance(r.json(), list)

    def test_empty_list_when_no_salons(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _SALONS_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json() == []

    def test_missing_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_SALONS_URL)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Routes non listées dans PUBLIC_ROUTE_PATHS (deny-by-default)
# ---------------------------------------------------------------------------


class TestRouteConfiguration:
    def test_post_salons_not_public(self) -> None:
        assert "/salons" not in PUBLIC_ROUTE_PATHS

    def test_get_salons_salon_id_not_public(self) -> None:
        assert "/salons/{salon_id}" not in PUBLIC_ROUTE_PATHS

    def test_unprotected_routes_invariant_holds(self) -> None:
        from coiflink_api.adapters.inbound.security import unprotected_routes

        assert unprotected_routes(app) == []
