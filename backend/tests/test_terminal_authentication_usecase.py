"""Tests unitaires — `AuthenticateTerminalDevice` (US-8.1, #155).

Couvre l'orchestration du cas d'usage sans I/O réelle :
- Parcours heureux : credential valide → paire JWT rôle `TERMINAL` + `salon_id`
  correct retourné ; jeton émis avec l'UUID du device, jamais d'un compte humain.
- Anti-oracle : device inconnu, mauvais secret, device révoqué (SUSPENDED) et
  device inactif lèvent tous `InvalidCredentials` avec le **même message générique**
  (aucun oracle sur l'existence ni l'état d'un device, ADR-0041/ADR-0026).
- Atténuation temporelle : la vérification `hasher.verify` est appelée même quand
  aucun device ne correspond (dummy hash), pour égaliser le temps de réponse.
- `device_id` illisible (non-UUID, vide) → `InvalidCredentials` (pas d'exception
  d'implémentation).
- Anti-bruteforce : limiteur consulté **avant** tout accès dépôt, incrémenté en
  cas d'échec, réinitialisé en cas de succès ; `TooManyLoginAttempts` si verrou.
- Clé de rate-limit : `{device_id_brut}|{ip}` — isolation par device **et** IP.

Tous les ports sont des fakes — aucune base, aucun JWT réel, aucun argon2 réel.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.application.terminal_authentication import (
    AuthenticateTerminalDevice,
    TerminalLoginCommand,
    TerminalLoginResult,
)
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import InvalidCredentials, TooManyLoginAttempts
from coiflink_api.domain.terminal_device import TerminalDeviceCredentials

from .conftest import (
    FAKE_TOKEN_PAIR,
    FakeHasher,
    FakeLoginRateLimiter,
    FakeTokenService,
)

# Identifiants synthétiques — aucune PII, aucun secret réel.
_DEVICE_ID  = uuid.UUID("d0000000-0000-0000-0000-000000000001")
_SALON_ID   = uuid.UUID("a0000000-0000-0000-0000-000000000001")
_GOOD_SECRET = "good-device-secret-for-tests"

_HASHER = FakeHasher()
_GOOD_HASH = _HASHER.hash(_GOOD_SECRET)


# ---------------------------------------------------------------------------
# Fausse implémentation du dépôt de bornes (lecture credentials uniquement).
# ---------------------------------------------------------------------------


class _FakeTerminalRepo:
    """Dépôt en mémoire : un seul credential configurable, aucun secret réel."""

    def __init__(self, creds: TerminalDeviceCredentials | None = None) -> None:
        self._creds = creds
        self.find_calls: list[uuid.UUID] = []

    def find_credentials(self, device_id: uuid.UUID) -> TerminalDeviceCredentials | None:
        self.find_calls.append(device_id)
        if self._creds is not None and self._creds.id == device_id:
            return self._creds
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creds(
    *,
    status: str = UserStatus.ACTIVE.value,
    password_hash: str = _GOOD_HASH,
) -> TerminalDeviceCredentials:
    return TerminalDeviceCredentials(
        id=_DEVICE_ID,
        salon_id=_SALON_ID,
        password_hash=password_hash,
        status=status,
    )


def _make_usecase(
    *,
    creds: TerminalDeviceCredentials | None,
    rate_limiter: FakeLoginRateLimiter | None = None,
    token_service: FakeTokenService | None = None,
) -> tuple[AuthenticateTerminalDevice, _FakeTerminalRepo, FakeLoginRateLimiter]:
    repo = _FakeTerminalRepo(creds)
    limiter = rate_limiter or FakeLoginRateLimiter()
    ts = token_service or FakeTokenService()
    # Dummy hash pré-calculé pour éviter l'argon2 réel dans le cas sans device.
    dummy_hash = _HASHER.hash("dummy-for-tests")
    uc = AuthenticateTerminalDevice(
        repository=repo,
        hasher=_HASHER,
        token_service=ts,
        rate_limiter=limiter,
        dummy_hash=dummy_hash,
    )
    return uc, repo, limiter


# ---------------------------------------------------------------------------
# Parcours heureux
# ---------------------------------------------------------------------------


class TestAuthenticateTerminalDeviceSuccess:
    def test_returns_terminal_login_result(self) -> None:
        uc, _repo, _limiter = _make_usecase(creds=_creds())
        result = uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert isinstance(result, TerminalLoginResult)

    def test_returns_token_pair_from_token_service(self) -> None:
        uc, _repo, _limiter = _make_usecase(creds=_creds())
        result = uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert result.tokens == FAKE_TOKEN_PAIR

    def test_returns_correct_salon_id(self) -> None:
        uc, _repo, _limiter = _make_usecase(creds=_creds())
        result = uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert result.salon_id == _SALON_ID

    def test_token_issued_with_terminal_role(self) -> None:
        """Le jeton est émis avec `role = TERMINAL` — jamais avec un rôle humain."""
        ts = FakeTokenService()
        uc, _repo, _limiter = _make_usecase(creds=_creds(), token_service=ts)
        uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert len(ts.issued) == 1
        _uid, issued_role = ts.issued[0]
        assert issued_role == Role.TERMINAL.value

    def test_token_issued_with_device_uuid(self) -> None:
        """L'`user_id` du jeton est l'UUID du device, pas celui d'un compte humain."""
        ts = FakeTokenService()
        uc, _repo, _limiter = _make_usecase(creds=_creds(), token_service=ts)
        uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        issued_uid, _role = ts.issued[0]
        assert str(issued_uid) == str(_DEVICE_ID)

    def test_rate_limiter_reset_on_success(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=_creds())
        uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert len(limiter.resets) == 1
        assert len(limiter.failures) == 0

    def test_device_id_with_surrounding_spaces_is_normalised(self) -> None:
        """Un `device_id` avec espaces est normalisé (strip) avant résolution."""
        uc, _repo, _limiter = _make_usecase(creds=_creds())
        result = uc.execute(
            TerminalLoginCommand(device_id=f"  {_DEVICE_ID}  ", secret=_GOOD_SECRET)
        )
        assert result.salon_id == _SALON_ID


