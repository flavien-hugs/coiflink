"""Tests e2e pour US-7.1 — notification de confirmation de RDV (#45).

Groupe `TestAppointmentNotificationE2E` (PostgreSQL requis) :
    exerce le **chemin d'écriture réel** de `SqlNotificationRepository.enqueue` —
    l'insertion d'une ligne `notifications` dans la **même transaction** que la
    création du RDV (`BookAppointment`, patron `AuditLog` #20), vérifiée contre
    les contraintes réelles du schéma (FK `RESTRICT`, `CHECK` d'énumération).
    Les suites unitaires/API (adossées à un `FakeNotificationRepository` en
    mémoire) couvrent la règle métier (~20 assertions), mais aucune ne vérifie
    le contenu de la ligne **réellement persistée** — c'est le seul code qui
    satisfait le critère d'acceptation #45 *« à la création d'un RDV, une
    confirmation est émise/tracée »* (cf. finding de revue automatisée sur la
    PR #132).

Scénarios (spec `specs/notification-confirmation-rdv.md`, miroir
`test_service_demand_e2e.py` #41) :
    - une réservation réussie (`POST /salons/{id}/appointments`) insère
      **exactly une** ligne `notifications` `type=CONFIRMATION`,
      `status=PENDING`, `sent_at IS NULL`, `channel=SMS` (canal résolu selon
      disponibilité, MVP sans registre de jetons) ;
    - la ligne est **rattachée** au bon `user_id` (client), `salon_id` et
      `appointment_id` (mêmes valeurs que le RDV créé) ;
    - `title`/`message` sont les libellés templatés, **sans PII** (aucun
      téléphone, aucun nom) ;
    - la ligne persistée respecte les contraintes réelles du schéma (FK vers
      `users`/`salons`/`appointments`, `CHECK` d'énumération `type`/`channel`/
      `status`) — l'`INSERT` échouerait avec des valeurs hors domaine ;
    - une réservation **refusée** (créneau déjà pris, course perdue → `409`)
      ne laisse **aucune** notification (rollback complet, RDV + confirmation
      ensemble) ;
    - `401` sans jeton (deny-by-default, hors périmètre de la notification
      elle-même, testé ailleurs — non répété ici) ;
    - la réponse HTTP de réservation ne révèle **jamais** l'existence ni le
      contenu de la notification (canal, titre, message absents du corps).

Le décor (salon réservable, horaires, coiffeur, prestation, client) est monté
**via l'API réelle** (miroir `test_appointment_concurrency.py`, #21) — la
réservation elle-même passe par `POST /salons/{id}/appointments`, jamais un
bypass SQL : c'est précisément le chemin `BookAppointment` qui émet la
confirmation.

**Note d'ordre de nettoyage** (mémoire projet) : depuis #45, une réservation
réussie insère une ligne `notifications` dont les FK sont `ON DELETE
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
                "title, message, status, sent_at "
                "FROM notifications WHERE appointment_id = :aid"
            ),
            {"aid": appointment_id},
        ).mappings().all()
        return [dict(row) for row in rows]


def _notification_count_for_salon(salon_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM notifications WHERE salon_id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestAppointmentNotificationE2E:
    """`POST /salons/{id}/appointments` bout-en-bout : insertion réelle de `notifications`."""

    # ── Parcours 1 : contenu de la ligne persistée ──────────────────────────────

    def test_successful_booking_persists_one_confirmation_row(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Une réservation réussie insère **exactement une** ligne `CONFIRMATION`/`PENDING`."""
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

        rows = _notifications_for_appointment(appointment_id)

        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "CONFIRMATION"
        assert row["status"] == "PENDING"
        assert row["sent_at"] is None
        assert row["channel"] == "SMS"

    def test_notification_linked_to_client_salon_and_appointment(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """La ligne rattache le bon `user_id` (client), `salon_id` et `appointment_id`."""
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
        assert len(rows) == 1
        row = rows[0]
        assert str(row["user_id"]) == _fixture.client_a_id
        assert str(row["salon_id"]) == _fixture.salon_id
        assert str(row["appointment_id"]) == appointment_id

    def test_notification_title_and_message_are_templated_no_pii(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """`title`/`message` sont les libellés templatés, sans PII (téléphone, nom)."""
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
        assert len(rows) == 1
        row = rows[0]
        assert row["title"] == "Réservation enregistrée"
        assert row["message"] == "Votre rendez-vous a bien été enregistré."
        assert _PHONE_CLIENT_A_LOCAL not in row["title"]
        assert _PHONE_CLIENT_A_LOCAL not in row["message"]
        assert "Client E2E Notif A" not in row["title"]
        assert "Client E2E Notif A" not in row["message"]

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
        # réservation (acceptée) en a émis une.
        assert after_count == before_count
        assert after_count == 1

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
