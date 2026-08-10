"""Tests d'intégration PostgreSQL pour le catalogue public de salons (#18).

Nécessite un PostgreSQL avec le schéma appliqué (alembic upgrade head depuis
backend/ avec DATABASE_URL défini). Skippé proprement si DATABASE_URL absent.

`FakeSalonCatalogRepository` (tests unitaires/API) filtre en mémoire avec une
sémantique proche mais distincte du SQL réel : ces tests couvrent le chemin de
production `SqlSalonCatalogRepository` que le fake ne peut pas exercer :

- filtre `status = ACTIVE` appliqué **en base** (`search_active`, `get_active`) ;
- `ILIKE` réel sur le nom, métacaractères `%`/`_` échappés (littéraux, pas des
  jokers) ;
- filtre de zone (`city`/`commune`) en `ILIKE` échappé, même garantie ;
- pagination (`limit`/`offset`) sur une vraie requête paginée/triée.

Prérequis d'exécution :
    cd backend
    DATABASE_URL=postgresql://user:pwd@localhost:5432/testdb alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@localhost:5432/testdb pytest \\
        tests/test_salon_catalog_repository_integration.py -v

Chaque test nettoie ses données (owner réservé +2250709998xxx, salons préfixés
« Salon Intégration Catalogue »).
"""

from __future__ import annotations

import decimal
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import (
    SqlSalonCatalogRepository,
)
from coiflink_api.adapters.outbound.persistence.salon_member_repository import (
    SqlSalonMemberRepository,
)
from coiflink_api.adapters.outbound.persistence.salon_repository import SqlSalonRepository
from coiflink_api.adapters.outbound.persistence.service_repository import SqlServiceRepository
from coiflink_api.adapters.outbound.persistence.session import normalize_dsn
from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository
from coiflink_api.application.ports.salon_catalog_repository import SalonSearchQuery
from coiflink_api.application.registration import RegisterCommand, RegisterUser
from coiflink_api.domain.enums import Role, SalonStatus, UserStatus
from coiflink_api.domain.membership import SalonMembershipToCreate
from coiflink_api.domain.salon import SalonToCreate
from coiflink_api.domain.service import ServiceToCreate
from coiflink_api.domain.user import UserToCreate

from .conftest import FakeHasher

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="Postgres requis — définissez DATABASE_URL pour exécuter ces tests.",
)

# Owner réservé aux tests d'intégration catalogue (plage distincte de
# test_manager_registration_integration.py) et préfixe des noms de salons créés.
_OWNER_PHONE_LOCAL = "0709998001"
_OWNER_PHONE_E164_PREFIX = "+2250709998"
_SALON_NAME_PREFIX = "Salon Intégration Catalogue "

# Plage réservée aux coiffeuses de test (#150) — distincte de l'owner ci-dessus.
_HAIRDRESSER_PHONE_E164_PREFIX = "+2250709997"


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
def _wipe_test_data(pg_engine):
    """Supprime salons et owner de test avant et après chaque test (ordre FK)."""

    def wipe() -> None:
        with pg_engine.connect() as conn:
            # salon_members (FK RESTRICT) → salons **et** → users : à supprimer
            # avant l'un ou l'autre.
            conn.execute(
                text(
                    "DELETE FROM salon_members WHERE salon_id IN "
                    "(SELECT id FROM salons WHERE name LIKE :prefix)"
                ),
                {"prefix": f"{_SALON_NAME_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM salon_members WHERE user_id IN "
                     "(SELECT id FROM users WHERE phone LIKE :prefix)"),
                {"prefix": f"{_HAIRDRESSER_PHONE_E164_PREFIX}%"},
            )
            # services (FK RESTRICT) → salons ; salon_photos est en CASCADE.
            conn.execute(
                text(
                    "DELETE FROM services WHERE salon_id IN "
                    "(SELECT id FROM salons WHERE name LIKE :prefix)"
                ),
                {"prefix": f"{_SALON_NAME_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM salons WHERE name LIKE :prefix"),
                {"prefix": f"{_SALON_NAME_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM users WHERE phone LIKE :prefix"),
                {"prefix": f"{_OWNER_PHONE_E164_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM users WHERE phone LIKE :prefix"),
                {"prefix": f"{_HAIRDRESSER_PHONE_E164_PREFIX}%"},
            )
            conn.commit()

    wipe()
    yield
    wipe()


def _new_session(factory) -> Session:
    return factory()


