"""Tests d'intégration PostgreSQL — inscription gérant (issue #9).

Nécessite une base PostgreSQL accessible via ``DATABASE_URL``.
Skippés proprement si ``DATABASE_URL`` est absent ou vide (CI sans base,
environnement de dev sans Docker).

Ces tests croisent deux composants réels :
- ``SqlUserRepository`` (adapter sortant SQLAlchemy) ;
- PostgreSQL 16 (contraintes ``ck_users_role``, ``uq_users_phone``).

Ils vérifient la couche de persistance que les tests API/use-case couvrent avec
des fakes : que le rôle ``MANAGER`` est bien accepté par la contrainte base, que
le condensat est stocké (jamais le mot de passe en clair), et que la contrainte
``uq_users_phone`` rejette les doublons au niveau base (fallback *race condition*).

La table ``users`` est créée avant les tests et supprimée après. Chaque test
opère dans une session qui revient en arrière (``rollback``) en fin de test :
aucune donnée de test n'est committée en base.
"""

from __future__ import annotations

import datetime
import os

import pytest

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="DATABASE_URL non défini — tests d'intégration Postgres ignorés",
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def pg_engine():
    """Engine SQLAlchemy pointant vers la base de test ; crée la table users."""
    from sqlalchemy import create_engine

    from coiflink_api.adapters.outbound.persistence import models as orm_models
    from coiflink_api.adapters.outbound.persistence.session import normalize_dsn

    engine = create_engine(normalize_dsn(_DATABASE_URL))
    orm_models.User.__table__.create(engine, checkfirst=True)
    yield engine
    orm_models.User.__table__.drop(engine, checkfirst=True)
    engine.dispose()


