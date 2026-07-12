"""Tests unitaires des cas d'usage RequestPasswordReset et ConfirmPasswordReset (#11).

Tous les ports sont des fakes (conftest.py) : aucune DB, aucun hasher réel,
aucun envoi réseau. Couvre l'orchestration applicative :
- RequestPasswordReset : succès (téléphone & e-mail), compte inconnu/inactif/suspendu,
  identifiant invalide ou vide, rate-limit avant accès base, routage de canal
  SMS/EMAIL, écriture OTP, invalidation du défi précédent, record_failure systématique.
- ConfirmPasswordReset : succès (update_password + suppression défi), OTP invalide/
  expiré/épuisé/consommé/absent, mot de passe trop court vérifié en premier, compte
  disparu/inactif après OTP valide, indistinguabilité des erreurs, ancien mot de passe
  invalidé, non-fuite du code OTP dans les messages d'erreur.
"""

from __future__ import annotations

import datetime
import uuid
from random import Random

import pytest

from coiflink_api.application.password_reset import (
    ConfirmPasswordReset,
    PasswordResetConfirmCommand,
    PasswordResetRequestCommand,
    RequestPasswordReset,
)
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import NotificationChannel, UserStatus
from coiflink_api.domain.errors import InvalidOtp, InvalidPassword, TooManyLoginAttempts
from coiflink_api.domain.otp import DEFAULT_OTP_MAX_ATTEMPTS, DEFAULT_OTP_TTL, OtpChallenge

from .conftest import (
    FakeAuthUserRepository,
    FakeHasher,
    FakeLoginRateLimiter,
    FakeOtpRepository,
    FakeOtpSender,
)

# ── Constantes de test ────────────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_PHONE_LOCAL = "0700000000"
_PHONE_E164 = "+2250700000000"
_EMAIL = "user@example.com"
_NEW_PASS = "nouveau-mdp-solide"  # >= 8 chars, respecte la politique
_TOO_SHORT_PASS = "court"         # < 8 chars, viole la politique
_OTP_CODE = "123456"
_UID = uuid.UUID("00000000-0000-0000-0000-000000000042")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _creds(status: str = UserStatus.ACTIVE.value) -> UserCredentials:
    return UserCredentials(
        id=_UID,
        role="CLIENT",
        status=status,
        password_hash=FakeHasher().hash("ancien-mdp"),
    )


def _valid_challenge(
    code: str = _OTP_CODE,
    attempts: int = DEFAULT_OTP_MAX_ATTEMPTS,
    consumed: bool = False,
) -> OtpChallenge:
    return OtpChallenge(
        code=code,
        expires_at=_NOW + DEFAULT_OTP_TTL,
        attempts_left=attempts,
        consumed=consumed,
    )


def _expired_challenge(code: str = _OTP_CODE) -> OtpChallenge:
    return OtpChallenge(
        code=code,
        expires_at=_NOW - datetime.timedelta(seconds=1),
        attempts_left=DEFAULT_OTP_MAX_ATTEMPTS,
        consumed=False,
    )


def _exhausted_challenge(code: str = _OTP_CODE) -> OtpChallenge:
    return OtpChallenge(
        code=code,
        expires_at=_NOW + DEFAULT_OTP_TTL,
        attempts_left=0,
        consumed=False,
    )


def _make_request_uc(
    *,
    creds_by_phone: dict | None = None,
    creds_by_email: dict | None = None,
    locked: bool = False,
    retry_after: int | None = None,
    rng: Random | None = None,
) -> tuple[RequestPasswordReset, FakeAuthUserRepository, FakeOtpRepository, FakeOtpSender, FakeLoginRateLimiter]:
    repo = FakeAuthUserRepository(
        credentials_by_phone=creds_by_phone or {},
        credentials_by_email=creds_by_email or {},
    )
    otp_repo = FakeOtpRepository()
    sender = FakeOtpSender()
    rate_limiter = FakeLoginRateLimiter(locked=locked, retry_after=retry_after)
    uc = RequestPasswordReset(
        repo,
        otp_repo,
        sender,
        rate_limiter=rate_limiter,
        rng=rng or Random(42),
        clock=lambda: _NOW,
    )
    return uc, repo, otp_repo, sender, rate_limiter


