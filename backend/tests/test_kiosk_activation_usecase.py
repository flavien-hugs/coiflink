"""Tests unitaires — `ActivateKioskDevice` (US-8.1, #155).

Couvre l'orchestration du cas d'usage sans I/O réelle :
- Parcours heureux : code valide → secret généré (une seule fois), condensat écrit
  via `set_password_hash`, défi supprimé, limiteur réinitialisé.
- Anti-énumération : code inconnu, expiré, trop d'essais et déjà consommé lèvent
  tous `InvalidActivationCode` avec le **même message générique**.
- Usage unique : réutiliser un code déjà activé échoue (défi supprimé après succès).
- Anti-bruteforce : limiteur consulté **avant** tout accès dépôt (clé = IP, aucun
  `device_id` connu avant résolution du code), incrémenté en échec, réinitialisé en
  succès ; `TooManyLoginAttempts` si verrou.
- Code vide/illisible → `InvalidActivationCode` (pas d'exception d'implémentation).

Tous les ports sont des fakes — aucune base, aucun argon2 réel.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from coiflink_api.application.kiosk_device_activation import (
    ActivateKioskDevice,
    ActivateKioskDeviceCommand,
    ActivateKioskDeviceResult,
)
from coiflink_api.domain.errors import InvalidActivationCode, TooManyLoginAttempts
from coiflink_api.domain.otp import OtpChallenge

from .conftest import FakeHasher, FakeLoginRateLimiter

_DEVICE_ID = uuid.UUID("d0000000-0000-0000-0000-000000000001")
_GOOD_CODE = "123456"
_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

_HASHER = FakeHasher()


# ---------------------------------------------------------------------------
# Fausses implémentations des dépôts.
# ---------------------------------------------------------------------------


class _FakeActivationRepo:
    """Un seul défi configurable, adressé par device_id **et** retrouvable par code."""

    def __init__(self, device_id: uuid.UUID | None = None, challenge: OtpChallenge | None = None) -> None:
        self._store: dict[uuid.UUID, OtpChallenge] = {}
        if device_id is not None and challenge is not None:
            self._store[device_id] = challenge
        self.saved: list[tuple[uuid.UUID, OtpChallenge]] = []
        self.deleted: list[uuid.UUID] = []

    def save(self, device_id: uuid.UUID, challenge: OtpChallenge) -> None:
        self.saved.append((device_id, challenge))
        self._store[device_id] = challenge

    def find_by_code(self, code: str) -> tuple[uuid.UUID, OtpChallenge] | None:
        for device_id, challenge in self._store.items():
            if challenge.code == code:
                return device_id, challenge
        return None

    def delete(self, device_id: uuid.UUID) -> None:
        self.deleted.append(device_id)
        self._store.pop(device_id, None)


class _FakeDeviceRepo:
    """Enregistre uniquement les appels à `set_password_hash` (seule méthode exercée)."""

    def __init__(self) -> None:
        self.set_password_hash_calls: list[tuple[uuid.UUID, str]] = []

    def set_password_hash(self, device_id: uuid.UUID, password_hash: str) -> None:
        self.set_password_hash_calls.append((device_id, password_hash))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _challenge(
    *,
    code: str = _GOOD_CODE,
    expires_at: datetime.datetime | None = None,
    attempts_left: int = 5,
    consumed: bool = False,
) -> OtpChallenge:
    return OtpChallenge(
        code=code,
        expires_at=expires_at or _NOW + datetime.timedelta(hours=24),
        attempts_left=attempts_left,
        consumed=consumed,
    )


def _make_usecase(
    *,
    activation_repo: _FakeActivationRepo | None = None,
    device_repo: _FakeDeviceRepo | None = None,
    rate_limiter: FakeLoginRateLimiter | None = None,
) -> tuple[ActivateKioskDevice, _FakeActivationRepo, _FakeDeviceRepo, FakeLoginRateLimiter]:
    act_repo = activation_repo or _FakeActivationRepo(_DEVICE_ID, _challenge())
    dev_repo = device_repo or _FakeDeviceRepo()
    limiter = rate_limiter or FakeLoginRateLimiter()
    uc = ActivateKioskDevice(
        activation_repository=act_repo,
        device_repository=dev_repo,
        hasher=_HASHER,
        rate_limiter=limiter,
        clock=lambda: _NOW,
    )
    return uc, act_repo, dev_repo, limiter


# ---------------------------------------------------------------------------
# Parcours heureux
# ---------------------------------------------------------------------------


class TestActivateKioskDeviceSuccess:
    def test_returns_activation_result(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        result = uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert isinstance(result, ActivateKioskDeviceResult)

    def test_returns_correct_device_id(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        result = uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert result.device_id == _DEVICE_ID

    def test_returns_non_empty_secret(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        result = uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert result.secret.strip() != ""

    def test_secret_differs_from_code(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        result = uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert result.secret != _GOOD_CODE

    def test_device_repository_receives_hash_of_returned_secret(self) -> None:
        uc, _act, dev, _lim = _make_usecase()
        result = uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert len(dev.set_password_hash_calls) == 1
        called_device_id, called_hash = dev.set_password_hash_calls[0]
        assert called_device_id == _DEVICE_ID
        assert _HASHER.verify(result.secret, called_hash)

    def test_activation_challenge_deleted_after_success(self) -> None:
        uc, act, _dev, _lim = _make_usecase()
        uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert act.deleted == [_DEVICE_ID]

    def test_rate_limiter_reset_on_success(self) -> None:
        uc, _act, _dev, lim = _make_usecase()
        uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert len(lim.resets) == 1
        assert lim.failures == []

    def test_code_with_surrounding_spaces_is_normalised(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        result = uc.execute(ActivateKioskDeviceCommand(code=f"  {_GOOD_CODE}  "))
        assert result.device_id == _DEVICE_ID


# ---------------------------------------------------------------------------
# Anti-énumération : `InvalidActivationCode` identique quel que soit le motif
# ---------------------------------------------------------------------------


class TestActivateKioskDeviceFailure:
    def test_unknown_code_raises_invalid_activation_code(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code="000000"))

    def test_expired_code_raises_invalid_activation_code(self) -> None:
        expired = _challenge(expires_at=_NOW - datetime.timedelta(minutes=1))
        uc, _act, _dev, _lim = _make_usecase(
            activation_repo=_FakeActivationRepo(_DEVICE_ID, expired)
        )
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))

    def test_already_consumed_code_raises_invalid_activation_code(self) -> None:
        consumed = _challenge(consumed=True)
        uc, _act, _dev, _lim = _make_usecase(
            activation_repo=_FakeActivationRepo(_DEVICE_ID, consumed)
        )
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))

    def test_exhausted_attempts_raises_invalid_activation_code(self) -> None:
        exhausted = _challenge(attempts_left=0)
        uc, _act, _dev, _lim = _make_usecase(
            activation_repo=_FakeActivationRepo(_DEVICE_ID, exhausted)
        )
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))

    def test_wrong_code_raises_invalid_activation_code(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code="999999"))

    def test_empty_code_raises_invalid_activation_code(self) -> None:
        uc, _act, _dev, _lim = _make_usecase()
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code=""))

    def test_reusing_a_consumed_code_fails_second_time(self) -> None:
        """Usage unique garanti : le défi est supprimé après le premier succès."""
        uc, _act, _dev, _lim = _make_usecase()
        uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))

    def test_unknown_and_expired_messages_are_identical(self) -> None:
        """Anti-énumération : aucun oracle sur la cause exacte de l'échec."""
        uc_unknown, _a1, _d1, _l1 = _make_usecase()
        expired = _challenge(expires_at=_NOW - datetime.timedelta(minutes=1))
        uc_expired, _a2, _d2, _l2 = _make_usecase(
            activation_repo=_FakeActivationRepo(_DEVICE_ID, expired)
        )

        with pytest.raises(InvalidActivationCode) as ei_unknown:
            uc_unknown.execute(ActivateKioskDeviceCommand(code="000000"))
        with pytest.raises(InvalidActivationCode) as ei_expired:
            uc_expired.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))

        assert str(ei_unknown.value) == str(ei_expired.value)

    def test_failure_increments_rate_limiter(self) -> None:
        uc, _act, _dev, lim = _make_usecase()
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code="000000"))
        assert len(lim.failures) == 1

    def test_failure_does_not_delete_challenge(self) -> None:
        """Un échec (mauvais code, mais un défi existe pour un autre code) ne purge rien."""
        uc, act, _dev, _lim = _make_usecase()
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code="000000"))
        assert act.deleted == []

    def test_failure_does_not_call_set_password_hash(self) -> None:
        uc, _act, dev, _lim = _make_usecase()
        with pytest.raises(InvalidActivationCode):
            uc.execute(ActivateKioskDeviceCommand(code="000000"))
        assert dev.set_password_hash_calls == []


