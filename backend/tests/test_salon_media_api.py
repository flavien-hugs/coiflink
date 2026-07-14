"""Tests API médias — routes `/salons/{id}/media/*`, logo et photos (US-2.1, #15).

Vérifie :
- MIME hors liste blanche → 422 ;
- object_key d'un autre salon → 422 (isolation §11.2 par référencement croisé) ;
- MEDIA_MAX_PHOTOS + 1 → 409 ;
- `media_storage=None` → 503 pour les routes d'écriture de médias
  **mais** `POST /salons` reste 201 (la création ne dépend pas du stockage) ;
- `GET /salons` et `GET /salons/{id}` sans stockage → 200 avec logo_url/photos à null.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.salons import get_salon_repository
from coiflink_api.adapters.inbound.security import get_access_policy, get_user_repository
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.application.salons import CreateSalon, CreateSalonCommand
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuthUserRepository,
    FakeMediaStorage,
    FakeSalonRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@contextlib.contextmanager
def _setup_manager(
    salon_repo: FakeSalonRepository,
    salon_id: uuid.UUID,
    media_storage: FakeMediaStorage | None,
) -> Generator[TestClient, None, None]:
    """Installe les overrides pour un MANAGER propriétaire de `salon_id`."""
    creds = UserCredentials(
        id=_MANAGER_ID,
        role=Role.MANAGER.value,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({salon_id})})

    original_storage = getattr(app.state, "media_storage", None)
    app.state.media_storage = media_storage
    app.dependency_overrides[get_salon_repository] = lambda: salon_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.state.media_storage = original_storage
        app.dependency_overrides.pop(get_salon_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


@pytest.fixture()
def salon_and_repo() -> tuple[uuid.UUID, FakeSalonRepository]:
    """Dépôt contenant un salon pré-créé appartenant au MANAGER."""
    repo = FakeSalonRepository()
    salon = CreateSalon(repo).execute(CreateSalonCommand(name="Mon Salon"), owner_id=_MANAGER_ID)
    return salon.id, repo


# ---------------------------------------------------------------------------
# POST /salons/{id}/media/upload-url
# ---------------------------------------------------------------------------


class TestMediaRbac:
    """Vérifie que seul le MANAGER (SALON_UPDATE) peut modifier les médias (#12, §4.1)."""

    @contextlib.contextmanager
    def _hairdresser_client(
        self,
        salon_id: uuid.UUID,
        repo: FakeSalonRepository,
    ) -> Generator[TestClient, None, None]:
        hd_id = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
        creds = UserCredentials(
            id=hd_id,
            role=Role.HAIRDRESSER.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
        )
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        # Le HAIRDRESSER a la portée du salon (il y est rattaché) mais pas SALON_UPDATE.
        scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({salon_id})})
        token = make_access_token(hd_id, Role.HAIRDRESSER.value)

        original_storage = getattr(app.state, "media_storage", None)
        app.state.media_storage = FakeMediaStorage()
        app.dependency_overrides[get_salon_repository] = lambda: repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            yield TestClient(app), token
        finally:
            app.state.media_storage = original_storage
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_hairdresser_cannot_issue_upload_url(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        with self._hairdresser_client(salon_id, repo) as (c, token):
            r = c.post(
                f"/salons/{salon_id}/media/upload-url",
                json={"kind": "logo", "content_type": "image/png"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 403

    def test_hairdresser_cannot_set_logo(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        valid_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        with self._hairdresser_client(salon_id, repo) as (c, token):
            r = c.put(
                f"/salons/{salon_id}/logo",
                json={"object_key": valid_key},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 403

    def test_hairdresser_cannot_add_photo(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        valid_key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        with self._hairdresser_client(salon_id, repo) as (c, token):
            r = c.post(
                f"/salons/{salon_id}/photos",
                json={"object_key": valid_key},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 403

    def test_hairdresser_cannot_delete_photo(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        photo = repo.add_photo(salon_id, key)
        with self._hairdresser_client(salon_id, repo) as (c, token):
            r = c.delete(
                f"/salons/{salon_id}/photos/{photo.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 403


class TestIssueUploadUrl:
    def test_valid_mime_returns_200(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        storage = FakeMediaStorage()
        with _setup_manager(repo, salon_id, storage) as c:
            r = c.post(
                f"/salons/{salon_id}/media/upload-url",
                json={"kind": "logo", "content_type": "image/png"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 200

    def test_response_contains_object_key(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        storage = FakeMediaStorage()
        with _setup_manager(repo, salon_id, storage) as c:
            r = c.post(
                f"/salons/{salon_id}/media/upload-url",
                json={"kind": "photo", "content_type": "image/jpeg"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert "object_key" in r.json()
        assert r.json()["object_key"].startswith(f"salons/{salon_id}/photos/")

    def test_invalid_mime_returns_422(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        storage = FakeMediaStorage()
        with _setup_manager(repo, salon_id, storage) as c:
            r = c.post(
                f"/salons/{salon_id}/media/upload-url",
                json={"kind": "logo", "content_type": "image/gif"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 422

    def test_no_storage_returns_503(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        with _setup_manager(repo, salon_id, None) as c:
            r = c.post(
                f"/salons/{salon_id}/media/upload-url",
                json={"kind": "logo", "content_type": "image/png"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 503

    def test_object_key_does_not_contain_pii(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        """La clé d'objet retournée ne contient pas de nom de fichier client."""
        salon_id, repo = salon_and_repo
        storage = FakeMediaStorage()
        with _setup_manager(repo, salon_id, storage) as c:
            r = c.post(
                f"/salons/{salon_id}/media/upload-url",
                json={"kind": "logo", "content_type": "image/png"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        key = r.json()["object_key"]
        # La clé ne doit contenir que des UUID opaques, pas de données texte clientes
        assert "salon_elegance" not in key.lower()
        assert key.startswith(f"salons/{salon_id}/logo/")


# ---------------------------------------------------------------------------
# PUT /salons/{id}/logo
# ---------------------------------------------------------------------------


class TestSetLogo:
    def test_valid_key_returns_200(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        valid_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        with _setup_manager(repo, salon_id, None) as c:
            r = c.put(
                f"/salons/{salon_id}/logo",
                json={"object_key": valid_key},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 200

    def test_key_from_other_salon_returns_422(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        other_salon_id = uuid.uuid4()
        bad_key = f"salons/{other_salon_id}/logo/{uuid.uuid4()}.png"
        with _setup_manager(repo, salon_id, None) as c:
            r = c.put(
                f"/salons/{salon_id}/logo",
                json={"object_key": bad_key},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 422

    def test_missing_token_returns_401(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        valid_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        with _setup_manager(repo, salon_id, None) as c:
            r = c.put(
                f"/salons/{salon_id}/logo",
                json={"object_key": valid_key},
            )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /salons/{id}/photos
# ---------------------------------------------------------------------------


class TestAddPhoto:
    def test_valid_key_returns_201(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        valid_key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        with _setup_manager(repo, salon_id, None) as c:
            r = c.post(
                f"/salons/{salon_id}/photos",
                json={"object_key": valid_key},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 201

    def test_key_from_other_salon_returns_422(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        other_id = uuid.uuid4()
        bad_key = f"salons/{other_id}/photos/{uuid.uuid4()}.jpg"
        with _setup_manager(repo, salon_id, None) as c:
            r = c.post(
                f"/salons/{salon_id}/photos",
                json={"object_key": bad_key},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 422

    def test_photo_limit_exceeded_returns_409(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        """MEDIA_MAX_PHOTOS + 1 photos → 409 Conflict."""
        from coiflink_api.config import DEFAULT_MEDIA_MAX_PHOTOS

        salon_id, repo = salon_and_repo
        # Pré-remplir le dépôt jusqu'à la limite
        for _ in range(DEFAULT_MEDIA_MAX_PHOTOS):
            key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
            repo.add_photo(salon_id, key)

        over_key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        with _setup_manager(repo, salon_id, None) as c:
            r = c.post(
                f"/salons/{salon_id}/photos",
                json={"object_key": over_key},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 409

    def test_missing_token_returns_401(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        with _setup_manager(repo, salon_id, None) as c:
            r = c.post(f"/salons/{salon_id}/photos", json={"object_key": key})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /salons/{id}/photos/{photo_id}
# ---------------------------------------------------------------------------


class TestDeletePhoto:
    def test_existing_photo_returns_204(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        photo = repo.add_photo(salon_id, key)

        with _setup_manager(repo, salon_id, None) as c:
            r = c.delete(
                f"/salons/{salon_id}/photos/{photo.id}",
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 204

    def test_unknown_photo_returns_404(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        with _setup_manager(repo, salon_id, None) as c:
            r = c.delete(
                f"/salons/{salon_id}/photos/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /salons ne dépend PAS du stockage objet
# ---------------------------------------------------------------------------


class TestCreateSalonWithoutStorage:
    def test_post_salons_returns_201_without_storage(self) -> None:
        """La création d'un salon doit fonctionner même sans stockage objet configuré."""
        repo = FakeSalonRepository()
        creds = UserCredentials(
            id=_MANAGER_ID,
            role=Role.MANAGER.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
        )
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()

        original_storage = getattr(app.state, "media_storage", None)
        app.state.media_storage = None  # pas de stockage
        app.dependency_overrides[get_salon_repository] = lambda: repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/salons",
                    json={"name": "Salon Sans Stockage"},
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.state.media_storage = original_storage
            app.dependency_overrides.pop(get_salon_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 201


# ---------------------------------------------------------------------------
# GET sans stockage → logo_url et photos.url à null
# ---------------------------------------------------------------------------


class TestReadWithoutStorage:
    def test_get_salon_without_storage_returns_200(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        # Attacher un logo pour s'assurer qu'il est résolu à null sans stockage
        logo_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        repo.set_logo(salon_id, logo_key)

        with _setup_manager(repo, salon_id, None) as c:
            r = c.get(
                f"/salons/{salon_id}",
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 200
        # Sans stockage, l'URL signée n'est pas disponible → null
        assert r.json()["logo_url"] is None

    def test_get_salon_list_without_storage_returns_200(
        self, salon_and_repo: tuple[uuid.UUID, FakeSalonRepository]
    ) -> None:
        salon_id, repo = salon_and_repo
        with _setup_manager(repo, salon_id, None) as c:
            r = c.get(
                "/salons",
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        assert r.status_code == 200