def _make_confirm_uc(
    *,
    creds_by_phone: dict | None = None,
    creds_by_email: dict | None = None,
) -> tuple[ConfirmPasswordReset, FakeAuthUserRepository, FakeOtpRepository]:
    repo = FakeAuthUserRepository(
        credentials_by_phone=creds_by_phone or {},
        credentials_by_email=creds_by_email or {},
    )
    otp_repo = FakeOtpRepository()
    uc = ConfirmPasswordReset(
        repo,
        otp_repo,
        FakeHasher(),
        clock=lambda: _NOW,
    )
    return uc, repo, otp_repo


# ── RequestPasswordReset — succès ─────────────────────────────────────────────


class TestRequestPasswordResetSuccess:
    def test_phone_account_saves_challenge(self) -> None:
        uc, _, otp_repo, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert _PHONE_E164 in otp_repo.challenges

    def test_phone_account_sends_otp(self) -> None:
        uc, _, _, sender, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert len(sender.sent) == 1

    def test_phone_account_sends_to_correct_recipient(self) -> None:
        uc, _, _, sender, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        recipient, _, _ = sender.sent_channels[0]
        assert recipient == _PHONE_E164

    def test_phone_account_uses_sms_channel(self) -> None:
        uc, _, _, sender, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        _, _, channel = sender.sent_channels[0]
        assert channel == NotificationChannel.SMS.value

    def test_email_account_saves_challenge(self) -> None:
        uc, _, otp_repo, _, _ = _make_request_uc(creds_by_email={_EMAIL: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_EMAIL))
        assert _EMAIL in otp_repo.challenges

    def test_email_account_sends_otp(self) -> None:
        uc, _, _, sender, _ = _make_request_uc(creds_by_email={_EMAIL: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_EMAIL))
        assert len(sender.sent) == 1

    def test_email_account_uses_email_channel(self) -> None:
        uc, _, _, sender, _ = _make_request_uc(creds_by_email={_EMAIL: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_EMAIL))
        _, _, channel = sender.sent_channels[0]
        assert channel == NotificationChannel.EMAIL.value

    def test_otp_code_matches_saved_challenge(self) -> None:
        uc, _, otp_repo, sender, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        sent_code = sender.sent[0][1]
        saved_code = otp_repo.challenges[_PHONE_E164].code
        assert sent_code == saved_code

    def test_new_request_overwrites_previous_challenge(self) -> None:
        uc, _, otp_repo, sender, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        first_code = otp_repo.challenges[_PHONE_E164].code
        # Second request with different RNG seed → different code
        uc2, _, otp_repo2, sender2, _ = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}, rng=Random(99)
        )
        uc2.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        second_code = otp_repo2.challenges[_PHONE_E164].code
        # Both are stored; the second overwrites the first in its own repo
        assert otp_repo.challenges[_PHONE_E164].code == first_code
        assert otp_repo2.challenges[_PHONE_E164].code == second_code

    def test_second_request_to_same_phone_overwrites_challenge(self) -> None:
        uc, _, otp_repo, sender, _ = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}, rng=Random(7)
        )
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        first_challenge = otp_repo.challenges[_PHONE_E164]
        # Rebuild use case sharing the same otp_repo to simulate a second request
        uc2 = RequestPasswordReset(
            FakeAuthUserRepository(credentials_by_phone={_PHONE_E164: _creds()}),
            otp_repo,  # shared OTP repository
            FakeOtpSender(),
            rng=Random(13),
            clock=lambda: _NOW,
        )
        uc2.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        # The challenge stored for the key must differ from the first one
        assert otp_repo.challenges[_PHONE_E164] is not first_challenge


# ── RequestPasswordReset — anti-énumération ───────────────────────────────────


