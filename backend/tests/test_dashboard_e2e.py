"""Tests e2e pour le Dashboard Manager — activité du salon (#148).

Groupes (PostgreSQL requis) exerçant le **chemin SQL réel** des six routes
`/salons/{id}/dashboard/*` — aucune suite unitaire/API (adossée à des fakes en
mémoire, `test_dashboard_usecases.py`/`test_dashboard_api.py`) ne vérifie :

    - le prédicat **`slot @> now`** (colonne générée `tsrange`, dérivation
      « en cours » sans statut ni migration) — `dashboard/kpis.in_progress` et
      `dashboard/in-progress` ;
    - les **jointures de noms** (`users` ×2 + `services`) de
      `list_in_progress_details` — émission maîtrisée (§11.3) ;
    - les **agrégats `GROUP BY`** réels (`count_by_status_in_range`,
      `count_distinct_completed_clients`, `attendance_series`) et la
      **conversion de fuseau** de `net_revenue_series`
      (`date(timezone('Africa/Abidjan', created_at))`) ;
    - le **flux fusionné, trié et dédupliqué** de `ListRecentActivity`
      (paiements réels + notifications salon réelles) ;
    - les **alertes dérivées** (`late`/`prolonged_wait`/`payment_anomaly`) sur
      des RDV et écarts de caisse réels ;
    - l'**isolation §11.2** inter-salons et l'absence de PII (§11.3) sur des
      réponses réellement matérialisées par PostgreSQL.

Les RDV/notifications/lignes de caisse sont insérés **directement en base**
(bypass des gardes HTTP de réservation, patron `test_hairdresser_performance_e2e.py`
#43) pour contrôler statut, date et horodatage sans dépendre du parcours de
réservation complet (déjà couvert par #21/#45/#46/#48). Les **paiements** de la
timeline passent par l'API réelle (`POST /payments`) — c'est ce chemin que
`ListRecentActivity` lit (patron #36/#43).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_dashboard_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225079998xxxx).
"""

from __future__ import annotations

import datetime
import decimal
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
from coiflink_api.domain.time_window import SALON_TIMEZONE
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-dashboard-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e du dashboard d'activité (#148).
_E2E_PHONE_PREFIX = "+225079998"
_PHONE_MANAGER_A_LOCAL = "0799980001"
_PHONE_MANAGER_B_LOCAL = "0799980002"
_PHONE_CLIENT_A_LOCAL = "0799980003"
_PHONE_CLIENT_B_LOCAL = "0799980004"
_PHONE_HAIRDRESSER_LOCAL = "0799980005"
_PASSWORD = "dashboard-activite-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-dashboard-activite-a"
_SALON_NAME_B = "e2e-salon-dashboard-activite-b"

