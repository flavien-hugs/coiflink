"""Tests unitaires pour le cas d'usage `RegisterClient` (#8).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base de
données, pas de hachage réel, pas de SMS. On vérifie ici l'orchestration
applicative, les garde-fous de sécurité (clair jamais persisté) et le
comportement sur doublon — y compris le fallback `IntegrityError` concurrente.
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
    RoleNotSelfRegisterable,
)
from coiflink_api.domain.user import SELF_REGISTERABLE_ROLES

from .conftest import (
    FakeHasher,
    FakeOtpRepository,
    FakeOtpSender,
    FakeUserRepository,
    FakeUserRepositoryRaisingDuplicate,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_FIXED_RNG = Random(42)

_VALID_COMMAND = RegisterCommand(
    full_name="Awa Koné",
    phone="0700000000",
    password="motdepasse-solide",
    email=None,
)


def _create_usecase(
    repository: FakeUserRepository | FakeUserRepositoryRaisingDuplicate | None = None,
    hasher: FakeHasher | None = None,
    otp_enabled: bool = False,
    sender: FakeOtpSender | None = None,
    otp_repository: FakeOtpRepository | None = None,
) -> RegisterClient:
    return RegisterClient(
        repository=repository or FakeUserRepository(),
        hasher=hasher or FakeHasher(),
        otp_enabled=otp_enabled,
        otp_sender=sender,
        otp_repository=otp_repository,
        rng=Random(42),
        clock=lambda: _NOW,
    )


class TestSuccessfulRegistration:
    def test_returns_user_with_client_role(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.role == Role.CLIENT.value

    def test_returns_user_with_active_status(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.status == UserStatus.ACTIVE.value

    def test_returns_normalized_name(self) -> None:
        uc = _create_usecase()
        command = RegisterCommand(
            full_name="  Awa Koné  ",
            phone="0700000000",
            password="motdepasse-solide",
        )
        user = uc.execute(command)
        assert user.full_name == "Awa Koné"

    def test_returns_canonical_phone(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        # 0700000000 doit être normalisé en E.164
        assert user.phone == "+2250700000000"

    def test_email_none_when_not_provided(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.email is None

    def test_email_passed_through_when_provided(self) -> None:
        uc = _create_usecase()
        command = RegisterCommand(
            full_name="Awa Koné",
            phone="0700000000",
            password="motdepasse-solide",
            email="awa@example.com",
        )
        user = uc.execute(command)
        assert user.email == "awa@example.com"

    def test_user_contains_no_secret(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        # L'entité retournée ne doit exposer ni le clair ni le condensat
        assert not hasattr(user, "mot_de_passe")
        assert not hasattr(user, "password")
        assert not hasattr(user, "password_hash")


class TestPasswordNotPersisted:
    def test_repository_receives_hash_not_plaintext(self) -> None:
        repository = FakeUserRepository()
        hasher = FakeHasher()
        plain_password = "motdepasse-solide"
        uc = _create_usecase(repository=repository, hasher=hasher)
        uc.execute(_VALID_COMMAND)

        assert len(repository.created) == 1
        assert repository.created[0].password_hash != plain_password
        assert repository.created[0].password_hash == hasher.hash(plain_password)

    def test_repository_never_stores_plaintext_password(self) -> None:
        repository = FakeUserRepository()
        plain_password = "motdepasse-solide"
        uc = _create_usecase(repository=repository)
        uc.execute(_VALID_COMMAND)

        assert repository.created[0].password_hash != plain_password


class TestDuplicatePhone:
    def test_duplicate_via_precheck_raises_phone_already_in_use(self) -> None:
        # Téléphone déjà normalisé dans le dépôt
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = _create_usecase(repository=repository)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_duplicate_via_integrity_error_fallback_raises_phone_already_in_use(self) -> None:
        """Simule un repository.create() levant PhoneAlreadyInUse (race condition)."""
        repository = FakeUserRepositoryRaisingDuplicate()
        uc = _create_usecase(repository=repository)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_local_0_and_e164_detected_as_same_duplicate(self) -> None:
        """0700000000 et +2250700000000 produisent la même forme E.164 → doublon détecté."""
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = _create_usecase(repository=repository)
        local_command = RegisterCommand(
            full_name="Autre",
            phone="0700000000",  # format local
            password="motdepasse-solide",
        )
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(local_command)


class TestInputValidation:
    def test_empty_name_raises_invalid_name(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidName):
            uc.execute(
                RegisterCommand(full_name="", phone="0700000000", password="motdepasse-ok")
            )

    def test_whitespace_only_name_raises_invalid_name(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidName):
            uc.execute(
                RegisterCommand(full_name="   ", phone="0700000000", password="motdepasse-ok")
            )

    def test_too_short_password_raises_invalid_password(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidPassword):
            uc.execute(
                RegisterCommand(full_name="Awa", phone="0700000000", password="court")
            )

    def test_invalid_phone_raises_invalid_phone(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidPhone):
            uc.execute(
                RegisterCommand(full_name="Awa", phone="abc", password="motdepasse-ok")
            )

    def test_empty_phone_raises_invalid_phone(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidPhone):
            uc.execute(
                RegisterCommand(full_name="Awa", phone="", password="motdepasse-ok")
            )


class TestEmailNormalization:
    def test_empty_email_stored_as_none(self) -> None:
        """email='' est falsy → l'inscription le stocke comme None."""
        uc = _create_usecase()
        command = RegisterCommand(
            full_name="Awa Koné",
            phone="0700000000",
            password="motdepasse-solide",
            email="",
        )
        user = uc.execute(command)
        assert user.email is None


