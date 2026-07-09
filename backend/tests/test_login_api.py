"""Tests API pour `POST /auth/login` et `POST /auth/refresh` (adapter entrant, #10).

Utilise FastAPI `TestClient` avec override de `get_authenticate_user` /
`get_refresh_tokens` (ports 100 % fakes, aucune base de données réelle).

Couverture :
- `POST /auth/login` : 200 + structure de la réponse ; 401 générique (mot de
  passe faux, utilisateur inconnu, compte inactif — assertion d'indistinguabilité)
  ; 429 + `Retry-After` ; 422 sur champs manquants/vides ; 503 sans TokenService ;
  non-fuite du mot de passe dans les réponses.
- `POST /auth/refresh` : 200 + structure ; 401 sur token invalide ou expiré ;
  422 sur champ manquant ; 405 sur mauvaise méthode.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.auth import get_authenticate_user, get_refresh_tokens
from coiflink_api.application.authentication import AuthenticateUser, RefreshTokens
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import UserStatus
from coiflink_api.domain.errors import ExpiredToken, InvalidToken
from coiflink_api.main import app

from .conftest import (
    FAKE_REFRESH_CLAIMS,
    FAKE_TOKEN_PAIR,
    FakeAuthUserRepository,
    FakeHasher,
    FakeLoginRateLimiter,
    FakeTokenService,
)

_PHONE_E164 = "+2250700000000"
_EMAIL = "user@example.com"
_GOOD_PASS = "good-password"
_GOOD_HASH = FakeHasher().hash(_GOOD_PASS)
_DUMMY_HASH = FakeHasher().hash("dummy")
_UUID_STR = FAKE_REFRESH_CLAIMS.sub

_ACTIVE_CREDS = UserCredentials(
    id=__import__("uuid").UUID(_UUID_STR),
    role="CLIENT",
    status=UserStatus.ACTIVE.value,
    password_hash=_GOOD_HASH,
)
_INACTIVE_CREDS = UserCredentials(
    id=__import__("uuid").UUID(_UUID_STR),
    role="CLIENT",
    status=UserStatus.INACTIVE.value,
    password_hash=_GOOD_HASH,
)

_VALID_LOGIN_PHONE = {"identifier": "0700000000", "password": _GOOD_PASS}
_VALID_LOGIN_EMAIL = {"identifier": _EMAIL, "password": _GOOD_PASS}

# Message d'erreur 401 attendu (anti-énumération).
_GENERIC_401 = "Identifiants invalides."


def _make_auth(
    *,
    creds_by_phone: dict | None = None,
    creds_by_email: dict | None = None,
    creds_by_id: dict | None = None,
    locked: bool = False,
    retry_after: int | None = None,
) -> AuthenticateUser:
    return AuthenticateUser(
        FakeAuthUserRepository(
            credentials_by_phone=creds_by_phone or {},
            credentials_by_email=creds_by_email or {},
            credentials_by_id=creds_by_id or {},
        ),
        FakeHasher(),
        FakeTokenService(),
        FakeLoginRateLimiter(locked=locked, retry_after=retry_after),
        dummy_hash=_DUMMY_HASH,
    )


def _make_refresh(
    *,
    verify_result=None,
) -> RefreshTokens:
    ts = FakeTokenService(verify_refresh_result=verify_result)
    repo = FakeAuthUserRepository(
        credentials_by_id={
            _UUID_STR: _ACTIVE_CREDS,
        }
    )
    return RefreshTokens(repo, ts)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client_valid_phone() -> Generator[TestClient, None, None]:
    """Connexion par téléphone valide."""

    def _uc() -> AuthenticateUser:
        return _make_auth(creds_by_phone={_PHONE_E164: _ACTIVE_CREDS})

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


@pytest.fixture()
def client_valid_email() -> Generator[TestClient, None, None]:
    """Connexion par e-mail valide."""

    def _uc() -> AuthenticateUser:
        return _make_auth(creds_by_email={_EMAIL: _ACTIVE_CREDS})

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


@pytest.fixture()
def client_wrong_password() -> Generator[TestClient, None, None]:
    """Dépôt avec compte existant mais le mot de passe envoyé sera faux."""

    def _uc() -> AuthenticateUser:
        return _make_auth(creds_by_phone={_PHONE_E164: _ACTIVE_CREDS})

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


@pytest.fixture()
def client_unknown_user() -> Generator[TestClient, None, None]:
    """Dépôt vide → utilisateur inconnu."""

    def _uc() -> AuthenticateUser:
        return _make_auth()

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


@pytest.fixture()
def client_inactive_account() -> Generator[TestClient, None, None]:
    """Compte présent mais inactif."""

    def _uc() -> AuthenticateUser:
        return _make_auth(creds_by_phone={_PHONE_E164: _INACTIVE_CREDS})

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


@pytest.fixture()
def client_rate_limited() -> Generator[TestClient, None, None]:
    """Rate-limiter verrouillé, retry_after=120."""

    def _uc() -> AuthenticateUser:
        return _make_auth(locked=True, retry_after=120)

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


@pytest.fixture()
def client_no_token_service() -> Generator[TestClient, None, None]:
    """Simule l'absence de JWT_SECRET : `get_authenticate_user` lève 503."""

    def _uc() -> AuthenticateUser:
        raise HTTPException(
            status_code=503,
            detail="Service d'authentification indisponible (JWT_SECRET non configuré).",
        )

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