_DASHBOARD_ROUTES = (
    "dashboard/kpis",
    "dashboard/revenue-series",
    "dashboard/attendance-series",
    "dashboard/in-progress",
    "dashboard/activity",
    "dashboard/alerts",
)


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → notifications → cash_journal → payments →
    appointment_services → appointments → services → salon_members → salons →
    users. `notifications` **avant** `appointments`/`salons`/`users` (mémoire
    projet, FK RESTRICT depuis #45) ; `cash_journal` **avant** `payments`
    (FK composite `(salon_id, transaction_id) → payments`).
    """
    engine = get_engine()
    with engine.connect() as conn:
        for table, column in (
            ("audit_logs", "salon_id"),
            ("notifications", "salon_id"),
            ("cash_journal", "salon_id"),
            ("payments", "salon_id"),
            ("appointment_services", "salon_id"),
            ("appointments", "salon_id"),
            ("services", "salon_id"),
        ):
            conn.execute(
                text(
                    f"DELETE FROM {table} WHERE {column} IN "
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

    Skip si `DATABASE_URL` absent. Nettoie les données de test (plage
    +225079998) avant et après chaque test.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e du dashboard d'activité.")

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


# ─── Helpers — décor (comptes, salon, service, coiffeur) ─────────────────────


def _register_manager(client: TestClient, *, phone: str) -> str:
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Dashboard", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client_account(client: TestClient, *, phone: str, full_name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"full_name": full_name, "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_salon(client: TestClient, token: str, *, name: str) -> str:
    resp = client.post("/salons", json={"name": name}, headers=_auth(token))
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(
    client: TestClient, token: str, salon_id: str, *, name: str, price: str
) -> str:
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": name, "price": price, "duration_minutes": 30},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _add_hairdresser(
    client: TestClient, manager_token: str, salon_id: str, *, full_name: str, phone: str
) -> str:
    resp_register = client.post(
        "/auth/register",
        json={"full_name": full_name, "phone": phone, "password": _PASSWORD},
    )
    assert resp_register.status_code == 201, (
        f"Inscription coiffeur échouée : {resp_register.text}"
    )
    hairdresser_id = resp_register.json()["id"]

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET role = 'HAIRDRESSER' WHERE id = :uid"),
            {"uid": hairdresser_id},
        )
        conn.execute(
            text(
                "INSERT INTO salon_members (salon_id, user_id, role) "
                "VALUES (:salon_id, :uid, 'HAIRDRESSER')"
            ),
            {"salon_id": salon_id, "uid": hairdresser_id},
        )
        conn.commit()
    return hairdresser_id


# ─── Helpers — bypass SQL (RDV, prestations, notifications, caisse) ──────────


def _seed_appointment(
    salon_id: str,
    client_id: str,
    hairdresser_id: str | None,
    *,
    day: datetime.date,
    start_time: datetime.time,
    end_time: datetime.time,
    status: str,
    service_id: str | None = None,
    price_at_booking: str | None = None,
) -> str:
    """Insère directement en base un RDV (statut/jour/créneau/coiffeur contrôlés).

    Bypass des gardes de réservation HTTP — seul le SQL des lectures dashboard
    est exercé ici (parcours complet déjà couvert par #21/#45/#46). Alimente la
    colonne générée `slot` (`tsrange`), base du prédicat réel `slot @> now`.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "INSERT INTO appointments "
                "(salon_id, client_id, hairdresser_id, appointment_date, "
                "start_time, end_time, status) "
                "VALUES (:salon_id, :client_id, :hairdresser_id, :day, "
                ":start_time, :end_time, :status) RETURNING id"
            ),
            {
                "salon_id": salon_id,
                "client_id": client_id,
                "hairdresser_id": hairdresser_id,
                "day": day,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "status": status,
            },
        )
        appointment_id = row.scalar_one()
        if service_id is not None:
            conn.execute(
                text(
                    "INSERT INTO appointment_services "
                    "(salon_id, appointment_id, service_id, price_at_booking) "
                    "VALUES (:salon_id, :appointment_id, :service_id, :price)"
                ),
                {
                    "salon_id": salon_id,
                    "appointment_id": str(appointment_id),
                    "service_id": service_id,
                    "price": price_at_booking,
                },
            )
        conn.commit()
    return str(appointment_id)


def _attach_service(
    salon_id: str, appointment_id: str, service_id: str, *, price: str
) -> None:
    """Ajoute une **deuxième** prestation à un RDV déjà créé (liste en-cours, #148)."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO appointment_services "
                "(salon_id, appointment_id, service_id, price_at_booking) "
                "VALUES (:salon_id, :appointment_id, :service_id, :price)"
            ),
            {
                "salon_id": salon_id,
                "appointment_id": appointment_id,
                "service_id": service_id,
                "price": price,
            },
        )
        conn.commit()


def _seed_notification(
    salon_id: str,
    appointment_id: str | None,
    *,
    type_: str,
    title: str,
    message: str,
    created_at: datetime.datetime,
    user_id: str | None = None,
    channel: str = "IN_APP",
) -> str:
    """Insère directement une ligne `notifications` (horodatage contrôlé, #148).

    Bypass de l'émission applicative (#45–#48, déjà couverte par
    `test_appointment_notification_e2e.py`) : seule la **lecture** salon-scopée
    `SqlNotificationRepository.list_for_salon` (nouvelle, #148) est exercée ici.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "INSERT INTO notifications "
                "(user_id, salon_id, appointment_id, type, channel, title, "
                "message, status, created_at) "
                "VALUES (:user_id, :salon_id, :appointment_id, :type, :channel, "
                ":title, :message, 'PENDING', :created_at) RETURNING id"
            ),
            {
                "user_id": user_id,
                "salon_id": salon_id,
                "appointment_id": appointment_id,
                "type": type_,
                "channel": channel,
                "title": title,
                "message": message,
                "created_at": created_at,
            },
        )
        notification_id = row.scalar_one()
        conn.commit()
    return str(notification_id)