@pytest.fixture
def owner_id(pg_session_factory) -> uuid.UUID:
    session = _new_session(pg_session_factory)
    try:
        user = RegisterUser(
            repository=SqlUserRepository(session),
            hasher=FakeHasher(),
            role=Role.MANAGER.value,
        ).execute(
            RegisterCommand(
                full_name="Gérant Intégration Catalogue",
                phone=_OWNER_PHONE_LOCAL,
                password="motdepasse-solide",
            )
        )
        session.commit()
    finally:
        session.close()
    return user.id


def _create_salon(
    pg_session_factory,
    owner_id: uuid.UUID,
    *,
    name: str,
    city: str | None = None,
    commune: str | None = None,
) -> uuid.UUID:
    session = _new_session(pg_session_factory)
    try:
        salon = SqlSalonRepository(session).create(
            SalonToCreate(
                owner_id=owner_id,
                name=f"{_SALON_NAME_PREFIX}{name}",
                city=city,
                commune=commune,
            )
        )
        session.commit()
    finally:
        session.close()
    return salon.id


def _set_status(pg_engine, salon_id: uuid.UUID, status: str) -> None:
    with pg_engine.connect() as conn:
        conn.execute(
            text("UPDATE salons SET status = :status WHERE id = :id"),
            {"status": status, "id": str(salon_id)},
        )
        conn.commit()


def _search(pg_session_factory, **kwargs) -> tuple:
    session = _new_session(pg_session_factory)
    try:
        return SqlSalonCatalogRepository(session).search_active(SalonSearchQuery(**kwargs))
    finally:
        session.close()


def _create_service(
    pg_session_factory,
    salon_id: uuid.UUID,
    *,
    name: str,
    active: bool = True,
) -> uuid.UUID:
    session = _new_session(pg_session_factory)
    try:
        service = SqlServiceRepository(session).create(
            ServiceToCreate(
                salon_id=salon_id,
                name=name,
                price=decimal.Decimal("5000.00"),
                duration_minutes=30,
            )
        )
        if not active:
            SqlServiceRepository(session).set_active(salon_id, service.id, False)
        session.commit()
    finally:
        session.close()
    return service.id


_hairdresser_phone_counter = 0


def _create_hairdresser(
    pg_session_factory,
    salon_id: uuid.UUID,
    *,
    full_name: str,
    specialties: str | None = None,
    status: str = UserStatus.ACTIVE.value,
) -> uuid.UUID:
    global _hairdresser_phone_counter
    _hairdresser_phone_counter += 1
    phone = f"{_HAIRDRESSER_PHONE_E164_PREFIX}{_hairdresser_phone_counter:03d}"

    session = _new_session(pg_session_factory)
    try:
        user = SqlUserRepository(session).create(
            UserToCreate(
                full_name=full_name,
                phone=phone,
                password_hash="x",
                role=Role.HAIRDRESSER.value,
                status=UserStatus.ACTIVE.value,
            )
        )
        members = SqlSalonMemberRepository(session)
        members.add_member(
            SalonMembershipToCreate(
                salon_id=salon_id,
                user_id=user.id,
                role=Role.HAIRDRESSER.value,
                status=UserStatus.ACTIVE.value,
            )
        )
        if specialties is not None:
            members.update_professional_fields(
                salon_id, user.id, specialties=specialties, hired_at=None
            )
        if status != UserStatus.ACTIVE.value:
            members.set_status(salon_id, user.id, status)
        session.commit()
    finally:
        session.close()
    return user.id


def _add_photo(pg_session_factory, salon_id: uuid.UUID, *, object_key: str) -> uuid.UUID:
    session = _new_session(pg_session_factory)
    try:
        photo = SqlSalonRepository(session).add_photo(salon_id, object_key)
        session.commit()
    finally:
        session.close()
    return photo.id