class TestDuplicateMessageSecurity:
    def test_duplicate_message_does_not_contain_phone(self) -> None:
        """PhoneAlreadyInUse ne doit pas fuiter le numéro (PRD §11.1)."""
        phone = "0700000000"
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = _create_usecase(repository=repository)
        try:
            uc.execute(
                RegisterCommand(
                    full_name="Awa Koné",
                    phone=phone,
                    password="motdepasse-solide",
                )
            )
        except Exception as exc:  # noqa: BLE001
            assert phone not in str(exc)
            assert "+2250700000000" not in str(exc)


class TestOtp:
    def test_otp_not_sent_when_disabled(self) -> None:
        sender = FakeOtpSender()
        uc = _create_usecase(otp_enabled=False, sender=sender)
        uc.execute(_VALID_COMMAND)
        assert sender.sent == []

    def test_otp_sent_when_enabled(self) -> None:
        sender = FakeOtpSender()
        uc = _create_usecase(otp_enabled=True, sender=sender)
        uc.execute(_VALID_COMMAND)
        assert len(sender.sent) == 1

    def test_otp_sent_to_correct_phone(self) -> None:
        sender = FakeOtpSender()
        uc = _create_usecase(otp_enabled=True, sender=sender)
        uc.execute(_VALID_COMMAND)
        sent_phone, _ = sender.sent[0]
        assert sent_phone == "+2250700000000"

    def test_otp_saved_in_repository_when_enabled(self) -> None:
        otp_repository = FakeOtpRepository()
        uc = _create_usecase(otp_enabled=True, otp_repository=otp_repository)
        uc.execute(_VALID_COMMAND)
        assert otp_repository.get("+2250700000000") is not None

    def test_otp_not_saved_when_disabled(self) -> None:
        otp_repository = FakeOtpRepository()
        uc = _create_usecase(otp_enabled=False, otp_repository=otp_repository)
        uc.execute(_VALID_COMMAND)
        assert otp_repository.get("+2250700000000") is None

    def test_returned_user_contains_no_otp(self) -> None:
        sender = FakeOtpSender()
        uc = _create_usecase(otp_enabled=True, sender=sender)
        user = uc.execute(_VALID_COMMAND)
        assert not hasattr(user, "otp")
        assert not hasattr(user, "code_otp")


class TestOtpCustomParameters:
    def test_custom_otp_length_applied(self) -> None:
        """otp_length=4 → le défi stocké a un code de 4 chiffres."""
        otp_repository = FakeOtpRepository()
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            otp_enabled=True,
            otp_repository=otp_repository,
            rng=Random(42),
            clock=lambda: _NOW,
            otp_length=4,
        )
        uc.execute(_VALID_COMMAND)
        challenge = otp_repository.get("+2250700000000")
        assert challenge is not None
        assert len(challenge.code) == 4

    def test_custom_otp_ttl_applied(self) -> None:
        """otp_ttl custom → expires_at = now + ttl custom."""
        otp_repository = FakeOtpRepository()
        custom_ttl = datetime.timedelta(minutes=10)
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            otp_enabled=True,
            otp_repository=otp_repository,
            rng=Random(42),
            clock=lambda: _NOW,
            otp_ttl=custom_ttl,
        )
        uc.execute(_VALID_COMMAND)
        challenge = otp_repository.get("+2250700000000")
        assert challenge is not None
        assert challenge.expires_at == _NOW + custom_ttl

    def test_custom_otp_max_attempts_applied(self) -> None:
        """otp_max_attempts=5 → attempts_left == 5 dans le défi."""
        otp_repository = FakeOtpRepository()
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            otp_enabled=True,
            otp_repository=otp_repository,
            rng=Random(42),
            clock=lambda: _NOW,
            otp_max_attempts=5,
        )
        uc.execute(_VALID_COMMAND)
        challenge = otp_repository.get("+2250700000000")
        assert challenge is not None
        assert challenge.attempts_left == 5