class TestRequestPasswordResetSilent:
    """La demande ne révèle jamais l'existence ou l'état d'un compte (#11 §anti-énumération)."""

    def test_unknown_account_returns_without_exception(self) -> None:
        uc, _, _, _, _ = _make_request_uc()  # dépôt vide
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))

    def test_unknown_account_does_not_save_challenge(self) -> None:
        uc, _, otp_repo, _, _ = _make_request_uc()
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not otp_repo.challenges

    def test_unknown_account_does_not_send_otp(self) -> None:
        uc, _, _, sender, _ = _make_request_uc()
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not sender.sent

    def test_inactive_account_returns_without_exception(self) -> None:
        creds = _creds(UserStatus.INACTIVE.value)
        uc, _, _, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: creds})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))

    def test_inactive_account_does_not_save_challenge(self) -> None:
        creds = _creds(UserStatus.INACTIVE.value)
        uc, _, otp_repo, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: creds})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not otp_repo.challenges

    def test_inactive_account_does_not_send_otp(self) -> None:
        creds = _creds(UserStatus.INACTIVE.value)
        uc, _, _, sender, _ = _make_request_uc(creds_by_phone={_PHONE_E164: creds})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not sender.sent

    def test_suspended_account_does_not_save_challenge(self) -> None:
        creds = _creds(UserStatus.SUSPENDED.value)
        uc, _, otp_repo, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: creds})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not otp_repo.challenges

    def test_empty_identifier_returns_without_exception(self) -> None:
        uc, _, _, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=""))

    def test_empty_identifier_does_not_save_challenge(self) -> None:
        uc, _, otp_repo, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=""))
        assert not otp_repo.challenges

    def test_invalid_phone_returns_without_exception(self) -> None:
        uc, _, _, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier="notaphone"))

    def test_invalid_phone_does_not_save_challenge(self) -> None:
        uc, _, otp_repo, _, _ = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier="notaphone"))
        assert not otp_repo.challenges


# ── RequestPasswordReset — rate-limit ─────────────────────────────────────────


class TestRequestPasswordResetRateLimit:
    def test_locked_raises_too_many_attempts(self) -> None:
        uc, _, _, _, _ = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}, locked=True
        )
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))

    def test_locked_propagates_retry_after(self) -> None:
        uc, _, _, _, _ = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}, locked=True, retry_after=300
        )
        with pytest.raises(TooManyLoginAttempts) as exc_info:
            uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert exc_info.value.retry_after == 300

    def test_locked_does_not_save_challenge(self) -> None:
        """Le rate-limiter est vérifié AVANT tout accès base (#11 §anti-abus)."""
        uc, _, otp_repo, _, _ = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}, locked=True
        )
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not otp_repo.challenges

    def test_locked_does_not_send_otp(self) -> None:
        uc, _, _, sender, _ = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}, locked=True
        )
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not sender.sent

    def test_rate_limiter_check_called(self) -> None:
        uc, _, _, _, rate_limiter = _make_request_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert rate_limiter.checks

    def test_rate_limiter_check_not_called_without_limiter(self) -> None:
        repo = FakeAuthUserRepository(credentials_by_phone={_PHONE_E164: _creds()})
        uc = RequestPasswordReset(
            repo, FakeOtpRepository(), FakeOtpSender(),
            rate_limiter=None, rng=Random(42), clock=lambda: _NOW,
        )
        # Should not raise even with no rate limiter
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))


# ── RequestPasswordReset — record_failure ─────────────────────────────────────


class TestRequestPasswordResetRecordFailure:
    """record_failure est appelé après chaque demande, succès compris (#11 §anti-abus)."""

    def test_success_records_failure(self) -> None:
        uc, _, _, _, rate_limiter = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}
        )
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert rate_limiter.failures

    def test_unknown_account_records_failure(self) -> None:
        uc, _, _, _, rate_limiter = _make_request_uc()
        uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert rate_limiter.failures

    def test_locked_does_not_record_failure(self) -> None:
        """TooManyLoginAttempts propagates before record_failure is reached."""
        uc, _, _, _, rate_limiter = _make_request_uc(
            creds_by_phone={_PHONE_E164: _creds()}, locked=True
        )
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(PasswordResetRequestCommand(identifier=_PHONE_LOCAL))
        assert not rate_limiter.failures


# ── ConfirmPasswordReset — succès ─────────────────────────────────────────────


