"""Tests de **concurrence** — anti double-réservation (US-3.7, #21).

Critère d'acceptation dur de l'issue #21 : *deux réservations concurrentes sur le
même créneau/coiffeur → une seule acceptée*. Ce fichier est le **seul** endroit où
cette garantie est réellement exercée : les tests unitaires simulent le conflit
(`FakeAppointmentRepository(raise_conflict=True)`), ici on provoque une **vraie**
violation de la contrainte d'exclusion PostgreSQL `ex_appointments_hairdresser_slot`.

Deux niveaux, tous deux à **parallélisme réel** (`ThreadPoolExecutor` +
`threading.Barrier` pour aligner les deux acteurs sur le même instant) :

1. `TestConcurrentBookingAtDatabaseLevel` — deux `Session` SQLAlchemy **distinctes**
   (donc deux connexions/transactions PostgreSQL) insèrent le même créneau pour le
   même coiffeur. Sous `READ COMMITTED`, la seconde attend le verrou de l'index GiST,
   puis échoue au commit du premier : exactement **1** succès et **1**
   `SlotAlreadyBooked`. On vérifie ensuite en base qu'**une seule** ligne subsiste
   (le perdant n'a rien persisté — ni RDV ni jonction `appointment_services`).

2. `TestConcurrentBookingOverHttp` — deux requêtes `POST /salons/{id}/appointments`
   simultanées, pile complète (JWT réel, sessions réelles). Exactement **un 201** et
   **un 409**. Le 409 peut venir soit de la course perdue en base (`SlotAlreadyBooked`),
   soit du garde applicatif `is_offered` si le premier RDV est déjà visible
   (`SlotUnavailable`) — les deux sont des refus corrects et indiscernables côté
   client ; l'invariant testé est « une seule réservation aboutit ».

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_appointment_concurrency.py -v

Sans `DATABASE_URL`, le fichier est **skippé proprement** (patron `test_service_e2e.py`) :
la garantie repose sur une contrainte d'exclusion GiST, elle n'est pas testable sur
un autre moteur.

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225074998xxxx).
"""

from __future__ import annotations

