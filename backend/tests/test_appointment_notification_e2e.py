"""Tests e2e pour US-7.1 — confirmation de RDV (#45) et US-7.2 — rappels (#46).

Groupe `TestAppointmentNotificationE2E` (PostgreSQL requis) :
    exerce le **chemin d'écriture réel** de `SqlNotificationRepository` —
    insertion et annulation de lignes `notifications` dans la **même
    transaction** que l'écriture du RDV (`BookAppointment`/`CancelAppointment`/
    `SetAppointmentStatus`/`ModifyAppointment`, patron `AuditLog` #20), vérifiée
    contre les contraintes réelles du schéma (FK `RESTRICT`, `CHECK`
    d'énumération, migration `0006`). Les suites unitaires/API (adossées à un
    `FakeNotificationRepository` en mémoire) couvrent la règle métier, mais
    aucune ne vérifie le contenu **réellement persisté** — c'est le seul code
    qui satisfait les critères d'acceptation #45/#46 (cf. finding de revue
    automatisée sur la PR #132).

Scénarios (spec `specs/notification-confirmation-rdv.md` et
`specs/rappel-automatique-avant-rdv.md`, miroir `test_service_demand_e2e.py`
#41) :
    - une réservation réussie (`POST /salons/{id}/appointments`) insère
      **exactement une** ligne `type=CONFIRMATION`, `status=PENDING`,
      `sent_at IS NULL`, `channel=SMS`, **et** (US-7.2, #46) une ligne
      `type=REMINDER` `status=PENDING` par échéance encore future
      (`scheduled_for = début − 24h/2h/30min`) ;
    - les lignes sont **rattachées** au bon `user_id` (client), `salon_id` et
      `appointment_id` (mêmes valeurs que le RDV créé) ;
    - `title`/`message` sont les libellés templatés, **sans PII** (aucun
      téléphone, aucun nom) ;
    - les lignes persistées respectent les contraintes réelles du schéma (FK
      vers `users`/`salons`/`appointments`, `CHECK` d'énumération
      `type`/`channel`/`status`, y compris `CANCELLED`) — l'`INSERT`
      échouerait avec des valeurs hors domaine ;
    - une réservation **refusée** (créneau déjà pris, course perdue → `409`)
      ne laisse **aucune** notification (rollback complet, RDV + confirmation
      + rappels ensemble) ;
    - l'**annulation client** (`POST .../cancellation`) et le **refus gérant**
      (`POST .../status` `CANCELLED`) **annulent** (`CANCELLED`) les rappels
      `PENDING` du RDV, dans la même transaction que le changement de statut
      (AC #46) ;
    - la **modification** (`PATCH /appointments/{id}`) **re-planifie** les
      rappels sur le nouveau créneau (annule les anciens, en recrée de
      nouveaux datés) ;
    - `401` sans jeton (deny-by-default, hors périmètre de la notification
      elle-même, testé ailleurs — non répété ici) ;
    - la réponse HTTP de réservation ne révèle **jamais** l'existence ni le
      contenu de la notification (canal, titre, message absents du corps).

Le décor (salon réservable, horaires, coiffeur, prestation, client) est monté
**via l'API réelle** (miroir `test_appointment_concurrency.py`, #21) — la
réservation elle-même passe par `POST /salons/{id}/appointments`, jamais un
bypass SQL : c'est précisément le chemin `BookAppointment` qui émet la
confirmation et planifie les rappels.

**Note d'ordre de nettoyage** (mémoire projet) : depuis #45, une réservation
réussie insère des lignes `notifications` dont les FK sont `ON DELETE
RESTRICT` — `_wipe_test_data` supprime `notifications` **avant**
`appointment_services`/`appointments`/`salon_members`/`salons`/`users`.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_appointment_notification_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225069998xxxx).
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.outbound.persistence.session import get_engine
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.domain.notification import REMINDER_OFFSETS
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-appointment-notification-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e de la notification de confirmation.
_E2E_PHONE_PREFIX = "+225069998"
_PHONE_MANAGER_LOCAL = "0699980001"
_PHONE_HAIRDRESSER_LOCAL = "0699980002"
_PHONE_CLIENT_A_LOCAL = "0699980003"
_PHONE_CLIENT_B_LOCAL = "0699980004"
_PASSWORD = "appointment-notification-e2e-strong-password-2024"

_SALON_NAME = "e2e-salon-appointment-notification"
_SERVICE_NAME = "Coupe E2E Notification"
_SERVICE_DURATION = 30
_VALID_HOURS = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → notifications → appointment_services → appointments →
    services → salon_members → salons → users. `notifications` **avant**
    `appointments`/`users`/`salons` : depuis #45, une réservation réussie émet
    une ligne `notifications` dont les FK référencent ces trois tables (mémoire
    projet `notifications-fk-restrict-cleanup`).
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "DELETE FROM audit_logs WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM notifications WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)) "
                "OR user_id IN (SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM appointment_services WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM appointments WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM services WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE user_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text("DELETE FROM users WHERE phone LIKE :prefix"),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT).

    - Injecte un JwtTokenService de test (secret local, jamais en production) sur app.state.
    - Supprime les données de test (plage +225069998) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip(
            "DATABASE_URL requis pour les tests e2e de la notification de confirmation."
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


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _register(client: TestClient, path: str, *, phone: str, full_name: str) -> str:
    """Inscrit un compte via l'API et retourne son UUID."""
    resp = client.post(
        path, json={"full_name": full_name, "phone": phone, "password": _PASSWORD}
    )
    assert resp.status_code == 201, f"Inscription échouée ({phone}) : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée ({phone}) : {resp.text}"
    return resp.json()["access_token"]


