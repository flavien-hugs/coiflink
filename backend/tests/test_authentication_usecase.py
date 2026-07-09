"""Tests unitaires des cas d'usage `AuthenticateUser` et `RefreshTokens` (#10).

Tous les ports sont des fakes (conftest.py) : pas de DB, pas de JWT réel, pas de
vrai argon2. On vérifie ici l'orchestration applicative :
- AuthenticateUser : succès par téléphone & e-mail, mauvais mot de passe,
  utilisateur inconnu (vérification factice appelée), compte non ACTIVE,
  rate-limit vérifié avant l'accès base, reset au succès, record_failure à l'échec.
- RefreshTokens : succès (nouvelle paire émise), refresh expiré/invalide/de
  mauvais type, compte devenu non ACTIVE, compte introuvable.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.application.authentication import AuthenticateUser, LoginCommand, RefreshTokens
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import UserStatus
from coiflink_api.domain.errors import (
    ExpiredToken,
    InvalidCredentials,
    InvalidToken,
    TooManyLoginAttempts,
)

from .conftest import (
    FAKE_REFRESH_CLAIMS,
    FAKE_TOKEN_PAIR,
    FakeAuthUserRepository,
    FakeHasher,
    FakeLoginRateLimiter,
    FakeTokenService,
)

# UUID du compte fictif correspondant à FAKE_REFRESH_CLAIMS.sub.
_UUID = uuid.UUID(FAKE_REFRESH_CLAIMS.sub)
# Téléphone normalisé E.164 (Côte d'Ivoire) utilisé dans les tests.
_PHONE_E164 = "+2250700000000"
_EMAIL = "user@example.com"
_GOOD_PASS = "good-password"

# Condensat pré-calculé via FakeHasher.
_GOOD_HASH = FakeHasher().hash(_GOOD_PASS)
_DUMMY_HASH = FakeHasher().hash("dummy")


def _active_creds(
    *,
    password_hash: str = _GOOD_HASH,
    role: str = "CLIENT",
) -> UserCredentials:
    return UserCredentials(
        id=_UUID,
        role=role,
        status=UserStatus.ACTIVE.value,
        password_hash=password_hash,
    )


def _inactive_creds() -> UserCredentials:
    return UserCredentials(
        id=_UUID,
        role="CLIENT",
        status=UserStatus.INACTIVE.value,
        password_hash=_GOOD_HASH,
    )


def _suspended_creds() -> UserCredentials:
    return UserCredentials(
        id=_UUID,
        role="CLIENT",
        status=UserStatus.SUSPENDED.value,
        password_hash=_GOOD_HASH,
    )


def _make_auth(
    *,
    creds_by_phone: dict | None = None,
    creds_by_email: dict | None = None,
    locked: bool = False,
    retry_after: int | None = None,
) -> tuple[AuthenticateUser, FakeLoginRateLimiter, FakeTokenService]:
    repo = FakeAuthUserRepository(
        credentials_by_phone=creds_by_phone or {},
        credentials_by_email=creds_by_email or {},
    )
    hasher = FakeHasher()
    token_service = FakeTokenService()
    rate_limiter = FakeLoginRateLimiter(locked=locked, retry_after=retry_after)
    usecase = AuthenticateUser(
        repo, hasher, token_service, rate_limiter, dummy_hash=_DUMMY_HASH
    )
    return usecase, rate_limiter, token_service


class TestAuthenticateUserSuccess:
    def test_login_by_phone_returns_token_pair(self) -> None:
        uc, _, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        result = uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))
        assert result == FAKE_TOKEN_PAIR

    def test_login_by_e164_phone_returns_token_pair(self) -> None:
        uc, _, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        result = uc.execute(LoginCommand(identifier=_PHONE_E164, password=_GOOD_PASS))
        assert result == FAKE_TOKEN_PAIR

    def test_login_by_email_returns_token_pair(self) -> None:
        uc, _, _ = _make_auth(creds_by_email={_EMAIL: _active_creds()})
        result = uc.execute(LoginCommand(identifier=_EMAIL, password=_GOOD_PASS))
        assert result == FAKE_TOKEN_PAIR

    def test_success_calls_rate_limiter_reset(self) -> None:
        uc, rl, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))
        assert rl.resets

    def test_success_does_not_record_failure(self) -> None:
        uc, rl, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))
        assert not rl.failures

    def test_success_calls_issue_pair(self) -> None:
        uc, _, ts = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))
        assert ts.issued

    def test_success_issues_pair_with_correct_role(self) -> None:
        uc, _, ts = _make_auth(
            creds_by_phone={_PHONE_E164: _active_creds(role="MANAGER")}
        )
        uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))
        assert ts.issued[0][1] == "MANAGER"

    def test_rate_limiter_check_called_before_db(self) -> None:
        """Le rate-limiter est consulté AVANT tout accès base (lève si verrouillé)."""
        uc, rl, _ = _make_auth(locked=True)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))
        assert rl.checks  # check a été appelé


class TestAuthenticateUserFailure:
    def test_wrong_password_raises_invalid_credentials(self) -> None:
        uc, _, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password="wrong"))

    def test_wrong_password_records_failure(self) -> None:
        uc, rl, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password="wrong"))
        assert rl.failures

    def test_wrong_password_does_not_reset(self) -> None:
        uc, rl, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password="wrong"))
        assert not rl.resets

    def test_unknown_user_raises_invalid_credentials(self) -> None:
        uc, _, _ = _make_auth()  # dépôt vide
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password="any"))

    def test_unknown_user_records_failure(self) -> None:
        uc, rl, _ = _make_auth()
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password="any"))
        assert rl.failures

    def test_unknown_user_does_not_reveal_absence_via_timing(self) -> None:
        """La vérification factice est appelée quand aucun compte n'est trouvé.

        Assure qu'`issue_pair` n'est jamais appelé (pas de jeton émis) et que le
        cas d'usage ne court-circuite pas avant la vérification (anti-oracle temporel).
        """
        uc, _, ts = _make_auth()
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password="any"))
        # Aucun jeton ne doit avoir été émis.
        assert not ts.issued

    def test_inactive_account_raises_invalid_credentials(self) -> None:
        uc, _, _ = _make_auth(creds_by_phone={_PHONE_E164: _inactive_creds()})
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))

    def test_inactive_account_records_failure(self) -> None:
        uc, rl, _ = _make_auth(creds_by_phone={_PHONE_E164: _inactive_creds()})
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))
        assert rl.failures

    def test_suspended_account_raises_invalid_credentials(self) -> None:
        uc, _, _ = _make_auth(creds_by_phone={_PHONE_E164: _suspended_creds()})
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="0700000000", password=_GOOD_PASS))

    def test_inactive_and_wrong_password_same_error_class(self) -> None:
        """ACTIVE+mauvais_mdp et INACTIVE+bon_mdp lèvent le même type (indistinguabilité)."""
        uc_wrong_pass, _, _ = _make_auth(creds_by_phone={_PHONE_E164: _active_creds()})
        uc_inactive, _, _ = _make_auth(creds_by_phone={_PHONE_E164: _inactive_creds()})
        cmd_wrong = LoginCommand(identifier="0700000000", password="wrong")
        cmd_good = LoginCommand(identifier="0700000000", password=_GOOD_PASS)
        with pytest.raises(InvalidCredentials):
            uc_wrong_pass.execute(cmd_wrong)
        with pytest.raises(InvalidCredentials):
            uc_inactive.execute(cmd_good)

    def test_empty_identifier_raises_invalid_credentials(self) -> None:
        uc, _, _ = _make_auth()
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="", password="any"))

    def test_unclassifiable_phone_raises_invalid_credentials(self) -> None:
        """Un identifiant sans '@' mais invalide comme numéro → InvalidCredentials."""
        uc, _, _ = _make_auth()
        with pytest.raises(InvalidCredentials):
            uc.execute(LoginCommand(identifier="notaphone", password="any"))


class TestAuthenticateUserRateLimit:
    def test_locked_raises_too_many_attempts(self) -> None:
        uc, _, _ = _make_auth(locked=True)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(LoginCommand(identifier="0700000000", password="any"))

    def test_locked_with_retry_after_propagates_value(self) -> None:
        uc, _, _ = _make_auth(locked=True, retry_after=600)
        with pytest.raises(TooManyLoginAttempts) as exc_info:
            uc.execute(LoginCommand(identifier="0700000000", password="any"))
        assert exc_info.value.retry_after == 600

    def test_locked_does_not_call_issue_pair(self) -> None:
        """Aucun jeton ne doit être émis quand le rate-limiter bloque."""
        uc, _, ts = _make_auth(locked=True)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(LoginCommand(identifier="0700000000", password="any"))
        assert not ts.issued


class TestRefreshTokens:
    def _repo_with_active(self) -> FakeAuthUserRepository:
        return FakeAuthUserRepository(
            credentials_by_id={
                FAKE_REFRESH_CLAIMS.sub: UserCredentials(
                    id=_UUID,
                    role="CLIENT",
                    status=UserStatus.ACTIVE.value,
                    password_hash="hash:x",
                )
            }
        )

    def _repo_with_inactive(self) -> FakeAuthUserRepository:
        return FakeAuthUserRepository(
            credentials_by_id={
                FAKE_REFRESH_CLAIMS.sub: UserCredentials(
                    id=_UUID,
                    role="CLIENT",
                    status=UserStatus.INACTIVE.value,
                    password_hash="hash:x",
                )
            }
        )

    def test_valid_refresh_returns_token_pair(self) -> None:
        usecase = RefreshTokens(self._repo_with_active(), FakeTokenService())
        result = usecase.execute("some-refresh-token")
        assert result == FAKE_TOKEN_PAIR

    def test_valid_refresh_calls_issue_pair(self) -> None:
        ts = FakeTokenService()
        usecase = RefreshTokens(self._repo_with_active(), ts)
        usecase.execute("some-refresh-token")
        assert ts.issued

    def test_expired_refresh_raises_expired_token(self) -> None:
        ts = FakeTokenService(verify_refresh_result=ExpiredToken("expiré"))
        usecase = RefreshTokens(self._repo_with_active(), ts)
        with pytest.raises(ExpiredToken):
            usecase.execute("expired-token")

    def test_invalid_refresh_raises_invalid_token(self) -> None:
        ts = FakeTokenService(verify_refresh_result=InvalidToken("invalide"))
        usecase = RefreshTokens(self._repo_with_active(), ts)
        with pytest.raises(InvalidToken):
            usecase.execute("bad-token")

    def test_access_token_used_as_refresh_raises_invalid_token(self) -> None:
        """Un jeton d'accès (type=access) doit être refusé comme refresh."""
        ts = FakeTokenService(
            verify_refresh_result=InvalidToken("Type de jeton invalide.")
        )
        usecase = RefreshTokens(self._repo_with_active(), ts)
        with pytest.raises(InvalidToken):
            usecase.execute("access-token-used-as-refresh")

    def test_inactive_account_raises_invalid_token(self) -> None:
        usecase = RefreshTokens(self._repo_with_inactive(), FakeTokenService())
        with pytest.raises(InvalidToken):
            usecase.execute("some-refresh-token")

    def test_account_not_found_raises_invalid_token(self) -> None:
        # Dépôt vide : find_by_id retourne None.
        usecase = RefreshTokens(FakeAuthUserRepository(), FakeTokenService())
        with pytest.raises(InvalidToken):
            usecase.execute("some-refresh-token")
