"""Tests unitaires — cas d'usage provisioning/révocation bornes kiosque (US-8.1, #155).

Couvre `ProvisionKioskDevice`, `ListKioskDevices` et `RevokeKioskDevice` :

**Provisioning** (depuis #155 « provisioning silencieux ») :
- Retourne l'entité **et** le **code d'activation à 6 chiffres** (une seule fois) —
  plus jamais le secret : celui-ci est généré à l'activation (`ActivateKioskDevice`).
- Code non-vide, exactement 6 chiffres, et **sauvegardé** dans le dépôt d'activation.
- Défi d'activation paramétré pour une installation matérielle : TTL 24 h, 5 essais.
- Le condensat stocké est un **placeholder** (secret jetable) : il ne correspond à
  aucune valeur retournée à l'appelant — d'où l'absence de test de vérification
  condensat/secret (invariant supprimé avec #155, il ne s'applique plus).
- Le libellé est normalisé (strip) avant stockage.
- Audit journalisé `KIOSK_DEVICE_PROVISIONED`, `entity_type = kiosk_device`,
  `metadata = {}` (invariant §11.3/§11.4 : ni secret, ni condensat, ni libellé).
- Label invalide (vide, trop long) → `InvalidKioskDeviceLabel`, **aucun** audit.

**Listing** : délégation directe au dépôt (lecture pure, pas d'audit).

**Révocation** :
- Suspension logique journalisée `KIOSK_DEVICE_REVOKED`, `entity_type = kiosk_device`,
  `metadata = {}` (même invariant que le provisioning).
- Borne hors salon / inexistante → `KioskDeviceNotFound` (aucun oracle §11.2).
- Aucun audit en cas d'échec.

Tous les ports sont des fakes — aucune base, aucun argon2 réel.
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid
from random import Random

import pytest

from coiflink_api.application.kiosk_devices import (
    ListKioskDevices,
    ProvisionKioskDevice,
    ProvisionKioskDeviceCommand,
    RevokeKioskDevice,
)
from coiflink_api.domain.audit import (
    ENTITY_TYPE_KIOSK_DEVICE,
    AuditAction,
)
from coiflink_api.domain.enums import UserStatus
from coiflink_api.domain.errors import InvalidKioskDeviceLabel, KioskDeviceNotFound
from coiflink_api.domain.kiosk_device import (
    KioskDevice,
    KioskDeviceToCreate,
)
from coiflink_api.domain.otp import OtpChallenge

from .conftest import FakeAuditLog, FakeHasher

# Identifiants synthétiques — aucune PII, aucun secret réel.
_SALON_ID  = uuid.UUID("a0000000-0000-0000-0000-000000000001")
_OTHER_SALON = uuid.UUID("c0000000-0000-0000-0000-000000000099")
_DEVICE_ID = uuid.UUID("d0000000-0000-0000-0000-000000000001")
_ACTOR_ID  = uuid.UUID("b0000000-0000-0000-0000-000000000001")
_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
# Horloge figée injectée au cas d'usage : rend l'`expires_at` du défi d'activation
# assertable exactement (aucune dépendance à l'heure système).
_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

# Paramètres attendus du défi d'activation (#155) — volontairement plus larges que
# les défauts OTP : l'activation est une installation matérielle, pas un login.
_EXPECTED_ACTIVATION_TTL = datetime.timedelta(hours=24)
_EXPECTED_ACTIVATION_MAX_ATTEMPTS = 5

_HASHER = FakeHasher()


# ---------------------------------------------------------------------------
# Fausse implémentation du dépôt de bornes.
# ---------------------------------------------------------------------------


class _FakeKioskDeviceRepo:
    """Dépôt en mémoire : create / list / revoke sans I/O réelle."""

    def __init__(self) -> None:
        self.created: list[KioskDeviceToCreate] = []
        self._devices: dict[uuid.UUID, KioskDevice] = {}

    def create(self, device: KioskDeviceToCreate) -> KioskDevice:
        entity = KioskDevice(
            id=_DEVICE_ID,
            salon_id=device.salon_id,
            label=device.label,
            status=UserStatus.ACTIVE.value,
            created_at=_CREATED_AT,
        )
        self._devices[entity.id] = entity
        self.created.append(device)
        return entity

    def list_for_salon(self, salon_id: uuid.UUID) -> tuple[KioskDevice, ...]:
        return tuple(d for d in self._devices.values() if d.salon_id == salon_id)

    def revoke(self, salon_id: uuid.UUID, device_id: uuid.UUID) -> KioskDevice | None:
        device = self._devices.get(device_id)
        if device is None or device.salon_id != salon_id:
            return None
        # Suspension logique (miroir du dépôt réel : `users.status = SUSPENDED`).
        suspended = dataclasses.replace(device, status=UserStatus.SUSPENDED.value)
        self._devices[device_id] = suspended
        return suspended


class _FakeKioskActivationRepo:
    """Dépôt de défis d'activation en mémoire — miroir du dépôt réel (par device_id)."""

    def __init__(self) -> None:
        self.saved: list[tuple[uuid.UUID, OtpChallenge]] = []
        self._store: dict[uuid.UUID, OtpChallenge] = {}

    def save(self, device_id: uuid.UUID, challenge: OtpChallenge) -> None:
        self.saved.append((device_id, challenge))
        self._store[device_id] = challenge

    def find_by_code(self, code: str) -> tuple[uuid.UUID, OtpChallenge] | None:
        for device_id, challenge in self._store.items():
            if challenge.code == code:
                return device_id, challenge
        return None

    def delete(self, device_id: uuid.UUID) -> None:
        self._store.pop(device_id, None)