class TestOtpWithoutFullInfrastructure:
    def test_otp_enabled_without_otp_repository_does_not_crash(self) -> None:
        """Seul l'expéditeur est fourni : l'inscription doit quand même réussir."""
        sender = FakeOtpSender()
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            otp_enabled=True,
            otp_sender=sender,
            otp_repository=None,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        uc.execute(_VALID_COMMAND)
        assert len(sender.sent) == 1

    def test_otp_enabled_without_sender_does_not_crash(self) -> None:
        """Seul le dépôt OTP est fourni : l'inscription doit quand même réussir."""
        otp_repository = FakeOtpRepository()
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            otp_enabled=True,
            otp_sender=None,
            otp_repository=otp_repository,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        uc.execute(_VALID_COMMAND)
        assert otp_repository.get("+2250700000000") is not None

    def test_otp_enabled_without_repository_or_sender_does_not_crash(self) -> None:
        """Ni dépôt ni expéditeur : l'OTP est généré en mémoire sans effet de bord."""
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            otp_enabled=True,
            otp_sender=None,
            otp_repository=None,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        user = uc.execute(_VALID_COMMAND)
        assert user is not None


class TestManagerRegistration:
    """Tests du cas d'usage RegisterUser pour le rôle MANAGER (issue #9)."""

    def test_returns_user_with_manager_role(self) -> None:
        uc = RegisterUser(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            role=Role.MANAGER,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        user = uc.execute(_VALID_COMMAND)
        assert user.role == Role.MANAGER.value

    def test_returns_user_with_active_status(self) -> None:
        uc = RegisterUser(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            role=Role.MANAGER,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        user = uc.execute(_VALID_COMMAND)
        assert user.status == UserStatus.ACTIVE.value

    def test_manager_password_not_stored_as_plaintext(self) -> None:
        repository = FakeUserRepository()
        hasher = FakeHasher()
        uc = RegisterUser(
            repository=repository,
            hasher=hasher,
            role=Role.MANAGER,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        plain = "motdepasse-solide"
        uc.execute(_VALID_COMMAND)
        assert repository.created[0].password_hash != plain
        assert repository.created[0].password_hash == hasher.hash(plain)

    def test_manager_phone_normalized_to_e164(self) -> None:
        uc = RegisterUser(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            role=Role.MANAGER,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        user = uc.execute(_VALID_COMMAND)
        assert user.phone == "+2250700000000"

    def test_manager_duplicate_phone_raises_phone_already_in_use(self) -> None:
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = RegisterUser(
            repository=repository,
            hasher=FakeHasher(),
            role=Role.MANAGER,
        )
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_manager_user_contains_no_secret(self) -> None:
        uc = RegisterUser(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            role=Role.MANAGER,
            rng=Random(42),
            clock=lambda: _NOW,
        )
        user = uc.execute(_VALID_COMMAND)
        assert not hasattr(user, "password")
        assert not hasattr(user, "password_hash")


class TestSelfRegisterableRoles:
    """Tests du garde-fou domaine : liste blanche des rôles auto-inscriptibles."""

    def test_client_role_is_self_registerable(self) -> None:
        assert Role.CLIENT in SELF_REGISTERABLE_ROLES

    def test_manager_role_is_self_registerable(self) -> None:
        assert Role.MANAGER in SELF_REGISTERABLE_ROLES

    def test_admin_role_is_not_self_registerable(self) -> None:
        assert Role.ADMIN not in SELF_REGISTERABLE_ROLES

    def test_hairdresser_role_is_not_self_registerable(self) -> None:
        assert Role.HAIRDRESSER not in SELF_REGISTERABLE_ROLES

    def test_register_user_with_admin_raises_role_not_self_registerable(self) -> None:
        with pytest.raises(RoleNotSelfRegisterable):
            RegisterUser(
                repository=FakeUserRepository(),
                hasher=FakeHasher(),
                role=Role.ADMIN,
            )

    def test_register_user_with_hairdresser_raises_role_not_self_registerable(self) -> None:
        with pytest.raises(RoleNotSelfRegisterable):
            RegisterUser(
                repository=FakeUserRepository(),
                hasher=FakeHasher(),
                role=Role.HAIRDRESSER,
            )


class TestRegisterClientAlias:
    """Non-régression : RegisterClient reste un alias de RegisterUser (compat #8)."""

    def test_register_client_alias_creates_client_role(self) -> None:
        uc = RegisterClient(
            repository=FakeUserRepository(),
            hasher=FakeHasher(),
            rng=Random(42),
            clock=lambda: _NOW,
        )
        user = uc.execute(_VALID_COMMAND)
        assert user.role == Role.CLIENT.value

    def test_register_client_and_register_user_are_same_class(self) -> None:
        assert RegisterClient is RegisterUser