def _seed_cash_journal(
    salon_id: str,
    performed_by: str,
    *,
    amount: str,
    created_at: datetime.datetime,
    operation_type: str = "PAYMENT",
) -> None:
    """Insère directement une ligne `cash_journal` (jour/horodatage contrôlés, #148).

    Bypass de l'écriture applicative (`RecordPayment`, #34/#35, déjà couverte
    ailleurs) : seule la **lecture agrégée** `net_revenue_series` (nouvelle,
    #148 — conversion de fuseau `Africa/Abidjan` incluse) est exercée ici.
    `transaction_id` reste `NULL` (nullable, aucune jointure requise par la
    lecture testée).
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO cash_journal "
                "(salon_id, operation_type, amount, performed_by, created_at) "
                "VALUES (:salon_id, :operation_type, :amount, :performed_by, :created_at)"
            ),
            {
                "salon_id": salon_id,
                "operation_type": operation_type,
                "amount": amount,
                "performed_by": performed_by,
                "created_at": created_at,
            },
        )
        conn.commit()


def _record_payment_for_appointment(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    amount: str,
    appointment_id: str,
    client_id: str,
) -> str:
    """Enregistre un paiement `VALIDATED` **via l'API réelle** — alimente la
    timeline d'activité (`ListRecentActivity`, patron #36/#43)."""
    resp = client.post(
        f"/salons/{salon_id}/payments",
        json={
            "amount": amount,
            "payment_method": "CASH",
            "appointment_id": appointment_id,
            "client_id": client_id,
        },
        headers=_auth(manager_token),
    )
    assert resp.status_code == 201, f"Enregistrement paiement échoué : {resp.text}"
    return resp.json()["id"]


def _day_noon(day: datetime.date) -> datetime.datetime:
    """Midi (fuseau salon) du jour civil donné — bucket sans ambiguïté de bord."""
    return datetime.datetime.combine(day, datetime.time(12, 0), tzinfo=SALON_TIMEZONE)


def _now_salon() -> datetime.datetime:
    """Instant présent **naïf** dans le fuseau salon (`Africa/Abidjan`, #148)."""
    return datetime.datetime.now(SALON_TIMEZONE).replace(tzinfo=None)


# ─── Helpers — appels des routes dashboard ────────────────────────────────────


def _dashboard_kpis(client: TestClient, token: str, salon_id: str, **params: object) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/dashboard/kpis", params=params, headers=_auth(token)
    )
    assert resp.status_code == 200, f"KPI dashboard échoués : {resp.text}"
    return resp.json()


def _dashboard_revenue_series(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/dashboard/revenue-series", params=params, headers=_auth(token)
    )
    assert resp.status_code == 200, f"Série CA échouée : {resp.text}"
    return resp.json()


def _dashboard_attendance_series(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/dashboard/attendance-series", params=params, headers=_auth(token)
    )
    assert resp.status_code == 200, f"Série fréquentation échouée : {resp.text}"
    return resp.json()


def _dashboard_in_progress(client: TestClient, token: str, salon_id: str) -> dict:
    resp = client.get(f"/salons/{salon_id}/dashboard/in-progress", headers=_auth(token))
    assert resp.status_code == 200, f"Prestations en cours échouées : {resp.text}"
    return resp.json()


def _dashboard_activity(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/dashboard/activity", params=params, headers=_auth(token)
    )
    assert resp.status_code == 200, f"Timeline d'activité échouée : {resp.text}"
    return resp.json()