def _next_monday() -> datetime.date:
    """Prochain lundi (jour couvert par `_VALID_HOURS`), toujours dans le futur."""
    today = datetime.date.today()
    days_ahead = (7 - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=days_ahead)


class _Fixture:
    def __init__(
        self,
        *,
        salon_id: str,
        hairdresser_id: str,
        service_id: str,
        client_a_id: str,
        client_b_id: str,
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


@pytest.fixture()
def _fixture(_e2e_client: TestClient) -> _Fixture:
    """Décor complet monté **via l'API** : salon réservable + coiffeur + prestation.

    Miroir `test_appointment_concurrency.py::_fixture` (#21) : le coiffeur est créé
    par `POST /salons/{id}/employees` (inscrit dans `salon_members`, requis par le
    contrôle de rattachement §11.2).
    """
    client = _e2e_client
    _register(
        client, "/auth/register/manager", phone=_PHONE_MANAGER_LOCAL, full_name="Gérant E2E Notif"
    )
    manager_token = _login(client, phone=_PHONE_MANAGER_LOCAL)
    auth = {"Authorization": f"Bearer {manager_token}"}

    resp = client.post("/salons", json={"name": _SALON_NAME}, headers=auth)
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    salon_id = resp.json()["id"]

    resp = client.put(
        f"/salons/{salon_id}/opening-hours", json=_VALID_HOURS, headers=auth
    )
    assert resp.status_code == 200, f"Horaires refusés : {resp.text}"

    resp = client.post(
        f"/salons/{salon_id}/employees",
        json={
            "full_name": "Coiffeur E2E Notif",
            "phone": _PHONE_HAIRDRESSER_LOCAL,
            "password": _PASSWORD,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Création coiffeur échouée : {resp.text}"
    hairdresser_id = resp.json()["id"]

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
    service_id = resp.json()["id"]

    client_a_id = _register(
        client, "/auth/register", phone=_PHONE_CLIENT_A_LOCAL, full_name="Client E2E Notif A"
    )
    client_b_id = _register(
        client, "/auth/register", phone=_PHONE_CLIENT_B_LOCAL, full_name="Client E2E Notif B"
    )

    return _Fixture(
        salon_id=salon_id,
        hairdresser_id=hairdresser_id,
        service_id=service_id,
        client_a_id=client_a_id,
        client_b_id=client_b_id,
        token_a=_login(client, phone=_PHONE_CLIENT_A_LOCAL),
        token_b=_login(client, phone=_PHONE_CLIENT_B_LOCAL),
    )


def _book(
    client: TestClient, token: str, salon_id: str, *, date: datetime.date,
    start_time: str, service_id: str, hairdresser_id: str,
) -> dict:
    """`POST /salons/{id}/appointments` — retourne la réponse JSON complète."""
    resp = client.post(
        f"/salons/{salon_id}/appointments",
        json={
            "date": date.isoformat(),
            "start_time": start_time,
            "service_ids": [service_id],
            "hairdresser_id": hairdresser_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp


def _notifications_for_appointment(appointment_id: str) -> list[dict]:
    """Lit directement en base les notifications rattachées à un RDV (assertion, pas l'app)."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, user_id, salon_id, appointment_id, type, channel, "
                "title, message, status, sent_at, scheduled_for "
                "FROM notifications WHERE appointment_id = :aid"
            ),
            {"aid": appointment_id},
        ).mappings().all()
        return [dict(row) for row in rows]


def _confirmation_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["type"] == "CONFIRMATION"]


def _reminder_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["type"] == "REMINDER"]


def _as_naive_utc(value: datetime.datetime) -> datetime.datetime:
    """Normalise un `scheduled_for` lu en base (tz-aware) pour comparaison naïve."""
    return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _notification_count_for_salon(salon_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM notifications WHERE salon_id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


def _cancel(client: TestClient, token: str, appointment_id: str) -> dict:
    """`POST /appointments/{id}/cancellation` (annulation client, #24)."""
    return client.post(
        f"/appointments/{appointment_id}/cancellation",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )


def _set_status(
    client: TestClient, token: str, salon_id: str, appointment_id: str, status: str
) -> dict:
    """`POST /salons/{salon_id}/appointments/{id}/status` (cycle gérant, #25)."""
    return client.post(
        f"/salons/{salon_id}/appointments/{appointment_id}/status",
        json={"status": status},
        headers={"Authorization": f"Bearer {token}"},
    )


def _modify(
    client: TestClient, token: str, appointment_id: str, *, date: datetime.date,
    start_time: str, service_id: str, hairdresser_id: str,
) -> dict:
    """`PATCH /appointments/{id}` (modification client, #23)."""
    return client.patch(
        f"/appointments/{appointment_id}",
        json={
            "date": date.isoformat(),
            "start_time": start_time,
            "service_ids": [service_id],
            "hairdresser_id": hairdresser_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestAppointmentNotificationE2E:
    """`POST /salons/{id}/appointments` bout-en-bout : insertion réelle de `notifications`."""

    # ── Parcours 1 : contenu de la ligne persistée ──────────────────────────────

    def test_successful_booking_persists_one_confirmation_row(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Une réservation réussie insère **exactement une** ligne `CONFIRMATION`/`PENDING`.

        Le RDV est réservé plusieurs jours à l'avance (`_next_monday`) : il porte
        **aussi** 3 rappels `REMINDER` (US-7.2, #46) — vérifiés séparément par
        `test_successful_booking_persists_three_reminder_rows_dated`. Ce test ne
        regarde que la ligne `CONFIRMATION`, inchangée par #46.
        """
        date = _next_monday()
        resp = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="09:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert resp.status_code == 201, f"Réservation échouée : {resp.text}"
        appointment_id = resp.json()["id"]

        rows = _confirmation_rows(_notifications_for_appointment(appointment_id))

        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "CONFIRMATION"
        assert row["status"] == "PENDING"
        assert row["sent_at"] is None
        assert row["channel"] == "SMS"
        assert row["scheduled_for"] is None

    def test_notification_linked_to_client_salon_and_appointment(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Chaque ligne (confirmation + rappels) rattache le bon `user_id`/`salon_id`/`appointment_id`."""
        date = _next_monday()
        resp = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="10:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert resp.status_code == 201, f"Réservation échouée : {resp.text}"
        appointment_id = resp.json()["id"]

        rows = _notifications_for_appointment(appointment_id)
        assert len(rows) == 1 + len(REMINDER_OFFSETS)
        for row in rows:
            assert str(row["user_id"]) == _fixture.client_a_id
            assert str(row["salon_id"]) == _fixture.salon_id
            assert str(row["appointment_id"]) == appointment_id

    def test_notification_title_and_message_are_templated_no_pii(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """`title`/`message` (confirmation + rappels) sont templatés, sans PII (téléphone, nom)."""
        date = _next_monday()
        resp = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="11:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert resp.status_code == 201, f"Réservation échouée : {resp.text}"
        appointment_id = resp.json()["id"]

        rows = _notifications_for_appointment(appointment_id)
        confirmation = _confirmation_rows(rows)[0]
        assert confirmation["title"] == "Réservation enregistrée"
        assert confirmation["message"] == "Votre rendez-vous a bien été enregistré."

        for reminder in _reminder_rows(rows):
            assert reminder["title"] == "Rappel de rendez-vous"
            assert reminder["message"] == "Vous avez un rendez-vous à venir."

        for row in rows:
            assert _PHONE_CLIENT_A_LOCAL not in row["title"]
            assert _PHONE_CLIENT_A_LOCAL not in row["message"]
            assert "Client E2E Notif A" not in row["title"]
            assert "Client E2E Notif A" not in row["message"]

    # ── Parcours 1bis : rappels planifiés (US-7.2, #46) ─────────────────────────

    def test_successful_booking_persists_three_reminder_rows_dated(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Un RDV réservé suffisamment loin planifie **3** rappels `REMINDER`/`PENDING` datés."""
        date = _next_monday()
        start_time = "09:00"
        resp = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time=start_time,
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert resp.status_code == 201, f"Réservation échouée : {resp.text}"
        appointment_id = resp.json()["id"]

        appointment_start = datetime.datetime.combine(
            date, datetime.time.fromisoformat(start_time)
        )
        expected_due = sorted(
            appointment_start - offset for offset in REMINDER_OFFSETS
        )

        reminders = _reminder_rows(_notifications_for_appointment(appointment_id))
        assert len(reminders) == 3

        actual_due = sorted(_as_naive_utc(row["scheduled_for"]) for row in reminders)
        assert actual_due == expected_due

        for row in reminders:
            assert row["status"] == "PENDING"
            assert row["sent_at"] is None
            assert row["channel"] == "SMS"

    # ── Parcours 2 : atomicité (rollback complet sur créneau refusé) ───────────

    def test_slot_conflict_leaves_zero_notifications(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Un créneau déjà pris (409) ne laisse **aucune** notification (rollback complet)."""
        date = _next_monday()
        first = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="14:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert first.status_code == 201, f"Première réservation échouée : {first.text}"

        before_count = _notification_count_for_salon(_fixture.salon_id)

        second = _book(
            _e2e_client,
            _fixture.token_b,
            _fixture.salon_id,
            date=date,
            start_time="14:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert second.status_code == 409, f"Conflit de créneau attendu : {second.text}"

        after_count = _notification_count_for_salon(_fixture.salon_id)

        # Le refus (409) ne doit ajouter aucune notification : seule la première
        # réservation (acceptée) en a émis une confirmation + ses rappels (#46).
        assert after_count == before_count
        assert after_count == 1 + len(REMINDER_OFFSETS)

    # ── Parcours 3 : la notification n'est jamais exposée dans la réponse HTTP ──

    def test_booking_response_never_exposes_notification_content(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """La réponse de réservation ne révèle ni le canal, ni le titre, ni le message."""
        date = _next_monday()
        resp = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="15:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert resp.status_code == 201, f"Réservation échouée : {resp.text}"
        assert "SMS" not in resp.text
        assert "CONFIRMATION" not in resp.text
        assert "Réservation enregistrée" not in resp.text
        assert "notification" not in resp.text.lower()

    # ── Parcours 4 : annulation du RDV → annulation des rappels (AC #46) ───────

    def test_client_cancellation_marks_pending_reminders_cancelled(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """`POST .../cancellation` annule (statut `CANCELLED`) les rappels `PENDING` du RDV."""
        date = _next_monday()
        booking = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="16:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert booking.status_code == 201, f"Réservation échouée : {booking.text}"
        appointment_id = booking.json()["id"]
        assert len(_reminder_rows(_notifications_for_appointment(appointment_id))) == 3

        cancellation = _cancel(_e2e_client, _fixture.token_a, appointment_id)
        assert cancellation.status_code == 200, f"Annulation échouée : {cancellation.text}"

        rows = _notifications_for_appointment(appointment_id)
        reminders = _reminder_rows(rows)
        assert len(reminders) == 3
        assert {row["status"] for row in reminders} == {"CANCELLED"}
        assert not [row for row in reminders if row["status"] == "PENDING"]

        # La confirmation (#45), déjà émise, n'est jamais touchée par l'annulation.
        confirmation = _confirmation_rows(rows)[0]
        assert confirmation["status"] == "PENDING"

    def test_manager_refusal_marks_pending_reminders_cancelled(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Refus gérant (`POST .../status` `CANCELLED`) annule les rappels `PENDING` du RDV."""
        date = _next_monday()
        booking = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="17:00",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert booking.status_code == 201, f"Réservation échouée : {booking.text}"
        appointment_id = booking.json()["id"]
        assert len(_reminder_rows(_notifications_for_appointment(appointment_id))) == 3

        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        refusal = _set_status(
            _e2e_client, manager_token, _fixture.salon_id, appointment_id, "CANCELLED"
        )
        assert refusal.status_code == 200, f"Refus échoué : {refusal.text}"

        reminders = _reminder_rows(_notifications_for_appointment(appointment_id))
        assert len(reminders) == 3
        assert {row["status"] for row in reminders} == {"CANCELLED"}

    def test_manager_confirmation_does_not_cancel_reminders(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Une transition `→ CONFIRMED` (pas une annulation) n'annule **aucun** rappel."""
        date = _next_monday()
        booking = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=date,
            start_time="09:30",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert booking.status_code == 201, f"Réservation échouée : {booking.text}"
        appointment_id = booking.json()["id"]

        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_LOCAL)
        confirmed = _set_status(
            _e2e_client, manager_token, _fixture.salon_id, appointment_id, "CONFIRMED"
        )
        assert confirmed.status_code == 200, f"Confirmation échouée : {confirmed.text}"

        reminders = _reminder_rows(_notifications_for_appointment(appointment_id))
        assert len(reminders) == 3
        assert {row["status"] for row in reminders} == {"PENDING"}

    # ── Parcours 5 : modification du RDV → re-planification des rappels ────────

    def test_modify_reschedules_reminders_to_new_slot(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """`PATCH /appointments/{id}` annule les anciens rappels et en recrée sur le nouveau créneau."""
        old_date = _next_monday()
        booking = _book(
            _e2e_client,
            _fixture.token_a,
            _fixture.salon_id,
            date=old_date,
            start_time="10:30",
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert booking.status_code == 201, f"Réservation échouée : {booking.text}"
        appointment_id = booking.json()["id"]
        assert len(_reminder_rows(_notifications_for_appointment(appointment_id))) == 3

        new_date = old_date + datetime.timedelta(days=7)
        new_start_time = "13:00"
        modified = _modify(
            _e2e_client,
            _fixture.token_a,
            appointment_id,
            date=new_date,
            start_time=new_start_time,
            service_id=_fixture.service_id,
            hairdresser_id=_fixture.hairdresser_id,
        )
        assert modified.status_code == 200, f"Modification échouée : {modified.text}"

        reminders = _reminder_rows(_notifications_for_appointment(appointment_id))
        # Les 3 anciens rappels sont annulés, 3 nouveaux sont planifiés sur le
        # nouveau créneau — aucun n'est supprimé (trace §8.4/§11.4 conservée).
        assert len(reminders) == 6
        cancelled = [row for row in reminders if row["status"] == "CANCELLED"]
        pending = [row for row in reminders if row["status"] == "PENDING"]
        assert len(cancelled) == 3
        assert len(pending) == 3

        new_start = datetime.datetime.combine(
            new_date, datetime.time.fromisoformat(new_start_time)
        )
        expected_due = sorted(new_start - offset for offset in REMINDER_OFFSETS)
        actual_due = sorted(_as_naive_utc(row["scheduled_for"]) for row in pending)
        assert actual_due == expected_due

        # La confirmation d'origine n'est jamais touchée par une modification.
        confirmation = _confirmation_rows(_notifications_for_appointment(appointment_id))[0]
        assert confirmation["status"] == "PENDING"