@pytest.fixture()
def client_refresh_valid() -> Generator[TestClient, None, None]:
    """Refresh valide → nouvelle paire."""

    def _uc() -> RefreshTokens:
        return _make_refresh()

    app.dependency_overrides[get_refresh_tokens] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_refresh_tokens, None)


@pytest.fixture()
def client_refresh_invalid() -> Generator[TestClient, None, None]:
    """Refresh invalide → lève `InvalidToken`."""

    def _uc() -> RefreshTokens:
        return _make_refresh(verify_result=InvalidToken("invalide"))

    app.dependency_overrides[get_refresh_tokens] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_refresh_tokens, None)


@pytest.fixture()
def client_refresh_expired() -> Generator[TestClient, None, None]:
    """Refresh expiré → lève `ExpiredToken`."""

    def _uc() -> RefreshTokens:
        return _make_refresh(verify_result=ExpiredToken("expiré"))

    app.dependency_overrides[get_refresh_tokens] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_refresh_tokens, None)


# ── POST /auth/login — succès ──────────────────────────────────────────────────


class TestLoginSuccess:
    def test_status_200_with_phone(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.status_code == 200

    def test_status_200_with_email(self, client_valid_email: TestClient) -> None:
        r = client_valid_email.post("/auth/login", json=_VALID_LOGIN_EMAIL)
        assert r.status_code == 200

    def test_response_contains_access_token(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert "access_token" in r.json()

    def test_response_contains_refresh_token(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert "refresh_token" in r.json()

    def test_response_contains_token_type_bearer(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.json()["token_type"] == "bearer"

    def test_response_contains_expires_in(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert "expires_in" in r.json()
        assert isinstance(r.json()["expires_in"], int)

    def test_response_matches_fake_token_pair(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        body = r.json()
        assert body["access_token"] == FAKE_TOKEN_PAIR.access_token
        assert body["refresh_token"] == FAKE_TOKEN_PAIR.refresh_token
        assert body["expires_in"] == FAKE_TOKEN_PAIR.expires_in

    def test_content_type_json(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert "application/json" in r.headers.get("content-type", "")


# ── POST /auth/login — non-fuite du mot de passe ──────────────────────────────


class TestLoginNoSecretLeak:
    def test_password_absent_from_200_response(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert _GOOD_PASS not in r.text

    def test_hash_absent_from_200_response(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert _GOOD_HASH not in r.text

    def test_password_absent_from_401_response(self, client_wrong_password: TestClient) -> None:
        r = client_wrong_password.post(
            "/auth/login", json={"identifier": "0700000000", "password": "wrong-secret"}
        )
        assert "wrong-secret" not in r.text


# ── POST /auth/login — 401 indistinguable ─────────────────────────────────────


class TestLoginIndistinguishability:
    def test_wrong_password_returns_401(self, client_wrong_password: TestClient) -> None:
        r = client_wrong_password.post(
            "/auth/login", json={"identifier": "0700000000", "password": "wrong"}
        )
        assert r.status_code == 401

    def test_wrong_password_returns_generic_detail(self, client_wrong_password: TestClient) -> None:
        r = client_wrong_password.post(
            "/auth/login", json={"identifier": "0700000000", "password": "wrong"}
        )
        assert r.json()["detail"] == _GENERIC_401

    def test_unknown_user_returns_401(self, client_unknown_user: TestClient) -> None:
        r = client_unknown_user.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.status_code == 401

    def test_unknown_user_returns_same_generic_detail(
        self, client_unknown_user: TestClient
    ) -> None:
        r = client_unknown_user.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.json()["detail"] == _GENERIC_401

    def test_inactive_account_returns_401(self, client_inactive_account: TestClient) -> None:
        r = client_inactive_account.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.status_code == 401

    def test_inactive_account_returns_same_generic_detail(
        self, client_inactive_account: TestClient
    ) -> None:
        r = client_inactive_account.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.json()["detail"] == _GENERIC_401


# ── POST /auth/login — 429 rate-limit ─────────────────────────────────────────


class TestLoginRateLimit:
    def test_rate_limited_returns_429(self, client_rate_limited: TestClient) -> None:
        r = client_rate_limited.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.status_code == 429

    def test_rate_limited_includes_retry_after_header(
        self, client_rate_limited: TestClient
    ) -> None:
        r = client_rate_limited.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert "Retry-After" in r.headers

    def test_rate_limited_retry_after_value(self, client_rate_limited: TestClient) -> None:
        r = client_rate_limited.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.headers["Retry-After"] == "120"


# ── POST /auth/login — 503 sans TokenService ──────────────────────────────────


class TestLoginServiceUnavailable:
    def test_no_token_service_returns_503(self, client_no_token_service: TestClient) -> None:
        r = client_no_token_service.post("/auth/login", json=_VALID_LOGIN_PHONE)
        assert r.status_code == 503


# ── POST /auth/login — 422 validation Pydantic ────────────────────────────────


class TestLoginPydanticValidation:
    def test_missing_identifier_returns_422(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json={"password": _GOOD_PASS})
        assert r.status_code == 422

    def test_missing_password_returns_422(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json={"identifier": "0700000000"})
        assert r.status_code == 422

    def test_empty_identifier_returns_422(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post(
            "/auth/login", json={"identifier": "", "password": _GOOD_PASS}
        )
        assert r.status_code == 422

    def test_empty_password_returns_422(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post(
            "/auth/login", json={"identifier": "0700000000", "password": ""}
        )
        assert r.status_code == 422

    def test_empty_body_returns_422(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.post("/auth/login", json={})
        assert r.status_code == 422


# ── POST /auth/login — méthode HTTP ───────────────────────────────────────────


class TestLoginHttpMethod:
    def test_get_returns_405(self, client_valid_phone: TestClient) -> None:
        r = client_valid_phone.get("/auth/login")
        assert r.status_code == 405


# ── POST /auth/refresh — succès ───────────────────────────────────────────────


class TestRefreshSuccess:
    def test_status_200(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.post(
            "/auth/refresh", json={"refresh_token": "some-valid-refresh"}
        )
        assert r.status_code == 200

    def test_response_contains_access_token(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.post(
            "/auth/refresh", json={"refresh_token": "some-valid-refresh"}
        )
        assert "access_token" in r.json()

    def test_response_contains_refresh_token(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.post(
            "/auth/refresh", json={"refresh_token": "some-valid-refresh"}
        )
        assert "refresh_token" in r.json()

    def test_response_contains_token_type_bearer(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.post(
            "/auth/refresh", json={"refresh_token": "some-valid-refresh"}
        )
        assert r.json()["token_type"] == "bearer"

    def test_response_contains_expires_in(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.post(
            "/auth/refresh", json={"refresh_token": "some-valid-refresh"}
        )
        assert "expires_in" in r.json()


# ── POST /auth/refresh — 401 ──────────────────────────────────────────────────


class TestRefreshInvalid:
    def test_invalid_token_returns_401(self, client_refresh_invalid: TestClient) -> None:
        r = client_refresh_invalid.post(
            "/auth/refresh", json={"refresh_token": "bad-token"}
        )
        assert r.status_code == 401

    def test_expired_token_returns_401(self, client_refresh_expired: TestClient) -> None:
        r = client_refresh_expired.post(
            "/auth/refresh", json={"refresh_token": "expired-token"}
        )
        assert r.status_code == 401

    def test_401_detail_is_generic(self, client_refresh_invalid: TestClient) -> None:
        r = client_refresh_invalid.post(
            "/auth/refresh", json={"refresh_token": "bad-token"}
        )
        assert r.json()["detail"]  # message présent (non vide)


# ── POST /auth/refresh — 422 ──────────────────────────────────────────────────


class TestRefreshPydanticValidation:
    def test_missing_refresh_token_returns_422(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.post("/auth/refresh", json={})
        assert r.status_code == 422

    def test_empty_refresh_token_returns_422(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.post("/auth/refresh", json={"refresh_token": ""})
        assert r.status_code == 422


# ── POST /auth/refresh — méthode HTTP ─────────────────────────────────────────


class TestRefreshHttpMethod:
    def test_get_returns_405(self, client_refresh_valid: TestClient) -> None:
        r = client_refresh_valid.get("/auth/refresh")
        assert r.status_code == 405
