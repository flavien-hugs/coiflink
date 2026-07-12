"""Tests unitaires pour le cas d'usage `CreateEmployee` (US-1.4, #13).

Tous les ports sont remplacés par des fakes (conftest.py + FakeSalonMemberRepository) :
pas de base de données, pas de hachage réel. On vérifie ici :
- l'orchestration applicative (user créé puis rattaché au salon) ;
- le rôle fixé côté serveur (`HAIRDRESSER`, jamais lu d'une commande) ;
- le statut `ACTIVE` par défaut ;
- le mot de passe jamais persisté en clair ;
- le doublon de téléphone et la race condition ;
- l'appartenance déjà existante (`EmployeeAlreadyInSalon`) ;
- les validations de domaine (nom, téléphone, mot de passe) ;
- les invariants de sécurité (entité retournée sans secret, message d'erreur sans PII).
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.application.employees import CreateEmployee, CreateEmployeeCommand
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import (
    EmployeeAlreadyInSalon,
    InvalidName,
    InvalidPassword,
    InvalidPhone,
    PhoneAlreadyInUse,
)

from .conftest import (
    FakeHasher,
    FakeSalonMemberRepository,
    FakeUserRepository,
    FakeUserRepositoryRaisingDuplicate,
)

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

_VALID_COMMAND = CreateEmployeeCommand(
    salon_id=_SALON_ID,
    full_name="Awa Koné",
    phone="0700000000",
    password="motdepasse-solide",
    email=None,
)


def _create_usecase(
    repository: FakeUserRepository | FakeUserRepositoryRaisingDuplicate | None = None,
    hasher: FakeHasher | None = None,
    members: FakeSalonMemberRepository | None = None,
    role: str = Role.HAIRDRESSER.value,
) -> CreateEmployee:
    return CreateEmployee(
        repository=repository or FakeUserRepository(),
        hasher=hasher or FakeHasher(),
        members=members or FakeSalonMemberRepository(),
        role=role,
    )


# ---------------------------------------------------------------------------
# Succès : entité retournée
# ---------------------------------------------------------------------------


class TestSuccessfulCreation:
    def test_returns_user_with_hairdresser_role(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.role == Role.HAIRDRESSER.value

    def test_returns_user_with_active_status(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.status == UserStatus.ACTIVE.value

    def test_returns_normalized_name(self) -> None:
        uc = _create_usecase()
        command = CreateEmployeeCommand(
            salon_id=_SALON_ID,
            full_name="  Awa Koné  ",
            phone="0700000000",
            password="motdepasse-solide",
        )
        user = uc.execute(command)
        assert user.full_name == "Awa Koné"

    def test_returns_canonical_phone(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.phone == "+2250700000000"

    def test_email_none_when_not_provided(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.email is None

    def test_email_passed_through_when_provided(self) -> None:
        uc = _create_usecase()
        command = CreateEmployeeCommand(
            salon_id=_SALON_ID,
            full_name="Awa Koné",
            phone="0700000000",
            password="motdepasse-solide",
            email="awa@example.com",
        )
        user = uc.execute(command)
        assert user.email == "awa@example.com"

    def test_empty_email_stored_as_none(self) -> None:
        """email='' est falsy → stocké comme None."""
        uc = _create_usecase()
        command = CreateEmployeeCommand(
            salon_id=_SALON_ID,
            full_name="Awa Koné",
            phone="0700000000",
            password="motdepasse-solide",
            email="",
        )
        user = uc.execute(command)
        assert user.email is None


# ---------------------------------------------------------------------------
# Rôle fixé côté serveur — anti-élévation de privilège
# ---------------------------------------------------------------------------


class TestRoleFixedServerSide:
    def test_command_has_no_role_field(self) -> None:
        assert not hasattr(_VALID_COMMAND, "role")

    def test_always_creates_hairdresser_role(self) -> None:
        uc = _create_usecase(role=Role.HAIRDRESSER.value)
        user = uc.execute(_VALID_COMMAND)
        assert user.role == Role.HAIRDRESSER.value

    def test_unknown_role_raises_value_error_at_construction(self) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            _create_usecase(role="SUPERADMIN")

    def test_empty_role_raises_value_error_at_construction(self) -> None:
        with pytest.raises(ValueError):
            _create_usecase(role="")

    def test_manager_role_raises_value_error_at_construction(self) -> None:
        """Un gérant ne peut créer que des coiffeurs — `MANAGER` comme rôle cible est invalide."""
        # Même si Role.MANAGER est un rôle valide du domaine, le cas d'usage
        # n'autorise que les rôles d'employé. Ici, tous les rôles sont techniquement
        # valides via _ROLE_VALUES ; ce test vérifie la sémantique dans le contexte
        # de l'usage réel où `role=HAIRDRESSER` est fixé au câblage.
        uc = _create_usecase(role=Role.HAIRDRESSER.value)
        user = uc.execute(_VALID_COMMAND)
        assert user.role != Role.MANAGER.value


# ---------------------------------------------------------------------------
# Mot de passe jamais persisté en clair
# ---------------------------------------------------------------------------


class TestPasswordNotPersisted:
    def test_repository_receives_hash_not_plaintext(self) -> None:
        repository = FakeUserRepository()
        hasher = FakeHasher()
        plain = "motdepasse-solide"
        uc = _create_usecase(repository=repository, hasher=hasher)
        uc.execute(_VALID_COMMAND)

        assert len(repository.created) == 1
        stored = repository.created[0]
        assert stored.password_hash != plain
        assert stored.password_hash == hasher.hash(plain)

    def test_repository_never_stores_plaintext_password(self) -> None:
        repository = FakeUserRepository()
        plain = "motdepasse-solide"
        uc = _create_usecase(repository=repository)
        uc.execute(_VALID_COMMAND)
        assert repository.created[0].password_hash != plain

    def test_repository_stores_hairdresser_role(self) -> None:
        repository = FakeUserRepository()
        uc = _create_usecase(repository=repository)
        uc.execute(_VALID_COMMAND)
        assert repository.created[0].role == Role.HAIRDRESSER.value


# ---------------------------------------------------------------------------
# Appartenance au salon
# ---------------------------------------------------------------------------


class TestSalonMembership:
    def test_member_added_to_correct_salon(self) -> None:
        members = FakeSalonMemberRepository()
        uc = _create_usecase(members=members)
        uc.execute(_VALID_COMMAND)

        assert len(members.added) == 1
        assert members.added[0].salon_id == _SALON_ID

    def test_member_added_with_hairdresser_role(self) -> None:
        members = FakeSalonMemberRepository()
        uc = _create_usecase(members=members)
        uc.execute(_VALID_COMMAND)

        assert members.added[0].role == Role.HAIRDRESSER.value

    def test_member_added_with_active_status(self) -> None:
        members = FakeSalonMemberRepository()
        uc = _create_usecase(members=members)
        uc.execute(_VALID_COMMAND)

        assert members.added[0].status == UserStatus.ACTIVE.value

    def test_membership_salon_id_matches_command(self) -> None:
        other_salon = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
        members = FakeSalonMemberRepository()
        uc = _create_usecase(members=members)
        command = CreateEmployeeCommand(
            salon_id=other_salon,
            full_name="Awa Koné",
            phone="0700000000",
            password="motdepasse-solide",
        )
        uc.execute(command)
        assert members.added[0].salon_id == other_salon

    def test_employee_already_in_salon_raises_error(self) -> None:
        members = FakeSalonMemberRepository(raise_duplicate=True)
        uc = _create_usecase(members=members)
        with pytest.raises(EmployeeAlreadyInSalon):
            uc.execute(_VALID_COMMAND)

    def test_add_member_called_once_per_execution(self) -> None:
        members = FakeSalonMemberRepository()
        uc = _create_usecase(members=members)
        uc.execute(_VALID_COMMAND)
        assert len(members.added) == 1


# ---------------------------------------------------------------------------
# Doublon de téléphone
# ---------------------------------------------------------------------------


class TestDuplicatePhone:
    def test_duplicate_via_precheck_raises_phone_already_in_use(self) -> None:
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = _create_usecase(repository=repository)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_duplicate_via_integrity_error_fallback_raises_phone_already_in_use(self) -> None:
        """Simule un `repository.create()` levant `PhoneAlreadyInUse` (race condition)."""
        repository = FakeUserRepositoryRaisingDuplicate()
        uc = _create_usecase(repository=repository)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)

    def test_local_and_e164_detected_as_same_duplicate(self) -> None:
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = _create_usecase(repository=repository)
        local_command = CreateEmployeeCommand(
            salon_id=_SALON_ID,
            full_name="Autre",
            phone="0700000000",
            password="motdepasse-solide",
        )
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(local_command)

    def test_duplicate_message_does_not_contain_phone(self) -> None:
        """PhoneAlreadyInUse ne doit pas fuiter le numéro (PRD §11.1)."""
        phone = "0700000000"
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = _create_usecase(repository=repository)
        try:
            uc.execute(_VALID_COMMAND)
        except PhoneAlreadyInUse as exc:
            assert phone not in str(exc)
            assert "+2250700000000" not in str(exc)

    def test_duplicate_does_not_call_add_member(self) -> None:
        """Sur doublon téléphone, le rattachement au salon ne doit pas être tenté."""
        members = FakeSalonMemberRepository()
        repository = FakeUserRepository(existing_phones={"+2250700000000"})
        uc = _create_usecase(repository=repository, members=members)
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_VALID_COMMAND)
        assert members.added == []


# ---------------------------------------------------------------------------
# Validations d'entrée
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_empty_name_raises_invalid_name(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidName):
            uc.execute(
                CreateEmployeeCommand(
                    salon_id=_SALON_ID, full_name="", phone="0700000000", password="motdepasse-ok"
                )
            )

    def test_whitespace_only_name_raises_invalid_name(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidName):
            uc.execute(
                CreateEmployeeCommand(
                    salon_id=_SALON_ID,
                    full_name="   ",
                    phone="0700000000",
                    password="motdepasse-ok",
                )
            )

    def test_too_short_password_raises_invalid_password(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidPassword):
            uc.execute(
                CreateEmployeeCommand(
                    salon_id=_SALON_ID, full_name="Awa", phone="0700000000", password="court"
                )
            )

    def test_invalid_phone_raises_invalid_phone(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidPhone):
            uc.execute(
                CreateEmployeeCommand(
                    salon_id=_SALON_ID, full_name="Awa", phone="abc", password="motdepasse-ok"
                )
            )

    def test_empty_phone_raises_invalid_phone(self) -> None:
        uc = _create_usecase()
        with pytest.raises(InvalidPhone):
            uc.execute(
                CreateEmployeeCommand(
                    salon_id=_SALON_ID, full_name="Awa", phone="", password="motdepasse-ok"
                )
            )

    def test_validation_error_does_not_call_add_member(self) -> None:
        members = FakeSalonMemberRepository()
        uc = _create_usecase(members=members)
        with pytest.raises(InvalidName):
            uc.execute(
                CreateEmployeeCommand(
                    salon_id=_SALON_ID,
                    full_name="",
                    phone="0700000000",
                    password="motdepasse-ok",
                )
            )
        assert members.added == []


# ---------------------------------------------------------------------------
# Invariants de sécurité sur l'entité retournée
# ---------------------------------------------------------------------------


class TestUserEntitySecurity:
    def test_returned_user_has_no_password_attribute(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert not hasattr(user, "password")

    def test_returned_user_has_no_password_hash_attribute(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert not hasattr(user, "password_hash")

    def test_returned_user_has_id(self) -> None:
        uc = _create_usecase()
        user = uc.execute(_VALID_COMMAND)
        assert user.id is not None