import datetime
import decimal
import os
import threading
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.outbound.persistence.appointment_repository import (
    SqlAppointmentRepository,
)
from coiflink_api.adapters.outbound.persistence.session import (
    get_engine,
    get_sessionmaker,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.domain.appointment import AppointmentToCreate, BookedService
from coiflink_api.domain.errors import SlotAlreadyBooked
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-concurrency-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests de concurrence (distincte des autres e2e :
# les tests peuvent tourner dans la même base sans se marcher dessus).
_E2E_PHONE_PREFIX = "+225074998"
_PHONE_MANAGER = "0749980001"
_PHONE_HAIRDRESSER = "0749980002"
_PHONE_CLIENT_A = "0749980003"
_PHONE_CLIENT_B = "0749980004"
_PASSWORD = "concurrency-e2e-strong-password-2024"

_SALON_NAME = "e2e-salon-concurrence"
_SERVICE_NAME = "Coupe concurrence"
_SERVICE_DURATION = 30

# Horaires du lundi : le créneau testé (09:00) tombe dedans et est aligné sur la
# grille par défaut (09:00 − 08:00 = 60 min).
_VALID_HOURS = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}
_START_TIME = datetime.time(9, 0)
_END_TIME = datetime.time(9, 30)

# Délai d'attente des tâches concurrentes : large, mais borné — un blocage sur le
# verrou de l'index GiST qui ne se résout pas doit faire échouer le test, pas le
# suspendre indéfiniment.
_TIMEOUT_SECONDS = 30


def _next_monday() -> datetime.date:
    """Un lundi **futur** (≥ 7 jours) : le créneau ne doit jamais être passé.

    Calculé dynamiquement plutôt qu'en dur : une date figée finirait par tomber
    dans le passé et ferait échouer `is_offered` pour une mauvaise raison.
    """

    base = datetime.date.today() + datetime.timedelta(days=7)
    return base + datetime.timedelta(days=(7 - base.weekday()) % 7)


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : appointment_services → appointments → audit_logs → services →
    salon_members → salons → users. Les rendez-vous précèdent les prestations et
    les salons (FK `RESTRICT` vers `services`/`salons`/`users`).
    """

    engine = get_engine()
    users_of_prefix = "SELECT id FROM users WHERE phone LIKE :prefix"
    with engine.connect() as conn:
        params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}
        # Jonctions RDV ↔ prestation (FK appointment_id → appointments).
        conn.execute(
            text(
                "DELETE FROM appointment_services WHERE appointment_id IN "
                f"(SELECT id FROM appointments WHERE client_id IN ({users_of_prefix}))"
            ),
            params,
        )
        # Rendez-vous (FK client_id/hairdresser_id → users, salon_id → salons).
        conn.execute(
            text(f"DELETE FROM appointments WHERE client_id IN ({users_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM appointments WHERE hairdresser_id IN ({users_of_prefix})"
            ),
            params,
        )
        # Journal d'audit (FK vers users et salons).
        conn.execute(
            text(
                "DELETE FROM audit_logs WHERE salon_id IN "
                f"(SELECT id FROM salons WHERE owner_id IN ({users_of_prefix}))"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM audit_logs WHERE actor_user_id IN ({users_of_prefix})"),
            params,
        )
        # Prestations (FK salon_id → salons RESTRICT).
        conn.execute(
            text(
                "DELETE FROM services WHERE salon_id IN "
                f"(SELECT id FROM salons WHERE owner_id IN ({users_of_prefix}))"
            ),
            params,
        )
        # Appartenances employé↔salon.
        conn.execute(
            text(f"DELETE FROM salon_members WHERE user_id IN ({users_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE salon_id IN "
                f"(SELECT id FROM salons WHERE owner_id IN ({users_of_prefix}))"
            ),
            params,
        )
        # Salons (FK owner_id → users RESTRICT).
        conn.execute(
            text(f"DELETE FROM salons WHERE owner_id IN ({users_of_prefix})"),
            params,
        )
        # Comptes utilisateurs.
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        conn.commit()


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT) ; skip sans `DATABASE_URL`."""

    if not _DATABASE_URL:
        pytest.skip(
            "DATABASE_URL requis : la garantie anti double-réservation repose sur une "
            "contrainte d'exclusion GiST PostgreSQL."
        )

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)

    main_app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    main_app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=10,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )

    _wipe_test_data()
    try:
        yield TestClient(main_app)
    finally:
        _wipe_test_data()
        main_app.state.token_service = orig_token_service
        main_app.state.login_rate_limiter = orig_rate_limiter


class _Fixture:
    """Identifiants du décor : salon réservable, coiffeur membre, prestation, clients."""

    def __init__(
        self,
        *,
        salon_id: uuid.UUID,
        hairdresser_id: uuid.UUID,
        service_id: uuid.UUID,
        client_a_id: uuid.UUID,
        client_b_id: uuid.UUID,
        token_a: str,
        token_b: str,
    ) -> None:
        self.salon_id = salon_id
        self.hairdresser_id = hairdresser_id
        self.service_id = service_id
        self.client_a_id = client_a_id
        self.client_b_id = client_b_id
        self.token_a = token_a
        self.token_b = token_b


def _register(client: TestClient, path: str, phone: str, name: str) -> uuid.UUID:
    resp = client.post(
        path, json={"full_name": name, "phone": phone, "password": _PASSWORD}
    )
    assert resp.status_code == 201, f"Inscription échouée ({phone}) : {resp.text}"
    return uuid.UUID(resp.json()["id"])