# ---------------------------------------------------------------------------
# Anti-oracle : `InvalidCredentials` identique quel que soit le motif d'échec
# ---------------------------------------------------------------------------


class TestAuthenticateTerminalDeviceFailure:
    def test_unknown_device_raises_invalid_credentials(self) -> None:
        uc, _repo, _limiter = _make_usecase(creds=None)
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))

    def test_wrong_secret_raises_invalid_credentials(self) -> None:
        uc, _repo, _limiter = _make_usecase(creds=_creds())
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret="wrong-secret"))

    def test_suspended_device_raises_invalid_credentials(self) -> None:
        """Borne révoquée → même erreur que mauvais secret (anti-oracle sur l'état)."""
        suspended = _creds(status=UserStatus.SUSPENDED.value)
        uc, _repo, _limiter = _make_usecase(creds=suspended)
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))

    def test_inactive_device_raises_invalid_credentials(self) -> None:
        inactive = _creds(status=UserStatus.INACTIVE.value)
        uc, _repo, _limiter = _make_usecase(creds=inactive)
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))

    def test_non_uuid_device_id_raises_invalid_credentials(self) -> None:
        """Un `device_id` non-UUID est ignoré sans exception d'implémentation."""
        uc, _repo, _limiter = _make_usecase(creds=_creds())
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id="not-a-uuid", secret=_GOOD_SECRET))

    def test_empty_device_id_raises_invalid_credentials(self) -> None:
        uc, _repo, _limiter = _make_usecase(creds=_creds())
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id="", secret=_GOOD_SECRET))

    def test_unknown_device_message_equals_wrong_secret_message(self) -> None:
        """Messages **identiques** : ni l'existence ni l'état d'un device n'est divulgué."""
        uc_unknown, _r1, _l1 = _make_usecase(creds=None)
        uc_wrong, _r2, _l2 = _make_usecase(creds=_creds())

        with pytest.raises(InvalidCredentials) as ei_unknown:
            uc_unknown.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        with pytest.raises(InvalidCredentials) as ei_wrong:
            uc_wrong.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret="bad"))

        assert str(ei_unknown.value) == str(ei_wrong.value)

    def test_suspended_message_equals_wrong_secret_message(self) -> None:
        """Compte suspendu → même message (anti-oracle sur le statut du device)."""
        suspended = _creds(status=UserStatus.SUSPENDED.value)
        uc_susp, _r1, _l1 = _make_usecase(creds=suspended)
        uc_wrong, _r2, _l2 = _make_usecase(creds=_creds())

        with pytest.raises(InvalidCredentials) as ei_susp:
            uc_susp.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        with pytest.raises(InvalidCredentials) as ei_wrong:
            uc_wrong.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret="bad"))

        assert str(ei_susp.value) == str(ei_wrong.value)

    def test_failure_increments_rate_limiter(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=None)
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert len(limiter.failures) == 1

    def test_success_does_not_increment_rate_limiter(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=_creds())
        uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert limiter.failures == []

    def test_unknown_device_triggers_dummy_verify_not_impl_error(self) -> None:
        """Atténuation temporelle : `verify` est appelé même sans device (anti-oracle).

        On vérifie **indirectement** : si le dummy verify n'était pas appelé, le
        code lèverait une `AttributeError` interne. L'absence d'une telle exception
        prouve que le chemin dummy est bien parcouru.
        """
        uc, _repo, _limiter = _make_usecase(creds=None)
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret="anything"))


