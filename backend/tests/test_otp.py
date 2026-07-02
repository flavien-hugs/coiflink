"""Tests unitaires pour la logique OTP pure (domaine, #8).

Critère d'acceptation « l'OTP est testable » : le RNG et l'horloge sont injectés,
rendant chaque test déterministe et indépendant de l'I/O ou du temps système.
"""

from __future__ import annotations

import datetime
from random import Random

import pytest

from coiflink_api.domain.otp import (
    DEFAULT_OTP_LENGTH,
    DEFAULT_OTP_MAX_ATTEMPTS,
    DEFAULT_OTP_TTL,
    OtpChallenge,
    OtpStatus,
    generate_otp_challenge,
    verify_otp_challenge,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_SEEDED_RNG = Random(42)


def _rng() -> Random:
    """RNG à graine fixe (déterministe) pour les tests."""
    return Random(42)


def _active_challenge(
    code: str = "123456",
    attempts: int = DEFAULT_OTP_MAX_ATTEMPTS,
    consumed: bool = False,
    delta: datetime.timedelta = DEFAULT_OTP_TTL,
) -> OtpChallenge:
    return OtpChallenge(
        code=code,
        expires_at=_NOW + delta,
        attempts_left=attempts,
        consumed=consumed,
    )


class TestGenerateOtpChallenge:
    def test_code_length_equals_parameter(self) -> None:
        challenge = generate_otp_challenge(_rng(), _NOW, length=6)
        assert len(challenge.code) == 6

    def test_custom_length(self) -> None:
        challenge = generate_otp_challenge(_rng(), _NOW, length=4)
        assert len(challenge.code) == 4

    def test_code_digits_only(self) -> None:
        challenge = generate_otp_challenge(_rng(), _NOW)
        assert challenge.code.isdigit()

    def test_deterministic_with_same_seed(self) -> None:
        code1 = generate_otp_challenge(Random(99), _NOW).code
        code2 = generate_otp_challenge(Random(99), _NOW).code
        assert code1 == code2

    def test_expires_at_is_now_plus_ttl(self) -> None:
        ttl = datetime.timedelta(minutes=10)
        challenge = generate_otp_challenge(_rng(), _NOW, ttl=ttl)
        assert challenge.expires_at == _NOW + ttl

    def test_attempts_left_equals_max_attempts(self) -> None:
        challenge = generate_otp_challenge(_rng(), _NOW, max_attempts=5)
        assert challenge.attempts_left == 5

    def test_not_consumed_at_creation(self) -> None:
        challenge = generate_otp_challenge(_rng(), _NOW)
        assert challenge.consumed is False

    def test_zero_length_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            generate_otp_challenge(_rng(), _NOW, length=0)

    def test_negative_length_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            generate_otp_challenge(_rng(), _NOW, length=-1)

    def test_zero_max_attempts_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            generate_otp_challenge(_rng(), _NOW, max_attempts=0)

    def test_negative_max_attempts_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            generate_otp_challenge(_rng(), _NOW, max_attempts=-3)

    def test_default_length_is_6(self) -> None:
        assert DEFAULT_OTP_LENGTH == 6

    def test_default_max_attempts_is_3(self) -> None:
        assert DEFAULT_OTP_MAX_ATTEMPTS == 3


class TestVerifyOtpChallenge:
    def test_valid_if_correct_code_before_expiry(self) -> None:
        challenge = _active_challenge(code="123456")
        status = verify_otp_challenge(challenge, "123456", _NOW)
        assert status == OtpStatus.VALID

    def test_consumed_after_valid_verification(self) -> None:
        challenge = _active_challenge(code="123456")
        verify_otp_challenge(challenge, "123456", _NOW)
        assert challenge.consumed is True

    def test_invalid_if_incorrect_code(self) -> None:
        challenge = _active_challenge(code="123456", attempts=3)
        status = verify_otp_challenge(challenge, "000000", _NOW)
        assert status == OtpStatus.INVALID

    def test_attempts_decremented_after_incorrect_code(self) -> None:
        challenge = _active_challenge(code="123456", attempts=3)
        verify_otp_challenge(challenge, "000000", _NOW)
        assert challenge.attempts_left == 2

    def test_expired_if_instant_equals_expiry(self) -> None:
        challenge = _active_challenge(code="123456")
        status = verify_otp_challenge(challenge, "123456", challenge.expires_at)
        assert status == OtpStatus.EXPIRED

    def test_expired_if_instant_after_expiry(self) -> None:
        challenge = _active_challenge(code="123456")
        after = challenge.expires_at + datetime.timedelta(seconds=1)
        status = verify_otp_challenge(challenge, "123456", after)
        assert status == OtpStatus.EXPIRED

    def test_too_many_attempts_if_attempts_exhausted(self) -> None:
        challenge = _active_challenge(code="123456", attempts=0)
        status = verify_otp_challenge(challenge, "123456", _NOW)
        assert status == OtpStatus.TOO_MANY_ATTEMPTS

    def test_single_use_already_consumed(self) -> None:
        challenge = _active_challenge(code="123456", consumed=True)
        status = verify_otp_challenge(challenge, "123456", _NOW)
        assert status == OtpStatus.ALREADY_CONSUMED

    def test_already_consumed_takes_precedence_over_expiry(self) -> None:
        """ALREADY_CONSUMED est vérifié en premier (avant l'expiration)."""
        challenge = _active_challenge(code="123456", consumed=True, delta=-DEFAULT_OTP_TTL)
        status = verify_otp_challenge(challenge, "123456", _NOW)
        assert status == OtpStatus.ALREADY_CONSUMED

    def test_correct_code_cannot_be_reused(self) -> None:
        challenge = _active_challenge(code="123456")
        verify_otp_challenge(challenge, "123456", _NOW)
        # Deuxième tentative avec le bon code
        status = verify_otp_challenge(challenge, "123456", _NOW)
        assert status == OtpStatus.ALREADY_CONSUMED

    def test_attempts_exhausted_after_series_of_failures(self) -> None:
        challenge = _active_challenge(code="123456", attempts=3)
        for _ in range(3):
            verify_otp_challenge(challenge, "000000", _NOW)
        status = verify_otp_challenge(challenge, "123456", _NOW)
        assert status == OtpStatus.TOO_MANY_ATTEMPTS

    def test_attempts_left_does_not_drop_below_zero(self) -> None:
        challenge = _active_challenge(code="123456", attempts=1)
        verify_otp_challenge(challenge, "000000", _NOW)
        verify_otp_challenge(challenge, "000000", _NOW)  # déjà à 0
        assert challenge.attempts_left == 0

    def test_otp_statuses_str_enum(self) -> None:
        assert OtpStatus.VALID == "VALID"
        assert OtpStatus.INVALID == "INVALID"
        assert OtpStatus.EXPIRED == "EXPIRED"
        assert OtpStatus.TOO_MANY_ATTEMPTS == "TOO_MANY_ATTEMPTS"
        assert OtpStatus.ALREADY_CONSUMED == "ALREADY_CONSUMED"