def _login(client: TestClient, phone: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée ({phone}) : {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture()
def _fixture(_e2e_client: TestClient) -> _Fixture:
    """Décor complet monté **via l'API** : salon réservable + coiffeur + prestation.

    Le coiffeur est créé par `POST /salons/{id}/employees`, ce qui l'inscrit dans
    `salon_members` — indispensable depuis le contrôle de rattachement §11.2 : un
    `hairdresser_id` hors salon serait refusé (404) avant même d'atteindre la base.
    """

    client = _e2e_client
    _register(client, "/auth/register/manager", _PHONE_MANAGER, "Gérant Concurrence")
    manager_token = _login(client, _PHONE_MANAGER)
    auth = {"Authorization": f"Bearer {manager_token}"}

    resp = client.post("/salons", json={"name": _SALON_NAME}, headers=auth)
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    salon_id = uuid.UUID(resp.json()["id"])

    resp = client.put(
        f"/salons/{salon_id}/opening-hours", json=_VALID_HOURS, headers=auth
    )
    assert resp.status_code == 200, f"Horaires refusés : {resp.text}"

    resp = client.post(
        f"/salons/{salon_id}/employees",
        json={
            "full_name": "Coiffeur Concurrence",
            "phone": _PHONE_HAIRDRESSER,
            "password": _PASSWORD,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Création coiffeur échouée : {resp.text}"
    hairdresser_id = uuid.UUID(resp.json()["id"])

    resp = client.post(
        f"/salons/{salon_id}/services",
        json={
            "name": _SERVICE_NAME,
            "price": "5000.00",
            "duration_minutes": _SERVICE_DURATION,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    service_id = uuid.UUID(resp.json()["id"])

    client_a_id = _register(client, "/auth/register", _PHONE_CLIENT_A, "Client A")
    client_b_id = _register(client, "/auth/register", _PHONE_CLIENT_B, "Client B")

    return _Fixture(
        salon_id=salon_id,
        hairdresser_id=hairdresser_id,
        service_id=service_id,
        client_a_id=client_a_id,
        client_b_id=client_b_id,
        token_a=_login(client, _PHONE_CLIENT_A),
        token_b=_login(client, _PHONE_CLIENT_B),
    )


# ─── Helpers de lecture base ──────────────────────────────────────────────────


def _count_appointments(salon_id: uuid.UUID, date: datetime.date) -> int:
    """Nombre de RDV actifs persistés pour ce salon/jour (source de vérité : la base)."""

    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT COUNT(*) FROM appointments WHERE salon_id = :sid "
                "AND appointment_date = :d AND status IN ('PENDING', 'CONFIRMED')"
            ),
            {"sid": str(salon_id), "d": date},
        ).scalar_one()


def _count_appointment_services(salon_id: uuid.UUID) -> int:
    """Nombre de lignes de jonction — vérifie que le perdant n'a rien laissé derrière."""

    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM appointment_services WHERE salon_id = :sid"),
            {"sid": str(salon_id)},
        ).scalar_one()


# ─── 1. Concurrence au niveau base (deux transactions réelles) ────────────────


class TestConcurrentBookingAtDatabaseLevel:
    """Deux transactions PostgreSQL simultanées sur le même créneau/coiffeur."""

    def test_two_concurrent_transactions_only_one_succeeds(
        self, _fixture: _Fixture
    ) -> None:
        date = _next_monday()
        to_create = AppointmentToCreate(
            salon_id=_fixture.salon_id,
            client_id=_fixture.client_a_id,
            hairdresser_id=_fixture.hairdresser_id,
            date=date,
            start_time=_START_TIME,
            end_time=_END_TIME,
            services=(
                BookedService(
                    service_id=_fixture.service_id,
                    price_at_booking=decimal.Decimal("5000.00"),
                ),
            ),
            client_note=None,
        )

        sessionmaker_ = get_sessionmaker()
        # Les deux tâches se rejoignent sur la barrière **avant** l'INSERT : elles
        # frappent la contrainte d'exclusion au même instant, sur deux connexions.
        barrier = threading.Barrier(2)

        def book(client_id: uuid.UUID) -> str:
            session = sessionmaker_()
            try:
                repository = SqlAppointmentRepository(session)
                command = AppointmentToCreate(
                    salon_id=to_create.salon_id,
                    client_id=client_id,
                    hairdresser_id=to_create.hairdresser_id,
                    date=to_create.date,
                    start_time=to_create.start_time,
                    end_time=to_create.end_time,
                    services=to_create.services,
                    client_note=to_create.client_note,
                )
                barrier.wait(timeout=_TIMEOUT_SECONDS)
                try:
                    repository.create(command)
                except SlotAlreadyBooked:
                    return "conflict"
                # Le commit libère le verrou de l'index GiST : le perdant, jusque-là
                # bloqué dans son INSERT, reçoit alors sa violation d'exclusion.
                session.commit()
                return "created"
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(book, _fixture.client_a_id),
                pool.submit(book, _fixture.client_b_id),
            ]
            outcomes = sorted(f.result(timeout=_TIMEOUT_SECONDS) for f in futures)

        # Exactement une réservation acceptée, une refusée pour cause de course perdue.
        assert outcomes == ["conflict", "created"], (
            f"Attendu 1 succès + 1 conflit, obtenu : {outcomes}"
        )
        # La base est la source de vérité : une seule ligne, et aucune jonction
        # orpheline laissée par le perdant (rollback complet de son unité de travail).
        assert _count_appointments(_fixture.salon_id, date) == 1
        assert _count_appointment_services(_fixture.salon_id) == 1

    def test_non_overlapping_slots_both_succeed(self, _fixture: _Fixture) -> None:
        """Contrôle négatif : la contrainte ne refuse **que** les créneaux qui se chevauchent.

        Sans ce test, une implémentation qui rejetterait tout second INSERT (bug de
        verrouillage trop large) passerait le test précédent.
        """

        date = _next_monday()
        sessionmaker_ = get_sessionmaker()
        barrier = threading.Barrier(2)

        def book(client_id: uuid.UUID, start: datetime.time, end: datetime.time) -> str:
            session = sessionmaker_()
            try:
                repository = SqlAppointmentRepository(session)
                barrier.wait(timeout=_TIMEOUT_SECONDS)
                try:
                    repository.create(
                        AppointmentToCreate(
                            salon_id=_fixture.salon_id,
                            client_id=client_id,
                            hairdresser_id=_fixture.hairdresser_id,
                            date=date,
                            start_time=start,
                            end_time=end,
                            services=(
                                BookedService(
                                    service_id=_fixture.service_id,
                                    price_at_booking=decimal.Decimal("5000.00"),
                                ),
                            ),
                            client_note=None,
                        )
                    )
                except SlotAlreadyBooked:
                    return "conflict"
                session.commit()
                return "created"
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                # Dos à dos (fermé-ouvert) : 09:00–09:30 et 09:30–10:00 ne se
                # chevauchent pas — les deux doivent aboutir.
                pool.submit(
                    book, _fixture.client_a_id, datetime.time(9, 0), datetime.time(9, 30)
                ),
                pool.submit(
                    book, _fixture.client_b_id, datetime.time(9, 30), datetime.time(10, 0)
                ),
            ]
            outcomes = sorted(f.result(timeout=_TIMEOUT_SECONDS) for f in futures)

        assert outcomes == ["created", "created"], (
            f"Créneaux adjacents refusés à tort : {outcomes}"
        )
        assert _count_appointments(_fixture.salon_id, date) == 2


# ─── 2. Concurrence au niveau HTTP (deux requêtes simultanées) ────────────────


class TestConcurrentBookingOverHttp:
    """Deux `POST /salons/{id}/appointments` simultanés — pile complète."""

    def test_two_concurrent_requests_yield_one_201_and_one_409(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        date = _next_monday()
        body = {
            "date": date.isoformat(),
            "start_time": "09:00",
            "service_ids": [str(_fixture.service_id)],
            "hairdresser_id": str(_fixture.hairdresser_id),
        }
        barrier = threading.Barrier(2)

        def post(token: str) -> int:
            # Barrière juste avant l'envoi : les deux requêtes partent ensemble et
            # se disputent le créneau dans deux sessions HTTP/DB distinctes.
            barrier.wait(timeout=_TIMEOUT_SECONDS)
            resp = _e2e_client.post(
                f"/salons/{_fixture.salon_id}/appointments",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            return resp.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(post, _fixture.token_a),
                pool.submit(post, _fixture.token_b),
            ]
            statuses = sorted(f.result(timeout=_TIMEOUT_SECONDS) for f in futures)

        # Une seule réservation acceptée ; l'autre est refusée en conflit — que le
        # refus vienne de la base (course perdue) ou du garde applicatif.
        assert statuses == [201, 409], (
            f"Attendu exactement un 201 et un 409, obtenu : {statuses}"
        )
        assert _count_appointments(_fixture.salon_id, date) == 1