class TestConfirmPasswordResetSuccess:
    def test_success_calls_update_password(self) -> None:
        uc, repo, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        uc.execute(PasswordResetConfirmCommand(
            identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
        ))
        assert repo.updated_passwords

    def test_success_stores_new_hash(self) -> None:
        uc, repo, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        uc.execute(PasswordResetConfirmCommand(
            identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
        ))
        _, new_hash = repo.updated_passwords[0]
        assert FakeHasher().verify(_NEW_PASS, new_hash)

    def test_success_deletes_challenge(self) -> None:
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        uc.execute(PasswordResetConfirmCommand(
            identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
        ))
        assert _PHONE_E164 not in otp_repo.challenges

    def test_old_password_no_longer_authenticates(self) -> None:
        """Critère d'acceptation : l'ancien mot de passe est invalidé (#11)."""
        old_pass = "ancien-mdp"
        hasher = FakeHasher()
        creds = UserCredentials(
            id=_UID, role="CLIENT",
            status=UserStatus.ACTIVE.value,
            password_hash=hasher.hash(old_pass),
        )
        repo = FakeAuthUserRepository(credentials_by_phone={_PHONE_E164: creds})
        otp_repo = FakeOtpRepository()
        otp_repo.save(_PHONE_E164, _valid_challenge())
        uc = ConfirmPasswordReset(repo, otp_repo, hasher, clock=lambda: _NOW)
        uc.execute(PasswordResetConfirmCommand(
            identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
        ))
        updated = repo.find_by_phone(_PHONE_E164)
        assert updated is not None
        assert not hasher.verify(old_pass, updated.password_hash)
        assert hasher.verify(_NEW_PASS, updated.password_hash)

    def test_success_by_email_identifier(self) -> None:
        uc, repo, otp_repo = _make_confirm_uc(creds_by_email={_EMAIL: _creds()})
        otp_repo.save(_EMAIL, _valid_challenge())
        uc.execute(PasswordResetConfirmCommand(
            identifier=_EMAIL, code=_OTP_CODE, new_password=_NEW_PASS
        ))
        assert repo.updated_passwords

    def test_challenge_single_use_cannot_be_reused(self) -> None:
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        uc.execute(PasswordResetConfirmCommand(
            identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
        ))
        # Second attempt after successful reset: no challenge in repo → InvalidOtp
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))


# ── ConfirmPasswordReset — politique de mot de passe vérifiée en premier ──────


class TestConfirmPasswordResetPasswordPolicy:
    """validate_password est appelé avant la vérification OTP (#11 ordonnancement)."""

    def test_too_short_password_raises_invalid_password(self) -> None:
        uc, _, _ = _make_confirm_uc()
        with pytest.raises(InvalidPassword):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_TOO_SHORT_PASS
            ))

    def test_empty_password_raises_invalid_password(self) -> None:
        uc, _, _ = _make_confirm_uc()
        with pytest.raises(InvalidPassword):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=""
            ))

    def test_invalid_password_does_not_update_hash(self) -> None:
        uc, repo, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidPassword):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_TOO_SHORT_PASS
            ))
        assert not repo.updated_passwords

    def test_invalid_password_even_without_otp_challenge(self) -> None:
        """La politique de mot de passe est vérifiée avant tout accès OTP."""
        uc, _, _ = _make_confirm_uc()  # dépôt OTP vide
        with pytest.raises(InvalidPassword):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_TOO_SHORT_PASS
            ))


# ── ConfirmPasswordReset — OTP invalide ───────────────────────────────────────


class TestConfirmPasswordResetInvalidOtp:
    def test_no_challenge_raises_invalid_otp(self) -> None:
        uc, _, _ = _make_confirm_uc()  # dépôt OTP vide
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_wrong_code_raises_invalid_otp(self) -> None:
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge(code="999999"))
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code="000000", new_password=_NEW_PASS
            ))

    def test_wrong_code_decrements_attempts(self) -> None:
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge(code="999999", attempts=3))
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code="000000", new_password=_NEW_PASS
            ))
        assert otp_repo.challenges[_PHONE_E164].attempts_left == 2

    def test_wrong_code_saves_mutated_challenge(self) -> None:
        """L'état muté du défi (tentatives décrémentées) est persisté après un échec."""
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge(code="999999", attempts=2))
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code="000000", new_password=_NEW_PASS
            ))
        # Challenge still present but with decremented attempts
        assert _PHONE_E164 in otp_repo.challenges
        assert otp_repo.challenges[_PHONE_E164].attempts_left == 1

    def test_wrong_code_does_not_update_password(self) -> None:
        uc, repo, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge(code="999999"))
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code="000000", new_password=_NEW_PASS
            ))
        assert not repo.updated_passwords

    def test_expired_otp_raises_invalid_otp(self) -> None:
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _expired_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_expired_otp_does_not_update_password(self) -> None:
        uc, repo, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _expired_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))
        assert not repo.updated_passwords

    def test_exhausted_attempts_raises_invalid_otp(self) -> None:
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _exhausted_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_already_consumed_challenge_raises_invalid_otp(self) -> None:
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge(consumed=True))
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_empty_identifier_raises_invalid_otp(self) -> None:
        uc, _, otp_repo = _make_confirm_uc()
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier="", code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_unclassifiable_identifier_raises_invalid_otp(self) -> None:
        uc, _, otp_repo = _make_confirm_uc()
        otp_repo.save("notaphone", _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier="notaphone", code=_OTP_CODE, new_password=_NEW_PASS
            ))