# ---------------------------------------------------------------------------
# ProvisionKioskDevice
# ---------------------------------------------------------------------------


class TestProvisionKioskDevice:
    def _make(
        self,
        audit_log: FakeAuditLog | None = None,
        activation_repository: _FakeKioskActivationRepo | None = None,
        rng: Random | None = None,
    ) -> tuple[ProvisionKioskDevice, _FakeKioskDeviceRepo, FakeAuditLog, _FakeKioskActivationRepo]:
        repo = _FakeKioskDeviceRepo()
        log = audit_log or FakeAuditLog()
        activation_repo = activation_repository or _FakeKioskActivationRepo()
        uc = ProvisionKioskDevice(
            repository=repo,
            hasher=_HASHER,
            audit_log=log,
            activation_repository=activation_repo,
            rng=rng or Random(1),
            clock=lambda: _NOW,
        )
        return uc, repo, log, activation_repo

    def _execute(self, uc: ProvisionKioskDevice, label: str = "Borne entrée") -> tuple[KioskDevice, str]:
        return uc.execute(
            _SALON_ID,
            ProvisionKioskDeviceCommand(label=label),
            actor_user_id=_ACTOR_ID,
        )

    # --- Retour (device, activation_code) ---

    def test_returns_device_and_activation_code_tuple(self) -> None:
        uc, _repo, _log, _act = self._make()
        device, code = self._execute(uc)
        assert device is not None
        assert isinstance(code, str)

    def test_activation_code_is_six_digits(self) -> None:
        uc, _repo, _log, _act = self._make()
        _device, code = self._execute(uc)
        assert len(code) == 6
        assert code.isdigit()

    def test_activation_code_saved_exactly_once(self) -> None:
        uc, _repo, _log, act = self._make()
        self._execute(uc)
        assert len(act.saved) == 1

    def test_activation_challenge_device_id_matches_created_device(self) -> None:
        uc, _repo, _log, act = self._make()
        device, _code = self._execute(uc)
        saved_device_id, _challenge = act.saved[0]
        assert saved_device_id == device.id

    def test_activation_challenge_code_matches_returned_code(self) -> None:
        uc, _repo, _log, act = self._make()
        _device, code = self._execute(uc)
        _saved_device_id, challenge = act.saved[0]
        assert challenge.code == code

    def test_activation_challenge_ttl_is_24_hours(self) -> None:
        """Fenêtre volontairement large : geste d'installation matérielle, pas un login."""
        uc, _repo, _log, act = self._make()
        self._execute(uc)
        _device_id, challenge = act.saved[0]
        assert challenge.expires_at == _NOW + _EXPECTED_ACTIVATION_TTL

    def test_activation_challenge_max_attempts_is_five(self) -> None:
        uc, _repo, _log, act = self._make()
        self._execute(uc)
        _device_id, challenge = act.saved[0]
        assert challenge.attempts_left == _EXPECTED_ACTIVATION_MAX_ATTEMPTS

    def test_password_hash_is_not_derivable_from_activation_code(self) -> None:
        """Le condensat placeholder ne correspond à aucune valeur retournée (§11.3) :
        même le code d'activation, une fois consommé, ne vérifie jamais le login."""
        uc, repo, _log, _act = self._make()
        _device, code = self._execute(uc)
        stored_hash = repo.created[0].password_hash
        assert not _HASHER.verify(code, stored_hash)

    def test_device_salon_id_matches(self) -> None:
        uc, repo, _log, _act = self._make()
        _device, _secret = self._execute(uc)
        assert repo.created[0].salon_id == _SALON_ID

    def test_label_trimmed_before_storage(self) -> None:
        """Le libellé est normalisé (strip) avant stockage — identique à `validate_device_label`."""
        uc, repo, _log, _act = self._make()
        self._execute(uc, label="  Borne entrée  ")
        assert repo.created[0].label == "Borne entrée"

    def test_returned_device_has_matching_salon_id(self) -> None:
        uc, _repo, _log, _act = self._make()
        device, _secret = self._execute(uc)
        assert device.salon_id == _SALON_ID

    # --- Invariant §11.3 : device retourné sans secret ---

    def test_returned_device_has_no_attribute_password_hash(self) -> None:
        """Invariant §11.3 : `KioskDevice` retourné ne porte jamais le condensat."""
        uc, _repo, _log, _act = self._make()
        device, _secret = self._execute(uc)
        assert not hasattr(device, "password_hash")

    # --- Label invalide ---

    def test_invalid_empty_label_raises_before_audit(self) -> None:
        uc, _repo, log, _act = self._make()
        with pytest.raises(InvalidKioskDeviceLabel):
            uc.execute(
                _SALON_ID, ProvisionKioskDeviceCommand(label=""),
                actor_user_id=_ACTOR_ID,
            )
        assert log.recorded == [], "Aucun audit ne doit être émis si le label est invalide."

    def test_invalid_whitespace_label_raises(self) -> None:
        uc, _repo, _log, _act = self._make()
        with pytest.raises(InvalidKioskDeviceLabel):
            uc.execute(
                _SALON_ID, ProvisionKioskDeviceCommand(label="   "),
                actor_user_id=_ACTOR_ID,
            )

    # --- Audit ---

    def test_one_audit_entry_logged(self) -> None:
        uc, _repo, log, _act = self._make()
        self._execute(uc)
        assert len(log.recorded) == 1

    def test_audit_action_is_kiosk_device_provisioned(self) -> None:
        uc, _repo, log, _act = self._make()
        self._execute(uc)
        assert log.recorded[0].action == AuditAction.KIOSK_DEVICE_PROVISIONED.value

    def test_audit_entity_type_is_kiosk_device(self) -> None:
        uc, _repo, log, _act = self._make()
        self._execute(uc)
        assert log.recorded[0].entity_type == ENTITY_TYPE_KIOSK_DEVICE

    def test_audit_metadata_is_empty(self) -> None:
        """Invariant §11.3/§11.4 : ni secret, ni condensat, ni libellé au journal."""
        uc, _repo, log, _act = self._make()
        self._execute(uc, label="Borne super secrète")
        assert log.recorded[0].metadata == {}

    def test_audit_actor_user_id_matches(self) -> None:
        uc, _repo, log, _act = self._make()
        self._execute(uc)
        assert log.recorded[0].actor_user_id == _ACTOR_ID

    def test_audit_salon_id_matches(self) -> None:
        uc, _repo, log, _act = self._make()
        self._execute(uc)
        assert log.recorded[0].salon_id == _SALON_ID