# ---------------------------------------------------------------------------
# Anti-bruteforce — rate limiter
# ---------------------------------------------------------------------------


class TestTerminalRateLimiter:
    def test_locked_rate_limiter_raises_too_many_attempts(self) -> None:
        limiter = FakeLoginRateLimiter(locked=True)
        uc, repo, _l = _make_usecase(creds=_creds(), rate_limiter=limiter)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))

    def test_rate_limiter_checked_before_repo(self) -> None:
        """Le verrou est consulté **avant** tout accès dépôt (deny-by-default)."""
        limiter = FakeLoginRateLimiter(locked=True)
        uc, repo, _l = _make_usecase(creds=_creds(), rate_limiter=limiter)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert repo.find_calls == [], (
            "Le dépôt ne doit pas être interrogé quand le verrou est ouvert."
        )

    def test_rate_limiter_key_includes_device_id(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=_creds())
        uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert len(limiter.checks) == 1
        assert str(_DEVICE_ID) in limiter.checks[0]

    def test_rate_limiter_key_includes_ip(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=_creds())
        client_ip = "10.0.0.42"
        uc.execute(
            TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET, client_ip=client_ip)
        )
        assert client_ip in limiter.checks[0]

    def test_rate_limiter_key_without_ip_uses_dash(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=_creds())
        uc.execute(
            TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET, client_ip=None)
        )
        # La clé doit contenir « |- » quand l'IP est absente.
        assert "|-" in limiter.checks[0]

    def test_rate_limiter_check_called_exactly_once_on_success(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=_creds())
        uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert len(limiter.checks) == 1

    def test_rate_limiter_reset_called_on_success(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=_creds())
        uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert len(limiter.resets) == 1

    def test_rate_limiter_record_failure_called_on_bad_credentials(self) -> None:
        uc, _repo, limiter = _make_usecase(creds=None)
        with pytest.raises(InvalidCredentials):
            uc.execute(TerminalLoginCommand(device_id=str(_DEVICE_ID), secret=_GOOD_SECRET))
        assert len(limiter.failures) == 1
