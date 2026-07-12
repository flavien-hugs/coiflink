"""Tests d'intégration PostgreSQL pour l'inscription gérant (#9).

Nécessite un PostgreSQL avec le schéma appliqué (alembic upgrade head depuis
backend/ avec DATABASE_URL défini). Skippé proprement si DATABASE_URL absent.

Couvre le chemin réel qui va au-delà des fakes :
- Persistance effective : role=MANAGER, status=ACTIVE dans la base.
- phone normalisé E.164 stocké tel quel.
- password_hash ≠ mot de passe clair dans la table.
- Contrainte uq_users_phone au niveau base (doublon gérant→gérant).
- Doublon cross-rôle : téléphone CLIENT existant refusé pour un MANAGER.
- Traduction IntegrityError concurrente → PhoneAlreadyInUse (fallback race).

Prérequis d'exécution :
    cd backend
    DATABASE_URL=postgresql://user:pwd@localhost:5432/testdb alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@localhost:5432/testdb pytest \\
        tests/test_manager_registration_integration.py -v

Chaque test nettoie ses données (plage de numéros réservée : +225070999xxxx).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from coiflink_api.adapters.outbound.persistence.session import normalize_dsn
from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository
from coiflink_api.application.registration import RegisterCommand, RegisterUser
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import PhoneAlreadyInUse
from coiflink_api.domain.user import UserToCreate

from .conftest import FakeHasher

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="Postgres requis — définissez DATABASE_URL pour exécuter ces tests.",
)

# Plage de numéros réservée aux tests d'intégration (normalisés en E.164
# +225070999xxxx par le domaine). Le préfixe commun simplifie le nettoyage.
_PHONE_A_LOCAL = "0709990001"
_PHONE_B_LOCAL = "0709990002"
_PHONE_C_LOCAL = "0709990003"
_TEST_PHONE_E164_PREFIX = "+225070999"


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(normalize_dsn(_DATABASE_URL), pool_pre_ping=True, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def pg_session_factory(pg_engine):
    return sessionmaker(
        bind=pg_engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


@pytest.fixture(autouse=True)
def _wipe_test_phones(pg_engine):
    """Supprime les lignes de test avant et après chaque test."""

    def wipe() -> None:
        with pg_engine.connect() as conn:
            # salon_members → users (FK RESTRICT) : supprimer avant users.
            conn.execute(
                text(
                    "DELETE FROM salon_members WHERE user_id IN "
                    "(SELECT id FROM users WHERE phone LIKE :prefix)"
                ),
                {"prefix": f"{_TEST_PHONE_E164_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM users WHERE phone LIKE :prefix"),
                {"prefix": f"{_TEST_PHONE_E164_PREFIX}%"},
            )
            conn.commit()

    wipe()
    yield
    wipe()


def _new_session(factory) -> Session:
    return factory()


def _manager_usecase(session: Session) -> RegisterUser:
    return RegisterUser(
        repository=SqlUserRepository(session),
        hasher=FakeHasher(),
        role=Role.MANAGER.value,
    )


def _client_usecase(session: Session) -> RegisterUser:
    return RegisterUser(
        repository=SqlUserRepository(session),
        hasher=FakeHasher(),
        role=Role.CLIENT.value,
    )


class TestManagerPersistence:
    """La ligne users est effectivement insérée avec les bons attributs métier."""

    def test_manager_role_persisted(self, pg_session_factory) -> None:
        session = _new_session(pg_session_factory)
        try:
            user = _manager_usecase(session).execute(
                RegisterCommand(
                    full_name="Gérant Intégration",
                    phone=_PHONE_A_LOCAL,
                    password="motdepasse-solide",
                )
            )
            session.commit()
        finally:
            session.close()
        assert user.role == Role.MANAGER.value

    def test_manager_status_active_persisted(self, pg_session_factory) -> None:
        session = _new_session(pg_session_factory)
        try:
            user = _manager_usecase(session).execute(
                RegisterCommand(
                    full_name="Gérant Intégration",
                    phone=_PHONE_A_LOCAL,
                    password="motdepasse-solide",
                )
            )
            session.commit()
        finally:
            session.close()
        assert user.status == UserStatus.ACTIVE.value

    def test_manager_id_assigned(self, pg_session_factory) -> None:
        session = _new_session(pg_session_factory)
        try:
            user = _manager_usecase(session).execute(
                RegisterCommand(
                    full_name="Gérant Intégration",
                    phone=_PHONE_A_LOCAL,
                    password="motdepasse-solide",
                )
            )
            session.commit()
        finally:
            session.close()
        assert user.id is not None

    def test_manager_phone_normalized_e164(self, pg_session_factory) -> None:
        session = _new_session(pg_session_factory)
        try:
            user = _manager_usecase(session).execute(
                RegisterCommand(
                    full_name="Gérant Intégration",
                    phone=_PHONE_A_LOCAL,
                    password="motdepasse-solide",
                )
            )
            session.commit()
        finally:
            session.close()
        assert user.phone == "+2250709990001"

    def test_password_hash_not_plaintext_in_db(self, pg_session_factory, pg_engine) -> None:
        plain = "motdepasse-solide"
        session = _new_session(pg_session_factory)
        try:
            user = _manager_usecase(session).execute(
                RegisterCommand(
                    full_name="Gérant Intégration",
                    phone=_PHONE_A_LOCAL,
                    password=plain,
                )
            )
            session.commit()
        finally:
            session.close()
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT password_hash FROM users WHERE id = :id"),
                {"id": str(user.id)},
            ).fetchone()
        assert row is not None
        assert row[0] != plain

    def test_optional_email_stored_when_provided(self, pg_session_factory) -> None:
        session = _new_session(pg_session_factory)
        try:
            user = _manager_usecase(session).execute(
                RegisterCommand(
                    full_name="Gérant Avec Email",
                    phone=_PHONE_A_LOCAL,
                    password="motdepasse-solide",
                    email="gerant@salon.ci",
                )
            )
            session.commit()
        finally:
            session.close()
        assert user.email == "gerant@salon.ci"

    def test_email_none_when_not_provided(self, pg_session_factory) -> None:
        session = _new_session(pg_session_factory)
        try:
            user = _manager_usecase(session).execute(
                RegisterCommand(
                    full_name="Gérant Sans Email",
                    phone=_PHONE_A_LOCAL,
                    password="motdepasse-solide",
                )
            )
            session.commit()
        finally:
            session.close()
        assert user.email is None


class TestDuplicatePhoneConstraint:
    """La contrainte uq_users_phone est appliquée au niveau base de données."""

    def test_duplicate_manager_phone_raises_phone_already_in_use(
        self, pg_session_factory
    ) -> None:
        s1 = _new_session(pg_session_factory)
        try:
            _manager_usecase(s1).execute(
                RegisterCommand(
                    full_name="Gérant 1",
                    phone=_PHONE_A_LOCAL,
                    password="motdepasse-solide",
                )
            )
            s1.commit()
        finally:
            s1.close()

        s2 = _new_session(pg_session_factory)
        try:
            with pytest.raises(PhoneAlreadyInUse):
                _manager_usecase(s2).execute(
                    RegisterCommand(
                        full_name="Gérant 2",
                        phone=_PHONE_A_LOCAL,
                        password="motdepasse-solide",
                    )
                )
        finally:
            s2.close()

    def test_client_phone_rejected_for_manager_registration(
        self, pg_session_factory
    ) -> None:
        """Un téléphone inscrit en CLIENT est refusé pour un nouveau compte MANAGER."""
        s1 = _new_session(pg_session_factory)
        try:
            _client_usecase(s1).execute(
                RegisterCommand(
                    full_name="Client Existant",
                    phone=_PHONE_B_LOCAL,
                    password="motdepasse-solide",
                )
            )
            s1.commit()
        finally:
            s1.close()

        s2 = _new_session(pg_session_factory)
        try:
            with pytest.raises(PhoneAlreadyInUse):
                _manager_usecase(s2).execute(
                    RegisterCommand(
                        full_name="Gérant Tentative",
                        phone=_PHONE_B_LOCAL,
                        password="motdepasse-solide",
                    )
                )
        finally:
            s2.close()

    def test_integrity_error_fallback_on_concurrent_insert(
        self, pg_session_factory
    ) -> None:
        """Fallback IntegrityError → PhoneAlreadyInUse quand le pré-check est contourné.

        Simule la race condition où deux inscriptions concurrentes passent phone_exists
        avant que l'une d'elles ne committe. On appelle SqlUserRepository.create()
        directement, sans pré-check, pour reproduire ce scénario.
        """
        phone_e164 = "+2250709990003"

        s1 = _new_session(pg_session_factory)
        try:
            SqlUserRepository(s1).create(
                UserToCreate(
                    full_name="Premier Utilisateur",
                    phone=phone_e164,
                    password_hash="hash:motdepasse-solide",
                    email=None,
                    role=Role.MANAGER.value,
                    status=UserStatus.ACTIVE.value,
                )
            )
            s1.commit()
        finally:
            s1.close()

        s2 = _new_session(pg_session_factory)
        try:
            with pytest.raises(PhoneAlreadyInUse):
                SqlUserRepository(s2).create(
                    UserToCreate(
                        full_name="Concurrent",
                        phone=phone_e164,
                        password_hash="hash:motdepasse-concurrent",
                        email=None,
                        role=Role.CLIENT.value,
                        status=UserStatus.ACTIVE.value,
                    )
                )
        finally:
            s2.close()