# ---------------------------------------------------------------------------
# ListKioskDevices
# ---------------------------------------------------------------------------


class TestListKioskDevices:
    def test_returns_devices_for_salon(self) -> None:
        repo = _FakeKioskDeviceRepo()
        repo.create(KioskDeviceToCreate(salon_id=_SALON_ID, label="Borne A", password_hash="h"))
        uc = ListKioskDevices(repository=repo)
        devices = uc.execute(_SALON_ID)
        assert len(devices) == 1
        assert devices[0].salon_id == _SALON_ID

    def test_returns_empty_for_unknown_salon(self) -> None:
        repo = _FakeKioskDeviceRepo()
        uc = ListKioskDevices(repository=repo)
        devices = uc.execute(uuid.UUID("ffff0000-0000-0000-0000-000000000099"))
        assert devices == ()

    def test_does_not_cross_salon_boundary(self) -> None:
        """Isolation §11.2 : les bornes du salon A ne sont pas visibles depuis le salon B."""
        repo = _FakeKioskDeviceRepo()
        repo.create(KioskDeviceToCreate(salon_id=_SALON_ID, label="Borne A", password_hash="h"))
        uc = ListKioskDevices(repository=repo)
        assert uc.execute(_OTHER_SALON) == ()

    def test_returns_tuple(self) -> None:
        repo = _FakeKioskDeviceRepo()
        uc = ListKioskDevices(repository=repo)
        assert isinstance(uc.execute(_SALON_ID), tuple)