def _dashboard_alerts(client: TestClient, token: str, salon_id: str) -> dict:
    resp = client.get(f"/salons/{salon_id}/dashboard/alerts", headers=_auth(token))
    assert resp.status_code == 200, f"Alertes dashboard échouées : {resp.text}"
    return resp.json()


# ─── Groupe 1 : KPI — agrégats réels + évolution + prédicat `slot @> now` ────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardKpisE2E:
    """`GET /salons/{id}/dashboard/kpis` bout-en-bout : `GROUP BY`/évolution SQL réels."""

    def test_waiting_and_clients_kpis_reflect_real_aggregates_with_evolution(
        self, _e2e_client: TestClient
    ) -> None:
        """`waiting_clients`/`clients_count` dérivent de `GROUP BY status`/`COUNT(DISTINCT)` réels.

        Aujourd'hui : 2 RDV `PENDING` (attente), 1 RDV `COMPLETED` (client A) → en
        attente = 2, clientes = 1. Hier (période précédente, longueur 1 jour) :
        1 RDV `PENDING`, 1 RDV `COMPLETED` (client B) → en attente = 1, clientes = 1.
        Évolution « en attente » = up (2 > 1).
        """
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente A"
        )
        client_b = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_B_LOCAL, full_name="Cliente B"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        today = _now_salon().date()
        yesterday = today - datetime.timedelta(days=1)

        # Aujourd'hui.
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 30),
            status="PENDING",
        )
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=datetime.time(10, 0), end_time=datetime.time(10, 30),
            status="PENDING",
        )
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=datetime.time(11, 0), end_time=datetime.time(11, 30),
            status="COMPLETED",
        )
        # Hier (période précédente).
        _seed_appointment(
            salon_id, client_b, None, day=yesterday,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 30),
            status="PENDING",
        )
        _seed_appointment(
            salon_id, client_b, None, day=yesterday,
            start_time=datetime.time(10, 0), end_time=datetime.time(10, 30),
            status="COMPLETED",
        )

        kpis = _dashboard_kpis(
            _e2e_client, manager_token, salon_id,
            period="custom", date_from=today.isoformat(), date_to=today.isoformat(),
        )

        assert kpis["waiting_clients"]["current"] == 2
        assert kpis["waiting_clients"]["previous"] == 1
        assert kpis["waiting_clients"]["direction"] == "up"
        assert kpis["clients_count"]["current"] == 1
        assert kpis["clients_count"]["previous"] == 1
        assert kpis["period"]["date_from"] == today.isoformat()
        assert kpis["period"]["date_to"] == today.isoformat()

    def test_revenue_kpi_reflects_real_cash_journal_net_with_evolution(
        self, _e2e_client: TestClient
    ) -> None:
        """`revenue` dérive du **net `cash_journal`** réel (pas d'un comptage de RDV)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        today = _now_salon().date()
        yesterday = today - datetime.timedelta(days=1)

        _seed_cash_journal(
            salon_id, manager_id, amount="15000.00", created_at=_day_noon(today)
        )
        _seed_cash_journal(
            salon_id, manager_id, amount="10000.00", created_at=_day_noon(yesterday)
        )
        # Un `REFUND` n'entre pas dans le net (seuls PAYMENT/ADJUSTMENT comptent).
        _seed_cash_journal(
            salon_id, manager_id, amount="-2000.00", created_at=_day_noon(today),
            operation_type="REFUND",
        )

        kpis = _dashboard_kpis(
            _e2e_client, manager_token, salon_id,
            period="custom", date_from=today.isoformat(), date_to=today.isoformat(),
        )

        assert decimal.Decimal(kpis["revenue"]["current"]) == decimal.Decimal("15000.00")
        assert decimal.Decimal(kpis["revenue"]["previous"]) == decimal.Decimal("10000.00")
        assert kpis["revenue"]["direction"] == "up"
        assert kpis["revenue"]["currency"] == "XOF"

    def test_in_progress_kpi_derived_from_real_slot_predicate(
        self, _e2e_client: TestClient
    ) -> None:
        """`in_progress` compte les `CONFIRMED` dont `slot @> now` (SQL réel, pas un fake)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente En Cours"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        now = _now_salon()
        today = now.date()

        # En cours : créneau [now-15min, now+15min).
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=(now - datetime.timedelta(minutes=15)).time(),
            end_time=(now + datetime.timedelta(minutes=15)).time(),
            status="CONFIRMED",
        )
        # Hors créneau : dans 3h.
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=(now + datetime.timedelta(hours=3)).time(),
            end_time=(now + datetime.timedelta(hours=3, minutes=30)).time(),
            status="CONFIRMED",
        )
        # PENDING dans le même créneau horaire : exclu par le statut, jamais « en cours ».
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=(now - datetime.timedelta(minutes=10)).time(),
            end_time=(now + datetime.timedelta(minutes=10)).time(),
            status="PENDING",
        )

        kpis = _dashboard_kpis(_e2e_client, manager_token, salon_id)
        assert kpis["in_progress"]["current"] == 1

    def test_other_salon_data_excluded_from_kpis(self, _e2e_client: TestClient) -> None:
        """Isolation §11.2 : les RDV du salon B n'entrent jamais dans les KPI du salon A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        client_b = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_B_LOCAL, full_name="Cliente Salon B"
        )
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        today = _now_salon().date()
        _seed_appointment(
            salon_b_id, client_b, None, day=today,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 30),
            status="PENDING",
        )
        _seed_cash_journal(
            salon_b_id, manager_b_id, amount="50000.00", created_at=_day_noon(today)
        )

        kpis = _dashboard_kpis(_e2e_client, token_a, salon_a_id)
        assert kpis["waiting_clients"]["current"] == 0
        assert decimal.Decimal(kpis["revenue"]["current"]) == decimal.Decimal("0.00")

    def test_kpis_response_has_no_pii(self, _e2e_client: TestClient) -> None:
        """§11.3 : compteurs-only, aucun `client_id`/téléphone/jeton dans la réponse."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente Confidentielle"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        today = _now_salon().date()
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 30),
            status="PENDING",
        )

        resp = _e2e_client.get(
            f"/salons/{salon_id}/dashboard/kpis", headers=_auth(manager_token)
        )
        assert resp.status_code == 200
        assert client_a not in resp.text
        assert manager_token not in resp.text
        assert "Cliente Confidentielle" not in resp.text

    def test_no_token_returns_401_on_every_dashboard_route(
        self, _e2e_client: TestClient
    ) -> None:
        """Deny-by-default (ADR-0015) : les six routes `dashboard/*` refusent sans jeton."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        assert manager_id

        for route in _DASHBOARD_ROUTES:
            resp = _e2e_client.get(f"/salons/{salon_id}/{route}")
            assert resp.status_code == 401, f"{route} devrait refuser sans jeton"

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Le jeton du gérant A est refusé pour consulter le dashboard du salon B."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        for route in _DASHBOARD_ROUTES:
            resp = _e2e_client.get(
                f"/salons/{salon_b_id}/{route}", headers=_auth(token_a)
            )
            assert resp.status_code == 403, f"{route} devrait refuser hors périmètre"


# ─── Groupe 2 : prestations en cours — jointures de noms réelles ─────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardInProgressE2E:
    """`GET /salons/{id}/dashboard/in-progress` : jointures `users`×2 + `services` réelles."""

    def test_in_progress_list_resolves_names_via_real_joins(
        self, _e2e_client: TestClient
    ) -> None:
        """Cliente, coiffeuse et prestations résolues par jointure SQL réelle (#43/#36)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Awa Koné"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id,
            full_name="Fatou D.", phone=_PHONE_HAIRDRESSER_LOCAL,
        )
        service_1 = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe femme", price="10000.00"
        )
        service_2 = _create_service(
            _e2e_client, manager_token, salon_id, name="Coloration", price="20000.00"
        )

        now = _now_salon()
        today = now.date()
        appointment_id = _seed_appointment(
            salon_id, client_a, hairdresser_id, day=today,
            start_time=(now - datetime.timedelta(minutes=20)).time(),
            end_time=(now + datetime.timedelta(minutes=40)).time(),
            status="CONFIRMED",
            service_id=service_1, price_at_booking="10000.00",
        )
        _attach_service(salon_id, appointment_id, service_2, price="20000.00")

        # Hors créneau — ne doit jamais apparaître.
        _seed_appointment(
            salon_id, client_a, hairdresser_id, day=today,
            start_time=(now + datetime.timedelta(hours=4)).time(),
            end_time=(now + datetime.timedelta(hours=4, minutes=30)).time(),
            status="CONFIRMED",
        )

        result = _dashboard_in_progress(_e2e_client, manager_token, salon_id)

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["appointment_id"] == appointment_id
        assert item["client_name"] == "Awa Koné"
        assert item["hairdresser_name"] == "Fatou D."
        assert set(item["service_names"]) == {"Coupe femme", "Coloration"}
        assert item["status"] == "CONFIRMED"

        # Émission maîtrisée (§11.3) : le nom d'affichage est présent, jamais un
        # identifiant ou un contact.
        raw = _e2e_client.get(
            f"/salons/{salon_id}/dashboard/in-progress", headers=_auth(manager_token)
        ).text
        assert client_a not in raw
        assert hairdresser_id not in raw
        assert _PHONE_HAIRDRESSER_LOCAL not in raw

    def test_in_progress_empty_when_nothing_in_slot(self, _e2e_client: TestClient) -> None:
        """Aucun RDV `CONFIRMED` en cours → liste vide (état légitime, pas une erreur)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        result = _dashboard_in_progress(_e2e_client, manager_token, salon_id)
        assert result["items"] == []


# ─── Groupe 3 : séries temporelles — `GROUP BY` + fuseau réels ───────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardSeriesE2E:
    """`revenue-series`/`attendance-series` : agrégats `GROUP BY` réels, zero-fill."""

    def test_revenue_series_buckets_reflect_real_cash_journal_with_zero_fill(
        self, _e2e_client: TestClient
    ) -> None:
        """Bucket = jour civil `Africa/Abidjan` réel ; jour sans opération = `0.00`."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        today = _now_salon().date()
        two_days_ago = today - datetime.timedelta(days=2)
        # `yesterday` reste sans opération → bucket à "0.00" (zero-fill du domaine).

        _seed_cash_journal(
            salon_id, manager_id, amount="8000.00", created_at=_day_noon(two_days_ago)
        )
        _seed_cash_journal(
            salon_id, manager_id, amount="5000.00", created_at=_day_noon(today)
        )

        series = _dashboard_revenue_series(
            _e2e_client, manager_token, salon_id,
            period="custom", date_from=two_days_ago.isoformat(), date_to=today.isoformat(),
        )

        by_day = {b["bucket_start"]: decimal.Decimal(b["total"]) for b in series["buckets"]}
        assert len(series["buckets"]) == 3
        assert by_day[two_days_ago.isoformat()] == decimal.Decimal("8000.00")
        assert by_day[(today - datetime.timedelta(days=1)).isoformat()] == decimal.Decimal(
            "0.00"
        )
        assert by_day[today.isoformat()] == decimal.Decimal("5000.00")
        assert series["currency"] == "XOF"

    def test_attendance_series_buckets_reflect_real_appointment_counts_with_zero_fill(
        self, _e2e_client: TestClient
    ) -> None:
        """Bucket = nombre de RDV (tous statuts) par jour ; jour sans RDV = `0`."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente Fréquentation"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        today = _now_salon().date()
        two_days_ago = today - datetime.timedelta(days=2)

        _seed_appointment(
            salon_id, client_a, None, day=two_days_ago,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 30), status="CANCELLED",
        )
        for start_hour in (9, 10):
            _seed_appointment(
                salon_id, client_a, None, day=today,
                start_time=datetime.time(start_hour, 0), end_time=datetime.time(start_hour, 30),
                status="PENDING",
            )

        series = _dashboard_attendance_series(
            _e2e_client, manager_token, salon_id,
            period="custom", date_from=two_days_ago.isoformat(), date_to=today.isoformat(),
        )

        by_day = {b["bucket_start"]: b["count"] for b in series["buckets"]}
        assert by_day[two_days_ago.isoformat()] == 1
        assert by_day[(today - datetime.timedelta(days=1)).isoformat()] == 0
        assert by_day[today.isoformat()] == 2


# ─── Groupe 4 : timeline d'activité — flux fusionné réel ─────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardActivityE2E:
    """`GET /salons/{id}/dashboard/activity` : paiements + notifications réels fusionnés."""

    def test_activity_merges_real_payments_and_notifications_sorted_and_deduped(
        self, _e2e_client: TestClient
    ) -> None:
        """Flux trié décroissant, dédupliqué par `(type, appointment_id)`, kinds neutres."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente Activité"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="12000.00"
        )

        today = _now_salon().date()
        appointment_id = _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 30),
            status="COMPLETED",
            service_id=service_id, price_at_booking="12000.00",
        )
        _record_payment_for_appointment(
            _e2e_client, manager_token, salon_id,
            amount="12000.00", appointment_id=appointment_id, client_id=client_a,
        )

        base = datetime.datetime.now(datetime.timezone.utc)
        _seed_notification(
            salon_id, appointment_id,
            type_="NEW_BOOKING", title="Nouvelle réservation",
            message="Une nouvelle réservation a été effectuée.",
            created_at=base - datetime.timedelta(hours=3),
        )
        _seed_notification(
            salon_id, appointment_id,
            type_="CANCELLATION", title="Réservation annulée",
            message="Une réservation a été annulée.",
            created_at=base - datetime.timedelta(hours=2),
        )
        # Doublon (même type + même RDV, horodatage différent) → dédupliqué : un
        # seul évènement `appointment_update` doit survivre (le plus récent).
        _seed_notification(
            salon_id, appointment_id,
            type_="APPOINTMENT_UPDATE", title="RDV modifié (ancien)",
            message="Le rendez-vous a été modifié.",
            created_at=base - datetime.timedelta(hours=1, minutes=30),
        )
        _seed_notification(
            salon_id, appointment_id,
            type_="APPOINTMENT_UPDATE", title="RDV modifié (récent)",
            message="Le rendez-vous a été modifié.",
            created_at=base - datetime.timedelta(minutes=45),
        )
        # Notification **client** (hors activité salon, #148 Non-Goals) : jamais dans le flux.
        _seed_notification(
            salon_id, appointment_id,
            type_="CONFIRMATION", title="RDV confirmé",
            message="Votre rendez-vous est confirmé.",
            created_at=base - datetime.timedelta(minutes=30),
        )

        feed = _dashboard_activity(_e2e_client, manager_token, salon_id, limit=20)
        items = feed["items"]

        kinds = [item["kind"] for item in items]
        assert kinds.count("appointment_update") == 1
        assert "payment" in kinds
        assert "new_booking" in kinds
        assert "cancellation" in kinds
        assert "confirmation" not in kinds

        update_item = next(item for item in items if item["kind"] == "appointment_update")
        assert update_item["label"] == "RDV modifié (récent)"

        occurred_at = [
            datetime.datetime.fromisoformat(item["occurred_at"]) for item in items
        ]
        assert occurred_at == sorted(occurred_at, reverse=True)

        payment_item = next(item for item in items if item["kind"] == "payment")
        assert decimal.Decimal(payment_item["amount"]) == decimal.Decimal("12000.00")
        assert payment_item["client_name"] == "Cliente Activité"

        notification_item = next(item for item in items if item["kind"] == "new_booking")
        assert notification_item["amount"] is None
        assert notification_item["client_name"] is None

    def test_activity_respects_limit_top_n(self, _e2e_client: TestClient) -> None:
        """`limit` borne le flux fusionné (garde de coût §12.1, top-N)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente Limite"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        today = _now_salon().date()

        # Chaque notification porte un `appointment_id` **distinct** — la déduplication
        # par `(type, appointment_id)` ne doit fusionner que des doublons d'un même RDV.
        base = datetime.datetime.now(datetime.timezone.utc)
        for offset_minutes in range(5):
            appointment_id = _seed_appointment(
                salon_id, client_a, None, day=today,
                start_time=datetime.time(8 + offset_minutes, 0),
                end_time=datetime.time(8 + offset_minutes, 30),
                status="PENDING",
            )
            _seed_notification(
                salon_id, appointment_id,
                type_="NEW_BOOKING", title=f"Réservation {offset_minutes}",
                message="Une nouvelle réservation a été effectuée.",
                created_at=base - datetime.timedelta(minutes=offset_minutes),
            )

        feed = _dashboard_activity(_e2e_client, manager_token, salon_id, limit=2)
        assert len(feed["items"]) == 2

    def test_activity_isolated_per_salon(self, _e2e_client: TestClient) -> None:
        """Isolation §11.2 : une notification du salon B n'apparaît jamais dans le flux A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        _seed_notification(
            salon_b_id, None,
            type_="NEW_BOOKING", title="Réservation salon B",
            message="Une nouvelle réservation a été effectuée.",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )

        feed_a = _dashboard_activity(_e2e_client, token_a, salon_a_id)
        assert feed_a["items"] == []