@pytest.fixture()
def pg_session(pg_engine):
    """Session SQLAlchemy dont la transaction est annulée après chaque test."""
    from sqlalchemy.orm import Session

    session = Session(pg_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def repository(pg_session):
    from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository

    return SqlUserRepository(pg_session)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _manager_to_create(
    phone: str = "+2250700000099",
    password_hash: str = "hash:motdepasse-test",
):
    """Retourne un ``UserToCreate`` gérant prêt à être persisté."""
    from coiflink_api.domain.enums import Role, UserStatus
    from coiflink_api.domain.user import UserToCreate

    return UserToCreate(
        full_name="Sidikat Koné",
        phone=phone,
        password_hash=password_hash,
        role=Role.MANAGER.value,
        status=UserStatus.ACTIVE.value,
    )


# --------------------------------------------------------------------------- #
# Tests de persistance via SqlUserRepository
# --------------------------------------------------------------------------- #


class TestManagerPersistenceIntegration:
    """SqlUserRepository avec PostgreSQL réel : contraintes et valeurs persistées."""

    def test_manager_role_accepted_by_ck_users_role(self, repository) -> None:
        """La contrainte ``ck_users_role`` accepte la valeur MANAGER sans lever d'erreur."""
        user = repository.create(_manager_to_create())
        assert user.role == "MANAGER"

    def test_manager_status_is_active(self, repository) -> None:
        user = repository.create(_manager_to_create())
        assert user.status == "ACTIVE"

    def test_manager_gets_server_generated_uuid(self, repository) -> None:
        user = repository.create(_manager_to_create())
        assert user.id is not None

    def test_manager_gets_server_generated_created_at(self, repository) -> None:
        user = repository.create(_manager_to_create())
        assert isinstance(user.created_at, datetime.datetime)

    def test_manager_phone_stored_as_e164(self, repository) -> None:
        user = repository.create(_manager_to_create(phone="+2250700000099"))
        assert user.phone == "+2250700000099"

    def test_password_hash_stored_not_plaintext(self, repository, pg_session) -> None:
        """Le condensat persisté en base ne correspond jamais au mot de passe en clair."""
        from sqlalchemy import select

        from coiflink_api.adapters.outbound.persistence import models as orm_models

        plaintext = "motdepasse-test"
        user = repository.create(_manager_to_create(password_hash=f"hash:{plaintext}"))

        stored = pg_session.scalar(
            select(orm_models.User.password_hash).where(orm_models.User.id == user.id)
        )
        assert stored is not None
        assert stored != plaintext
        assert stored == f"hash:{plaintext}"

    def test_entity_returned_exposes_no_secret(self, repository) -> None:
        """L'entité ``User`` retournée par le dépôt n'expose pas ``password_hash``."""
        user = repository.create(_manager_to_create())
        assert not hasattr(user, "password_hash")
        assert not hasattr(user, "password")


# --------------------------------------------------------------------------- #
# Tests de la contrainte d'unicité du téléphone
# --------------------------------------------------------------------------- #


class TestManagerPhoneUniquenessConstraint:
    """``uq_users_phone`` : doublon rejeté au niveau base (fallback race condition)."""

    def test_duplicate_phone_raises_phone_already_in_use(self, repository) -> None:
        """Le second INSERT sur le même téléphone lève ``PhoneAlreadyInUse``."""
        from coiflink_api.domain.errors import PhoneAlreadyInUse

        repository.create(_manager_to_create(phone="+2250700000099"))
        with pytest.raises(PhoneAlreadyInUse):
            repository.create(_manager_to_create(phone="+2250700000099"))

    def test_phone_exists_true_after_flush(self, repository) -> None:
        """``phone_exists`` reflète l'INSERT flushed dans la session courante."""
        repository.create(_manager_to_create(phone="+2250700000099"))
        assert repository.phone_exists("+2250700000099") is True

    def test_phone_exists_false_for_unknown_phone(self, repository) -> None:
        assert repository.phone_exists("+2250700000000") is False

    def test_two_managers_with_distinct_phones_both_accepted(self, repository) -> None:
        """Deux gérants avec des numéros différents coexistent sans erreur de contrainte."""
        repository.create(_manager_to_create(phone="+2250700000097"))
        repository.create(_manager_to_create(phone="+2250700000098"))


# --------------------------------------------------------------------------- #
# Test d'intégration du cas d'usage complet
# --------------------------------------------------------------------------- #


class TestManagerUseCaseWithRealDatabase:
    """``RegisterUser`` + ``SqlUserRepository`` réel : flux complet d'inscription gérant.

    Utilise ``FakeHasher`` (déterministe, rapide) pour isoler l'intégration de
    la persistance de la performance argon2id — la conformité du hachage réel est
    couverte séparément par ``test_password_hasher.py``.
    """

    def test_full_registration_persists_manager(self, pg_session) -> None:
        """Le cas d'usage complet persiste un compte MANAGER et normalise le téléphone."""
        from sqlalchemy import select

        from coiflink_api.adapters.outbound.persistence import models as orm_models
        from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository
        from coiflink_api.application.registration import RegisterCommand, RegisterUser
        from coiflink_api.domain.enums import Role

        from .conftest import FakeHasher

        plain = "motdepasse-solide"
        usecase = RegisterUser(
            repository=SqlUserRepository(pg_session),
            hasher=FakeHasher(),
            role=Role.MANAGER,
        )
        user = usecase.execute(
            RegisterCommand(
                full_name="  Moussa Traoré  ",
                phone="0700000099",
                password=plain,
            )
        )

        assert user.role == Role.MANAGER.value
        assert user.status == "ACTIVE"
        assert user.phone == "+2250700000099"
        assert user.full_name == "Moussa Traoré"

        stored_hash = pg_session.scalar(
            select(orm_models.User.password_hash).where(orm_models.User.id == user.id)
        )
        assert stored_hash is not None
        assert stored_hash != plain
        assert stored_hash == f"hash:{plain}"

    def test_full_registration_duplicate_phone_raises_409_equivalent(
        self, pg_session
    ) -> None:
        """Doublon de téléphone détecté par le pré-check applicatif (``PhoneAlreadyInUse``)."""
        from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository
        from coiflink_api.application.registration import RegisterCommand, RegisterUser
        from coiflink_api.domain.enums import Role
        from coiflink_api.domain.errors import PhoneAlreadyInUse

        from .conftest import FakeHasher

        usecase = RegisterUser(
            repository=SqlUserRepository(pg_session),
            hasher=FakeHasher(),
            role=Role.MANAGER,
        )
        cmd = RegisterCommand(
            full_name="Koné Mamadou",
            phone="0700000099",
            password="motdepasse-solide",
        )
        usecase.execute(cmd)
        with pytest.raises(PhoneAlreadyInUse):
            usecase.execute(cmd)