# ---------------------------------------------------------------------------
# RevokeKioskDevice
# ---------------------------------------------------------------------------


class TestRevokeKioskDevice:
    def _provisioned_repo(self) -> _FakeKioskDeviceRepo:
        """Repo avec une borne pré-provisionnée dans `_SALON_ID`."""
        repo = _FakeKioskDeviceRepo()
        repo.create(KioskDeviceToCreate(salon_id=_SALON_ID, label="Borne test", password_hash="h"))
        return repo

    def _make(
        self,
        repo: _FakeKioskDeviceRepo | None = None,
        log: FakeAuditLog | None = None,
    ) -> tuple[RevokeKioskDevice, _FakeKioskDeviceRepo, FakeAuditLog]:
        _repo = repo or self._provisioned_repo()
        _log = log or FakeAuditLog()
        uc = RevokeKioskDevice(repository=_repo, audit_log=_log)
        return uc, _repo, _log

    # --- Parcours heureux ---

    def test_happy_path_returns_device(self) -> None:
        uc, _repo, _log = self._make()
        device = uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert device.id == _DEVICE_ID

    def test_one_audit_entry_logged(self) -> None:
        uc, _repo, log = self._make()
        uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert len(log.recorded) == 1

    def test_audit_action_is_kiosk_device_revoked(self) -> None:
        uc, _repo, log = self._make()
        uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert log.recorded[0].action == AuditAction.KIOSK_DEVICE_REVOKED.value

    def test_audit_entity_type_is_kiosk_device(self) -> None:
        uc, _repo, log = self._make()
        uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert log.recorded[0].entity_type == ENTITY_TYPE_KIOSK_DEVICE

    def test_audit_metadata_is_empty(self) -> None:
        """Invariant §11.3/§11.4 : ni secret, ni libellé au journal de révocation."""
        uc, _repo, log = self._make()
        uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert log.recorded[0].metadata == {}

    def test_audit_actor_user_id_matches(self) -> None:
        uc, _repo, log = self._make()
        uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert log.recorded[0].actor_user_id == _ACTOR_ID

    def test_audit_salon_id_matches(self) -> None:
        uc, _repo, log = self._make()
        uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert log.recorded[0].salon_id == _SALON_ID

    # --- Borne hors salon / inexistante (aucun oracle §11.2) ---

    def test_unknown_device_raises_kiosk_device_not_found(self) -> None:
        """Borne inexistante → `KioskDeviceNotFound` (après portée, §11.2)."""
        repo = _FakeKioskDeviceRepo()  # aucune borne provisionnée
        uc, _repo, _log = self._make(repo=repo)
        with pytest.raises(KioskDeviceNotFound):
            uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)

    def test_device_in_other_salon_raises_kiosk_device_not_found(self) -> None:
        """Borne d'un autre salon → indiscernable d'une borne inexistante (§11.2)."""
        repo = _FakeKioskDeviceRepo()
        repo.create(KioskDeviceToCreate(salon_id=_OTHER_SALON, label="Borne B", password_hash="h"))
        uc, _repo, _log = self._make(repo=repo)
        with pytest.raises(KioskDeviceNotFound):
            # Tente de révoquer la borne de _OTHER_SALON en ciblant _SALON_ID → refusé.
            uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)

    def test_not_found_no_audit_logged(self) -> None:
        """Aucun audit si la borne est introuvable (pas de trace partielle)."""
        repo = _FakeKioskDeviceRepo()
        log = FakeAuditLog()
        uc, _repo, _log = self._make(repo=repo, log=log)
        with pytest.raises(KioskDeviceNotFound):
            uc.execute(_SALON_ID, _DEVICE_ID, actor_user_id=_ACTOR_ID)
        assert _log.recorded == []