# ---------------------------------------------------------------------------
# Anti-bruteforce — rate limiter
# ---------------------------------------------------------------------------


class TestActivationRateLimiter:
    def test_locked_rate_limiter_raises_too_many_attempts(self) -> None:
        limiter = FakeLoginRateLimiter(locked=True)
        uc, _act, _dev, _lim = _make_usecase(rate_limiter=limiter)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))

    def test_rate_limiter_checked_before_repository_access(self) -> None:
        limiter = FakeLoginRateLimiter(locked=True)
        act = _FakeActivationRepo(_DEVICE_ID, _challenge())
        uc, _act, _dev, _lim = _make_usecase(activation_repo=act, rate_limiter=limiter)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE))
        assert act.deleted == [], "Aucun accès dépôt ne doit avoir lieu quand le verrou est fermé."

    def test_rate_limiter_key_uses_client_ip(self) -> None:
        uc, _act, _dev, limiter = _make_usecase()
        uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE, client_ip="10.0.0.42"))
        assert len(limiter.checks) == 1
        assert "10.0.0.42" in limiter.checks[0]

    def test_rate_limiter_key_without_ip_uses_dash(self) -> None:
        uc, _act, _dev, limiter = _make_usecase()
        uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE, client_ip=None))
        assert "|-" in limiter.checks[0]

    def test_rate_limiter_key_does_not_depend_on_device_id(self) -> None:
        """Le `device_id` est inconnu avant résolution du code : la clé ne peut être que l'IP."""
        uc, _act, _dev, limiter = _make_usecase()
        uc.execute(ActivateKioskDeviceCommand(code=_GOOD_CODE, client_ip="1.2.3.4"))
        assert str(_DEVICE_ID) not in limiter.checks[0]
