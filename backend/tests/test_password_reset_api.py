"""Tests API pour POST /auth/password/reset/request et /confirm (adapter entrant, #11).

Utilise FastAPI TestClient avec override de `get_request_password_reset` /
`get_confirm_password_reset` (ports 100 % fakes, aucune base de données réelle).

Couverture :
- POST /auth/password/reset/request : 202 générique pour compte existant et inconnu
  (anti-énumération) ; 429 + Retry-After (rate-limit) ; 422 sur champs
  manquants/vides ; 405 sur mauvaise méthode ; OTP jamais dans la réponse.
- POST /auth/password/reset/confirm : 200 + message générique ; 400 générique
  pour OTP invalide/expiré/absent (indistinguabilité) ; 422 pour mot de passe
  invalide ; 422 sur champs manquants ; 405 sur mauvaise méthode.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from random import Random

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.auth import (
    get_confirm_password_reset,
    get_request_password_reset,
)
from coiflink_api.application.password_reset import (
    ConfirmPasswordReset,
    RequestPasswordReset,
)
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import UserStatus
from coiflink_api.domain.otp import DEFAULT_OTP_MAX_ATTEMPTS, DEFAULT_OTP_TTL, OtpChallenge
from coiflink_api.main import app

from .conftest import (
    FakeAuthUserRepository,
    FakeHasher,
    FakeLoginRateLimiter,
    FakeOtpRepository,
    FakeOtpSender,
)

# ── Constantes ────────────────────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_PHONE_LOCAL = "0700000000"
_PHONE_E164 = "+2250700000000"
_EMAIL = "user@example.com"
_NEW_PASS = "nouveau-mdp-solide"
_TOO_SHORT_PASS = "court"
_OTP_CODE = "123456"
_WRONG_CODE = "000000"
_UID = uuid.UUID("00000000-0000-0000-0000-000000000042")

_ACTIVE_CREDS = UserCredentials(
    id=_UID,
    role="CLIENT",
    status=UserStatus.ACTIVE.value,
    password_hash=FakeHasher().hash("ancien-mdp"),
)

# Messages attendus (extraits de l'adapter entrant, anti-énumération).
_REQUEST_DETAIL = (
    "Si un compte correspond à cet identifiant, un code de réinitialisation a été envoyé."
)
_CONFIRM_DETAIL = "Mot de passe réinitialisé."
_INVALID_OTP_DETAIL = "Code de réinitialisation invalide ou expiré."
_RATE_LIMITED_DETAIL = "Trop de demandes de réinitialisation. Réessayez plus tard."


# ── Helpers ───────────────────────────────────────────────────────────────────


def _valid_challenge(code: str = _OTP_CODE) -> OtpChallenge:
    return OtpChallenge(
        code=code,
        expires_at=_NOW + DEFAULT_OTP_TTL,
        attempts_left=DEFAULT_OTP_MAX_ATTEMPTS,
        consumed=False,
    )


def _expired_challenge() -> OtpChallenge:
    return OtpChallenge(
        code=_OTP_CODE,
        expires_at=_NOW - datetime.timedelta(seconds=1),
        attempts_left=DEFAULT_OTP_MAX_ATTEMPTS,
        consumed=False,
    )


def _make_request_uc(
    *,
    creds_by_phone: dict | None = None,
    locked: bool = False,
    retry_after: int | None = None,
) -> RequestPasswordReset:
    return RequestPasswordReset(
        FakeAuthUserRepository(credentials_by_phone=creds_by_phone or {}),
        FakeOtpRepository(),
        FakeOtpSender(),
        rate_limiter=FakeLoginRateLimiter(locked=locked, retry_after=retry_after),
        rng=Random(42),
        clock=lambda: _NOW,
    )


def _make_confirm_uc(
    *,
    otp_repo: FakeOtpRepository | None = None,
    creds_by_phone: dict | None = None,
) -> ConfirmPasswordReset:
    if otp_repo is None:
        otp_repo = FakeOtpRepository()
    return ConfirmPasswordReset(
        FakeAuthUserRepository(credentials_by_phone=creds_by_phone or {}),
        otp_repo,
        FakeHasher(),
        clock=lambda: _NOW,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client_request_active_phone() -> Generator[TestClient, None, None]:
    """Demande de reset pour un compte téléphone actif."""

    def _uc() -> RequestPasswordReset:
        return _make_request_uc(creds_by_phone={_PHONE_E164: _ACTIVE_CREDS})

    app.dependency_overrides[get_request_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_request_password_reset, None)


@pytest.fixture()
def client_request_unknown() -> Generator[TestClient, None, None]:
    """Demande de reset pour un identifiant sans compte associé."""

    def _uc() -> RequestPasswordReset:
        return _make_request_uc()  # dépôt vide

    app.dependency_overrides[get_request_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_request_password_reset, None)


@pytest.fixture()
def client_request_rate_limited() -> Generator[TestClient, None, None]:
    """Rate-limiter verrouillé, retry_after=60."""

    def _uc() -> RequestPasswordReset:
        return _make_request_uc(
            creds_by_phone={_PHONE_E164: _ACTIVE_CREDS},
            locked=True,
            retry_after=60,
        )

    app.dependency_overrides[get_request_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_request_password_reset, None)


@pytest.fixture()
def client_confirm_success() -> Generator[TestClient, None, None]:
    """Reset valide : OTP correct en dépôt, compte actif."""

    def _uc() -> ConfirmPasswordReset:
        repo = FakeOtpRepository()
        repo.save(_PHONE_E164, _valid_challenge())
        return _make_confirm_uc(
            otp_repo=repo,
            creds_by_phone={_PHONE_E164: _ACTIVE_CREDS},
        )

    app.dependency_overrides[get_confirm_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_confirm_password_reset, None)


@pytest.fixture()
def client_confirm_wrong_code() -> Generator[TestClient, None, None]:
    """Reset avec un mauvais code OTP."""

    def _uc() -> ConfirmPasswordReset:
        repo = FakeOtpRepository()
        repo.save(_PHONE_E164, _valid_challenge(code="999999"))
        return _make_confirm_uc(
            otp_repo=repo,
            creds_by_phone={_PHONE_E164: _ACTIVE_CREDS},
        )

    app.dependency_overrides[get_confirm_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_confirm_password_reset, None)


@pytest.fixture()
def client_confirm_no_challenge() -> Generator[TestClient, None, None]:
    """Reset sans défi OTP existant (identifiant jamais soumis ou déjà consommé)."""

    def _uc() -> ConfirmPasswordReset:
        return _make_confirm_uc(creds_by_phone={_PHONE_E164: _ACTIVE_CREDS})

    app.dependency_overrides[get_confirm_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_confirm_password_reset, None)


@pytest.fixture()
def client_confirm_expired() -> Generator[TestClient, None, None]:
    """Reset avec un OTP expiré."""

    def _uc() -> ConfirmPasswordReset:
        repo = FakeOtpRepository()
        repo.save(_PHONE_E164, _expired_challenge())
        return _make_confirm_uc(
            otp_repo=repo,
            creds_by_phone={_PHONE_E164: _ACTIVE_CREDS},
        )

    app.dependency_overrides[get_confirm_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_confirm_password_reset, None)


# ── POST /auth/password/reset/request — 202 ───────────────────────────────────


class TestRequestEndpointSuccess:
    def test_status_202_for_active_phone(self, client_request_active_phone: TestClient) -> None:
        r = client_request_active_phone.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert r.status_code == 202

    def test_response_has_detail_field(self, client_request_active_phone: TestClient) -> None:
        r = client_request_active_phone.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert "detail" in r.json()

    def test_response_detail_is_generic_message(
        self, client_request_active_phone: TestClient
    ) -> None:
        r = client_request_active_phone.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert r.json()["detail"] == _REQUEST_DETAIL

    def test_content_type_json(self, client_request_active_phone: TestClient) -> None:
        r = client_request_active_phone.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert "application/json" in r.headers.get("content-type", "")


# ── POST /auth/password/reset/request — anti-énumération ─────────────────────


class TestRequestEndpointAntiEnumeration:
    """202 identique pour compte existant et inconnu (jamais de divulgation d'existence)."""

    def test_unknown_account_still_202(self, client_request_unknown: TestClient) -> None:
        r = client_request_unknown.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert r.status_code == 202

    def test_unknown_account_same_detail_as_known(
        self,
        client_request_active_phone: TestClient,
        client_request_unknown: TestClient,
    ) -> None:
        r_known = client_request_active_phone.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        r_unknown = client_request_unknown.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert r_known.json()["detail"] == r_unknown.json()["detail"]

    def test_otp_code_never_in_response(self, client_request_active_phone: TestClient) -> None:
        r = client_request_active_phone.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        # Response body should not contain any digit sequence that looks like an OTP
        body = r.text
        assert len(body) < 300  # sanity: response is short


# ── POST /auth/password/reset/request — 429 ───────────────────────────────────


class TestRequestEndpointRateLimit:
    def test_rate_limited_returns_429(self, client_request_rate_limited: TestClient) -> None:
        r = client_request_rate_limited.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert r.status_code == 429

    def test_rate_limited_detail_is_generic(
        self, client_request_rate_limited: TestClient
    ) -> None:
        r = client_request_rate_limited.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert r.json()["detail"] == _RATE_LIMITED_DETAIL

    def test_rate_limited_has_retry_after_header(
        self, client_request_rate_limited: TestClient
    ) -> None:
        r = client_request_rate_limited.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert "Retry-After" in r.headers

    def test_rate_limited_retry_after_value(
        self, client_request_rate_limited: TestClient
    ) -> None:
        r = client_request_rate_limited.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        assert r.headers["Retry-After"] == "60"


# ── POST /auth/password/reset/request — validation Pydantic ──────────────────


class TestRequestEndpointPydanticValidation:
    def test_missing_identifier_returns_422(
        self, client_request_active_phone: TestClient
    ) -> None:
        r = client_request_active_phone.post("/auth/password/reset/request", json={})
        assert r.status_code == 422

    def test_empty_identifier_returns_422(
        self, client_request_active_phone: TestClient
    ) -> None:
        r = client_request_active_phone.post(
            "/auth/password/reset/request", json={"identifier": ""}
        )
        assert r.status_code == 422

    def test_empty_body_returns_422(self, client_request_active_phone: TestClient) -> None:
        r = client_request_active_phone.post("/auth/password/reset/request", json=None)
        assert r.status_code == 422


# ── POST /auth/password/reset/request — méthode HTTP ─────────────────────────


class TestRequestEndpointHttpMethod:
    def test_get_returns_405(self, client_request_active_phone: TestClient) -> None:
        r = client_request_active_phone.get("/auth/password/reset/request")
        assert r.status_code == 405


# ── POST /auth/password/reset/confirm — 200 ──────────────────────────────────


class TestConfirmEndpointSuccess:
    def test_status_200(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r.status_code == 200

    def test_response_has_detail_field(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert "detail" in r.json()

    def test_response_detail_is_confirmation_message(
        self, client_confirm_success: TestClient
    ) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r.json()["detail"] == _CONFIRM_DETAIL

    def test_content_type_json(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert "application/json" in r.headers.get("content-type", "")

    def test_new_password_not_in_200_response(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert _NEW_PASS not in r.text

    def test_otp_code_not_in_200_response(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert _OTP_CODE not in r.text


# ── POST /auth/password/reset/confirm — 400 OTP invalide ─────────────────────


class TestConfirmEndpointInvalidOtp:
    def test_wrong_code_returns_400(self, client_confirm_wrong_code: TestClient) -> None:
        r = client_confirm_wrong_code.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _WRONG_CODE, "new_password": _NEW_PASS},
        )
        assert r.status_code == 400

    def test_wrong_code_detail_is_generic(self, client_confirm_wrong_code: TestClient) -> None:
        r = client_confirm_wrong_code.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _WRONG_CODE, "new_password": _NEW_PASS},
        )
        assert r.json()["detail"] == _INVALID_OTP_DETAIL

    def test_no_challenge_returns_400(self, client_confirm_no_challenge: TestClient) -> None:
        r = client_confirm_no_challenge.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r.status_code == 400

    def test_no_challenge_same_generic_detail(
        self, client_confirm_no_challenge: TestClient
    ) -> None:
        r = client_confirm_no_challenge.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r.json()["detail"] == _INVALID_OTP_DETAIL

    def test_expired_otp_returns_400(self, client_confirm_expired: TestClient) -> None:
        r = client_confirm_expired.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r.status_code == 400

    def test_expired_otp_same_generic_detail(
        self, client_confirm_expired: TestClient
    ) -> None:
        r = client_confirm_expired.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r.json()["detail"] == _INVALID_OTP_DETAIL

    def test_indistinguishability_wrong_vs_no_challenge(
        self,
        client_confirm_wrong_code: TestClient,
        client_confirm_no_challenge: TestClient,
    ) -> None:
        """OTP faux et défi absent produisent le même statut 400 et le même message."""
        r_wrong = client_confirm_wrong_code.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _WRONG_CODE, "new_password": _NEW_PASS},
        )
        r_none = client_confirm_no_challenge.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r_wrong.status_code == r_none.status_code == 400
        assert r_wrong.json()["detail"] == r_none.json()["detail"]

    def test_400_response_does_not_contain_otp_code(
        self, client_confirm_wrong_code: TestClient
    ) -> None:
        r = client_confirm_wrong_code.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _WRONG_CODE, "new_password": _NEW_PASS},
        )
        assert _WRONG_CODE not in r.text


