"""Tests unitaires pour `RegisterUser` avec `role=MANAGER` (#9).

Tous les ports sont remplacés par des fakes (conftest.py). Vérifie :
- rôle MANAGER attribué côté serveur, jamais depuis la commande ;
- statut ACTIVE, normalisation téléphone E.164, email optionnel ;
- mot de passe jamais persisté en clair ;
- doublon → PhoneAlreadyInUse (pré-check + fallback race condition) ;
- validations domaine (nom, téléphone, mot de passe) ;
- OTP émis/non-émis selon configuration ;
- rôle inconnu → ValueError à la construction du cas d'usage ;
- non-régression #8 : RegisterClient toujours role=CLIENT.
"""

from __future__ import annotations

import datetime
from random import Random

import pytest

from coiflink_api.application.registration import RegisterClient, RegisterCommand, RegisterUser
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import (
    InvalidName,
    InvalidPassword,
    InvalidPhone,
    PhoneAlreadyInUse,
)

from .conftest import (
    FakeHasher,
    FakeOtpRepository,
    FakeOtpSender,
    FakeUserRepository,
    FakeUserRepositoryRaisingDuplicate,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

_VALID_COMMAND = RegisterCommand(
    full_name="Koné Gérant",
    phone="0700000001",
    password="motdepasse-solide",
    email=None,
)


def _create_manager_usecase(
    repository: FakeUserRepository | FakeUserRepositoryRaisingDuplicate | None = None,
    hasher: FakeHasher | None = None,
    otp_enabled: bool = False,
    sender: FakeOtpSender | None = None,
    otp_repository: FakeOtpRepository | None = None,
) -> RegisterUser:
    return RegisterUser(
        repository=repository or FakeUserRepository(),
        hasher=hasher or FakeHasher(),
        role=Role.MANAGER.value,
        otp_enabled=otp_enabled,
        otp_sender=sender,
        otp_repository=otp_repository,
        rng=Random(42),
        clock=lambda: _NOW,
    )


class TestManagerRoleAssignment:
    def test_returns_user_with_manager_role(self) -> None:
        uc = _create_manager_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.role == Role.MANAGER.value

    def test_returns_user_with_active_status(self) -> None:
        uc = _create_manager_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.status == UserStatus.ACTIVE.value

    def test_role_is_manager_string(self) -> None:
        uc = _create_manager_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.role == "MANAGER"

    def test_returns_canonical_phone(self) -> None:
        uc = _create_manager_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.phone == "+2250700000001"

    def test_returns_normalized_name(self) -> None:
        uc = _create_manager_usecase()
        command = RegisterCommand(
            full_name="  Koné Gérant  ",
            phone="0700000001",
            password="motdepasse-solide",
        )
        user = uc.execute(command)
        assert user.full_name == "Koné Gérant"

    def test_email_none_when_not_provided(self) -> None:
        uc = _create_manager_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.email is None

    def test_email_passed_through_when_provided(self) -> None:
        uc = _create_manager_usecase()
        command = RegisterCommand(
            full_name="Koné Gérant",
            phone="0700000001",
            password="motdepasse-solide",
            email="gerant@salon.ci",
        )
        user = uc.execute(command)
        assert user.email == "gerant@salon.ci"

    def test_user_contains_no_secret(self) -> None:
        uc = _create_manager_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert not hasattr(user, "password")
        assert not hasattr(user, "password_hash")


class TestRoleFixedServerSide:
    """Le rôle est fixé au câblage — jamais depuis la commande (anti-élévation)."""

    def test_command_has_no_role_field(self) -> None:
        assert not hasattr(_VALID_COMMAND, "role")

    def test_manager_usecase_always_produces_manager_role(self) -> None:
        """Même si on tente d'instancier RegisterUser avec role=CLIENT, il fixe MANAGER."""
        uc = _create_manager_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.role == Role.MANAGER.value

    def test_unknown_role_raises_value_error_at_construction(self) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            RegisterUser(
                repository=FakeUserRepository(),
                hasher=FakeHasher(),
                role="SUPERADMIN",
            )

    def test_empty_role_raises_value_error_at_construction(self) -> None:
        with pytest.raises(ValueError):
            RegisterUser(
                repository=FakeUserRepository(),
                hasher=FakeHasher(),
                role="",
            )


class TestPasswordNotPersisted:
    def test_repository_receives_hash_not_plaintext(self) -> None:
        repository = FakeUserRepository()
        hasher = FakeHasher()
        plain = "motdepasse-solide"
        uc = _create_manager_usecase(repository=repository, hasher=hasher)
        uc.execute(_VALID_COMMAND)

        assert len(repository.created) == 1
        stored = repository.created[0]
        assert stored.password_hash != plain
        assert stored.password_hash == hasher.hash(plain)

    def test_repository_never_stores_plaintext_password(self) -> None:
        repository = FakeUserRepository()
        uc = _create_manager_usecase(repository=repository)
        uc.execute(_VALID_COMMAND)
        assert repository.created[0].password_hash != "motdepasse-solide"

    def test_repository_stores_manager_role(self) -> None:
        repository = FakeUserRepository()
        uc = _create_manager_usecase(repository=repository)
        uc.execute(_VALID_COMMAND)
        assert repository.created[0].role == Role.MANAGER.value


class TestDuplicatePhone:
    def test_duplicate_via_precheck_raises_phone_already_in_use(self) -> None:
        repository = FakeUserRepository(existing_phones={"+2250700000001"})
        uc = _create_manager_usecase(repository=repository)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_duplicate_via_integrity_error_fallback_raises_phone_already_in_use(self) -> None:
        repository = FakeUserRepositoryRaisingDuplicate()
        uc = _create_manager_usecase(repository=repository)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_local_and_e164_detected_as_same_duplicate(self) -> None:
        repository = FakeUserRepository(existing_phones={"+2250700000001"})
        uc = _create_manager_usecase(repository=repository)
        local_command = RegisterCommand(
            full_name="Autre",
            phone="0700000001",
            password="motdepasse-solide",
        )
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(local_command)

    def test_manager_duplicate_of_existing_client_phone_rejected(self) -> None:
        """Un téléphone déjà utilisé par un CLIENT est refusé pour un MANAGER."""
        repository = FakeUserRepository(existing_phones={"+2250700000001"})
        uc = _create_manager_usecase(repository=repository)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_duplicate_message_does_not_contain_phone(self) -> None:
        phone = "0700000001"
        repository = FakeUserRepository(existing_phones={"+2250700000001"})
        uc = _create_manager_usecase(repository=repository)
        try:
            uc.execute(
                RegisterCommand(
                    full_name="Koné Gérant",
                    phone=phone,
                    password="motdepasse-solide",
                )
            )
        except PhoneAlreadyInUse as exc:
            assert phone not in str(exc)
            assert "+2250700000001" not in str(exc)


class TestInputValidation:
    def test_empty_name_raises_invalid_name(self) -> None:
        uc = _create_manager_usecase()
        with pytest.raises(InvalidName):
            uc.execute(RegisterCommand(full_name="", phone="0700000001", password="motdepasse-ok"))

    def test_whitespace_only_name_raises_invalid_name(self) -> None:
        uc = _create_manager_usecase()
        with pytest.raises(InvalidName):
            uc.execute(
                RegisterCommand(full_name="   ", phone="0700000001", password="motdepasse-ok")
            )

    def test_too_short_password_raises_invalid_password(self) -> None:
        uc = _create_manager_usecase()
        with pytest.raises(InvalidPassword):
            uc.execute(RegisterCommand(full_name="Gérant", phone="0700000001", password="court"))

    def test_invalid_phone_raises_invalid_phone(self) -> None:
        uc = _create_manager_usecase()
        with pytest.raises(InvalidPhone):
            uc.execute(RegisterCommand(full_name="Gérant", phone="abc", password="motdepasse-ok"))

    def test_empty_phone_raises_invalid_phone(self) -> None:
        uc = _create_manager_usecase()
        with pytest.raises(InvalidPhone):
            uc.execute(RegisterCommand(full_name="Gérant", phone="", password="motdepasse-ok"))


class TestOtp:
    def test_otp_not_sent_when_disabled(self) -> None:
        sender = FakeOtpSender()
        uc = _create_manager_usecase(otp_enabled=False, sender=sender)
        uc.execute(_VALID_COMMAND)
        assert sender.sent == []

    def test_otp_sent_when_enabled(self) -> None:
        sender = FakeOtpSender()
        uc = _create_manager_usecase(otp_enabled=True, sender=sender)
        uc.execute(_VALID_COMMAND)
        assert len(sender.sent) == 1

    def test_otp_sent_to_canonical_phone(self) -> None:
        sender = FakeOtpSender()
        uc = _create_manager_usecase(otp_enabled=True, sender=sender)
        uc.execute(_VALID_COMMAND)
        sent_phone, _ = sender.sent[0]
        assert sent_phone == "+2250700000001"

    def test_otp_saved_in_repository_when_enabled(self) -> None:
        otp_repository = FakeOtpRepository()
        uc = _create_manager_usecase(otp_enabled=True, otp_repository=otp_repository)
        uc.execute(_VALID_COMMAND)
        assert otp_repository.get("+2250700000001") is not None

    def test_otp_not_saved_when_disabled(self) -> None:
        otp_repository = FakeOtpRepository()
        uc = _create_manager_usecase(otp_enabled=False, otp_repository=otp_repository)
        uc.execute(_VALID_COMMAND)
        assert otp_repository.get("+2250700000001") is None

    def test_returned_user_contains_no_otp(self) -> None:
        sender = FakeOtpSender()
        uc = _create_manager_usecase(otp_enabled=True, sender=sender)
        user = uc.execute(_VALID_COMMAND)
        assert not hasattr(user, "otp")
        assert not hasattr(user, "code_otp")


class TestNonRegressionClientRole:
    """#8 non-régression : RegisterClient produit toujours role=CLIENT."""

    def test_register_client_still_produces_client_role(self) -> None:
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            rng=Random(42),
            clock=lambda: _NOW,
        )
        command = RegisterCommand(
            full_name="Awa Koné",
            phone="0700000002",
            password="motdepasse-solide",
        )
        user = uc.execute(command)
        assert user.role == Role.CLIENT.value

    def test_client_and_manager_usecases_are_independent(self) -> None:
        repository = FakeUserRepository()
        client_uc = RegisterClient(
            repository=repository,
            hasher=FakeHasher(),
            rng=Random(42),
            clock=lambda: _NOW,
        )
        manager_uc = RegisterUser(
            repository=repository,
            hasher=FakeHasher(),
            role=Role.MANAGER.value,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        client_user = client_uc.execute(
            RegisterCommand(full_name="Client", phone="0700000002", password="motdepasse-solide")
        )
        manager_user = manager_uc.execute(
            RegisterCommand(full_name="Gérant", phone="0700000003", password="motdepasse-solide")
        )
        assert client_user.role == Role.CLIENT.value
        assert manager_user.role == Role.MANAGER.value