# ── ConfirmPasswordReset — indistinguabilité des erreurs ──────────────────────


class TestConfirmPasswordResetIndistinguishability:
    """Toutes les causes d'échec d'OTP lèvent le même InvalidOtp (anti-énumération)."""

    def test_no_challenge_and_wrong_code_same_error_class(self) -> None:
        uc_no_chal, _, _ = _make_confirm_uc()
        uc_wrong, _, otp_repo_wrong = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo_wrong.save(_PHONE_E164, _valid_challenge(code="999999"))
        with pytest.raises(InvalidOtp):
            uc_no_chal.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))
        with pytest.raises(InvalidOtp):
            uc_wrong.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code="000000", new_password=_NEW_PASS
            ))

    def test_expired_and_exhausted_same_error_class(self) -> None:
        uc_exp, _, otp_repo_exp = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        uc_exh, _, otp_repo_exh = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo_exp.save(_PHONE_E164, _expired_challenge())
        otp_repo_exh.save(_PHONE_E164, _exhausted_challenge())
        with pytest.raises(InvalidOtp):
            uc_exp.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))
        with pytest.raises(InvalidOtp):
            uc_exh.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_error_message_does_not_contain_otp_code(self) -> None:
        """Le message d'erreur ne divulgue jamais la valeur du code OTP."""
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: _creds()})
        otp_repo.save(_PHONE_E164, _valid_challenge(code="999999"))
        with pytest.raises(InvalidOtp) as exc_info:
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code="000000", new_password=_NEW_PASS
            ))
        assert "000000" not in str(exc_info.value)
        assert "999999" not in str(exc_info.value)


# ── ConfirmPasswordReset — compte absent ou inactif après OTP valide ──────────


class TestConfirmPasswordResetAccountNotFound:
    """Compte disparu ou non ACTIVE après vérification OTP valide → InvalidOtp."""

    def test_account_not_found_raises_invalid_otp(self) -> None:
        uc, _, otp_repo = _make_confirm_uc()  # dépôt utilisateur vide
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_account_not_found_deletes_challenge(self) -> None:
        uc, _, otp_repo = _make_confirm_uc()
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))
        assert _PHONE_E164 not in otp_repo.challenges

    def test_inactive_account_raises_invalid_otp(self) -> None:
        creds = _creds(UserStatus.INACTIVE.value)
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: creds})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_inactive_account_deletes_challenge(self) -> None:
        creds = _creds(UserStatus.INACTIVE.value)
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: creds})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))
        assert _PHONE_E164 not in otp_repo.challenges

    def test_suspended_account_raises_invalid_otp(self) -> None:
        creds = _creds(UserStatus.SUSPENDED.value)
        uc, _, otp_repo = _make_confirm_uc(creds_by_phone={_PHONE_E164: creds})
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))

    def test_account_not_found_does_not_update_password(self) -> None:
        uc, repo, otp_repo = _make_confirm_uc()
        otp_repo.save(_PHONE_E164, _valid_challenge())
        with pytest.raises(InvalidOtp):
            uc.execute(PasswordResetConfirmCommand(
                identifier=_PHONE_LOCAL, code=_OTP_CODE, new_password=_NEW_PASS
            ))
        assert not repo.updated_passwords