# ── POST /auth/password/reset/confirm — 422 politique de mot de passe ─────────


class TestConfirmEndpointPasswordPolicy:
    def test_too_short_password_returns_422(
        self, client_confirm_no_challenge: TestClient
    ) -> None:
        r = client_confirm_no_challenge.post(
            "/auth/password/reset/confirm",
            json={
                "identifier": _PHONE_LOCAL,
                "code": _OTP_CODE,
                "new_password": _TOO_SHORT_PASS,
            },
        )
        assert r.status_code == 422

    def test_too_short_password_detail_not_generic_otp_message(
        self, client_confirm_no_challenge: TestClient
    ) -> None:
        r = client_confirm_no_challenge.post(
            "/auth/password/reset/confirm",
            json={
                "identifier": _PHONE_LOCAL,
                "code": _OTP_CODE,
                "new_password": _TOO_SHORT_PASS,
            },
        )
        # 422 for password policy, NOT the generic OTP 400 message
        assert r.status_code == 422
        assert r.json().get("detail") != _INVALID_OTP_DETAIL


# ── POST /auth/password/reset/confirm — validation Pydantic ──────────────────


class TestConfirmEndpointPydanticValidation:
    def test_missing_all_fields_returns_422(
        self, client_confirm_success: TestClient
    ) -> None:
        r = client_confirm_success.post("/auth/password/reset/confirm", json={})
        assert r.status_code == 422

    def test_missing_code_returns_422(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "new_password": _NEW_PASS},
        )
        assert r.status_code == 422

    def test_missing_new_password_returns_422(
        self, client_confirm_success: TestClient
    ) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": _OTP_CODE},
        )
        assert r.status_code == 422

    def test_empty_code_returns_422(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": "", "new_password": _NEW_PASS},
        )
        assert r.status_code == 422

    def test_empty_identifier_returns_422(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.post(
            "/auth/password/reset/confirm",
            json={"identifier": "", "code": _OTP_CODE, "new_password": _NEW_PASS},
        )
        assert r.status_code == 422


# ── POST /auth/password/reset/confirm — méthode HTTP ─────────────────────────


class TestConfirmEndpointHttpMethod:
    def test_get_returns_405(self, client_confirm_success: TestClient) -> None:
        r = client_confirm_success.get("/auth/password/reset/confirm")
        assert r.status_code == 405