# ─── Groupe 5 : alertes — dérivées de faits réels ────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardAlertsE2E:
    """`GET /salons/{id}/dashboard/alerts` : `late`/`prolonged_wait`/`payment_anomaly` réels."""

    def test_alerts_derived_from_real_late_prolonged_wait_and_payment_anomaly(
        self, _e2e_client: TestClient
    ) -> None:
        """Trois alertes dérivées de RDV et d'un écart de caisse réellement persistés."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente Alertes"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        now = _now_salon()
        today = now.date()

        # `late` : CONFIRMED dont le créneau est passé sans clôture.
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=(now - datetime.timedelta(hours=2)).time(),
            end_time=(now - datetime.timedelta(hours=1)).time(),
            status="CONFIRMED",
        )
        # `prolonged_wait` : PENDING dont le début est dépassé, non confirmé.
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=(now - datetime.timedelta(hours=1)).time(),
            end_time=(now + datetime.timedelta(minutes=30)).time(),
            status="PENDING",
        )
        # `payment_anomaly` : COMPLETED sans aucun paiement rattaché (#36).
        _seed_appointment(
            salon_id, client_a, None, day=today,
            start_time=datetime.time(8, 0), end_time=datetime.time(8, 30),
            status="COMPLETED",
        )

        alerts = _dashboard_alerts(_e2e_client, manager_token, salon_id)
        by_kind = {item["kind"]: item for item in alerts["items"]}

        assert by_kind["late"]["count"] >= 1
        assert by_kind["late"]["severity"] == "warning"
        assert by_kind["prolonged_wait"]["count"] >= 1
        assert by_kind["prolonged_wait"]["severity"] == "info"
        assert by_kind["payment_anomaly"]["count"] >= 1
        assert by_kind["payment_anomaly"]["severity"] == "warning"

        # Ordre d'affichage stable (autorité serveur).
        kinds_order = [item["kind"] for item in alerts["items"]]
        assert kinds_order.index("payment_anomaly") < kinds_order.index("late")
        assert kinds_order.index("late") < kinds_order.index("prolonged_wait")

    def test_alerts_empty_when_no_alerts(self, _e2e_client: TestClient) -> None:
        """Salon sans RDV en retard/attente prolongée ni écart de caisse → liste vide."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        alerts = _dashboard_alerts(_e2e_client, manager_token, salon_id)
        assert alerts["items"] == []

    def test_alerts_isolated_per_salon(self, _e2e_client: TestClient) -> None:
        """Isolation §11.2 : un RDV en retard du salon B n'entre jamais dans les alertes A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        client_b = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_B_LOCAL, full_name="Cliente Salon B Alertes"
        )
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        now = _now_salon()
        today = now.date()
        _seed_appointment(
            salon_b_id, client_b, None, day=today,
            start_time=(now - datetime.timedelta(hours=2)).time(),
            end_time=(now - datetime.timedelta(hours=1)).time(),
            status="CONFIRMED",
        )

        alerts_a = _dashboard_alerts(_e2e_client, token_a, salon_a_id)
        assert alerts_a["items"] == []