class TestActiveOnlyFilter:
    """§8.3 : le filtre `status = ACTIVE` est appliqué en SQL, jamais contournable."""

    def test_search_active_excludes_inactive_and_suspended(
        self, pg_engine, pg_session_factory, owner_id
    ) -> None:
        active_id = _create_salon(pg_session_factory, owner_id, name="Actif")
        inactive_id = _create_salon(pg_session_factory, owner_id, name="Inactif")
        suspended_id = _create_salon(pg_session_factory, owner_id, name="Suspendu")
        _set_status(pg_engine, inactive_id, SalonStatus.INACTIVE.value)
        _set_status(pg_engine, suspended_id, SalonStatus.SUSPENDED.value)

        results = _search(pg_session_factory, text=_SALON_NAME_PREFIX)

        ids = {row.id for row in results}
        assert active_id in ids
        assert inactive_id not in ids
        assert suspended_id not in ids

    def test_get_active_returns_none_for_inactive_salon(
        self, pg_engine, pg_session_factory, owner_id
    ) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Fermé")
        _set_status(pg_engine, salon_id, SalonStatus.INACTIVE.value)

        session = _new_session(pg_session_factory)
        try:
            result = SqlSalonCatalogRepository(session).get_active(salon_id)
        finally:
            session.close()

        assert result is None

    def test_get_active_returns_salon_when_active(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Ouvert")

        session = _new_session(pg_session_factory)
        try:
            result = SqlSalonCatalogRepository(session).get_active(salon_id)
        finally:
            session.close()

        assert result is not None
        assert result.id == salon_id


class TestNameSearchIlike:
    """Recherche par nom : `ILIKE` réel, métacaractères `%`/`_` échappés (littéraux)."""

    def test_search_is_case_insensitive_substring(self, pg_session_factory, owner_id) -> None:
        _create_salon(pg_session_factory, owner_id, name="Le Salon Doré")

        results = _search(pg_session_factory, text="salon doré".upper())

        assert any(row.name.endswith("Le Salon Doré") for row in results)

    def test_percent_in_query_is_treated_as_literal(self, pg_session_factory, owner_id) -> None:
        literal_id = _create_salon(pg_session_factory, owner_id, name="50% Chic")
        decoy_id = _create_salon(pg_session_factory, owner_id, name="50X Chic")

        results = _search(pg_session_factory, text="50%")

        ids = {row.id for row in results}
        assert literal_id in ids
        assert decoy_id not in ids


class TestZoneFilter:
    """`city`/`commune` : égalité insensible à la casse, métacaractères échappés."""

    def test_city_filter_is_case_insensitive(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Ville", city="Abidjan")

        results = _search(pg_session_factory, text=_SALON_NAME_PREFIX, city="ABIDJAN")

        assert salon_id in {row.id for row in results}

    def test_city_with_percent_is_treated_as_literal(self, pg_session_factory, owner_id) -> None:
        literal_id = _create_salon(
            pg_session_factory, owner_id, name="Zone Littérale", city="Abi%an"
        )
        decoy_id = _create_salon(
            pg_session_factory, owner_id, name="Zone Décalque", city="Abidjan"
        )

        results = _search(pg_session_factory, text=_SALON_NAME_PREFIX, city="Abi%an")

        ids = {row.id for row in results}
        assert literal_id in ids
        assert decoy_id not in ids


class TestPagination:
    """`limit`/`offset` bornés, appliqués à une requête triée par nom réelle."""

    def test_limit_and_offset_slice_the_sorted_results(
        self, pg_session_factory, owner_id
    ) -> None:
        _create_salon(pg_session_factory, owner_id, name="A Premier")
        _create_salon(pg_session_factory, owner_id, name="B Second")
        _create_salon(pg_session_factory, owner_id, name="C Troisième")

        page = _search(pg_session_factory, text=_SALON_NAME_PREFIX, limit=1, offset=1)

        assert len(page) == 1
        assert page[0].name == f"{_SALON_NAME_PREFIX}B Second"

    def test_count_active_ignores_pagination(self, pg_session_factory, owner_id) -> None:
        _create_salon(pg_session_factory, owner_id, name="A Premier")
        _create_salon(pg_session_factory, owner_id, name="B Second")

        session = _new_session(pg_session_factory)
        try:
            total = SqlSalonCatalogRepository(session).count_active(
                SalonSearchQuery(text=_SALON_NAME_PREFIX, limit=1, offset=0)
            )
        finally:
            session.close()

        assert total == 2


class TestListActiveServices:
    """`list_active_services` : filtre `is_active = true` appliqué en SQL (#19)."""

    def test_excludes_inactive_service(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Avec Prestations")
        active_id = _create_service(pg_session_factory, salon_id, name="Coupe", active=True)
        inactive_id = _create_service(
            pg_session_factory, salon_id, name="Ancienne Prestation", active=False
        )

        session = _new_session(pg_session_factory)
        try:
            services = SqlSalonCatalogRepository(session).list_active_services(salon_id)
        finally:
            session.close()

        ids = {s.id for s in services}
        assert active_id in ids
        assert inactive_id not in ids

    def test_returns_empty_tuple_when_no_active_service(
        self, pg_session_factory, owner_id
    ) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Sans Prestations")

        session = _new_session(pg_session_factory)
        try:
            services = SqlSalonCatalogRepository(session).list_active_services(salon_id)
        finally:
            session.close()

        assert services == ()

    def test_ordered_by_name(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Tri Prestations")
        _create_service(pg_session_factory, salon_id, name="Z Dernière")
        _create_service(pg_session_factory, salon_id, name="A Première")

        session = _new_session(pg_session_factory)
        try:
            services = SqlSalonCatalogRepository(session).list_active_services(salon_id)
        finally:
            session.close()

        assert [s.name for s in services] == ["A Première", "Z Dernière"]


class TestListActiveHairdressers:
    """`list_active_hairdressers` : filtre `status = ACTIVE` appliqué en SQL (#150)."""

    def test_excludes_inactive_hairdresser(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Avec Coiffeuses")
        active_id = _create_hairdresser(
            pg_session_factory, salon_id, full_name="Awa Koné"
        )
        inactive_id = _create_hairdresser(
            pg_session_factory,
            salon_id,
            full_name="Fatou Diarra",
            status=UserStatus.INACTIVE.value,
        )

        session = _new_session(pg_session_factory)
        try:
            hairdressers = SqlSalonCatalogRepository(session).list_active_hairdressers(
                salon_id
            )
        finally:
            session.close()

        ids = {h.id for h in hairdressers}
        assert active_id in ids
        assert inactive_id not in ids

    def test_returns_empty_tuple_when_no_active_hairdresser(
        self, pg_session_factory, owner_id
    ) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Sans Coiffeuses")

        session = _new_session(pg_session_factory)
        try:
            hairdressers = SqlSalonCatalogRepository(session).list_active_hairdressers(
                salon_id
            )
        finally:
            session.close()

        assert hairdressers == ()

    def test_ordered_by_name(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Tri Coiffeuses")
        _create_hairdresser(pg_session_factory, salon_id, full_name="Z Dernière")
        _create_hairdresser(pg_session_factory, salon_id, full_name="A Première")

        session = _new_session(pg_session_factory)
        try:
            hairdressers = SqlSalonCatalogRepository(session).list_active_hairdressers(
                salon_id
            )
        finally:
            session.close()

        assert [h.full_name for h in hairdressers] == ["A Première", "Z Dernière"]

    def test_carries_specialties_no_phone_or_email(
        self, pg_session_factory, owner_id
    ) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Coiffeuse Détail")
        _create_hairdresser(
            pg_session_factory,
            salon_id,
            full_name="Awa Koné",
            specialties="Tresses, colorations",
        )

        session = _new_session(pg_session_factory)
        try:
            hairdressers = SqlSalonCatalogRepository(session).list_active_hairdressers(
                salon_id
            )
        finally:
            session.close()

        assert len(hairdressers) == 1
        hairdresser = hairdressers[0]
        assert hairdresser.specialties == "Tresses, colorations"
        # `Employee` porte phone/email/status/hired_at (usage gestion) : c'est le
        # cas d'usage catalogue (`GetPublicSalon`) qui les retire côté public
        # (§A.4) — vérifié séparément par `test_catalog_detail_api.py`. Ici, on
        # vérifie seulement que le dépôt renvoie l'entité complète et cohérente.
        assert hairdresser.role == Role.HAIRDRESSER.value
        assert hairdresser.status == UserStatus.ACTIVE.value

    def test_isolation_between_salons(self, pg_session_factory, owner_id) -> None:
        salon_a = _create_salon(pg_session_factory, owner_id, name="Salon A Coiffeuses")
        salon_b = _create_salon(pg_session_factory, owner_id, name="Salon B Coiffeuses")
        _create_hairdresser(pg_session_factory, salon_a, full_name="Coiffeuse A")

        session = _new_session(pg_session_factory)
        try:
            hairdressers_b = SqlSalonCatalogRepository(session).list_active_hairdressers(
                salon_b
            )
        finally:
            session.close()

        assert hairdressers_b == ()


class TestListPhotos:
    """`list_photos` : toutes les photos du salon, ordonnées par position (#19)."""

    def test_returns_photos_ordered_by_position(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Avec Photos")
        second_id = _add_photo(pg_session_factory, salon_id, object_key="salons/x/photo-2.jpg")
        first_id = _add_photo(pg_session_factory, salon_id, object_key="salons/x/photo-1.jpg")

        session = _new_session(pg_session_factory)
        try:
            photos = SqlSalonCatalogRepository(session).list_photos(salon_id)
        finally:
            session.close()

        # `add_photo` assigne `position` par ordre d'insertion (0, 1, ...).
        assert [p.id for p in photos] == [second_id, first_id]

    def test_returns_empty_tuple_when_no_photo(self, pg_session_factory, owner_id) -> None:
        salon_id = _create_salon(pg_session_factory, owner_id, name="Sans Photos")

        session = _new_session(pg_session_factory)
        try:
            photos = SqlSalonCatalogRepository(session).list_photos(salon_id)
        finally:
            session.close()

        assert photos == ()
