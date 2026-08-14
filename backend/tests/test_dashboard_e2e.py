"""Tests e2e pour le Dashboard Manager — activité du salon, pivot walk-in (#148).

Groupes (PostgreSQL requis) exerçant le **chemin SQL réel** des six routes
`/salons/{id}/dashboard/*` — aucune suite unitaire/API (adossée à des fakes en
mémoire, `test_dashboard_usecases.py`/`test_dashboard_api.py`) ne vérifie :

    - les **agrégats `GROUP BY`** réels sur `queue_tickets`
      (`count_by_status_in_range`, `count_distinct_completed_clients`,
      `attendance_series`) et le **net `cash_journal`** (`net_revenue_series`) ;
    - le décompte **direct** des tickets `in_progress` (`count_in_progress`,
      `list_in_progress_details`) — plus aucune arithmétique de créneau (l'ancien
      prédicat RDV `slot @> now` a disparu avec le pivot walk-in exclusif) ;
    - les **jointures de noms** (`customer_profiles` + `users` + `services`) de
      `list_in_progress_details` — émission maîtrisée (§11.3) ;
    - le flux d'activité **borné aux paiements réels** (`ListRecentActivity`,
      #148) — les notifications ont disparu avec le pivot, plus rien à notifier
      pour un client déjà sur place ;
    - les alertes **dérivées** de faits réels sur des tickets et écarts de caisse
      réels (`prolonged_wait`/`payment_anomaly` — l'ancienne alerte `late`,
      propre au créneau RDV, n'a pas d'équivalent walk-in et a été retirée) ;
    - l'**isolation §11.2** inter-salons et l'absence de PII (§11.3) sur des
      réponses réellement matérialisées par PostgreSQL.

Les tickets/prestations/lignes de caisse sont insérés **directement en base**
(bypass des gardes HTTP de la borne walk-in, patron `test_hairdresser_performance_
e2e.py` #43) pour contrôler statut, jour et horodatage sans dépendre du parcours de
prise en charge complet (déjà couvert par #157/#150). Les **paiements** de la
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
import uuid
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

    Ordre : audit_logs → cash_journal → payments → queue_ticket_services →
    queue_tickets → customer_profiles → services → salon_members → salons →
    users. La table `notifications` a été supprimée par la migration
    destructive `0017` avec tout le module Rendez-vous/Notification — plus
    rien à nettoyer ici.
    """
    engine = get_engine()
    salons_of_prefix = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}
    with engine.connect() as conn:
        conn.execute(
            text(f"DELETE FROM audit_logs WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                "DELETE FROM audit_logs WHERE actor_user_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM cash_journal WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(f"DELETE FROM payments WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM queue_ticket_services WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM queue_tickets WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM customer_profiles WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM services WHERE salon_id IN ({salons_of_prefix})"), params
        )
        conn.execute(
            text(f"DELETE FROM salon_members WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE user_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            params,
        )
        conn.execute(
            text(
                "DELETE FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            params,
        )
        conn.execute(
            text("DELETE FROM users WHERE phone LIKE :prefix"),
            params,
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


# ─── Helpers — bypass SQL (tickets walk-in, prestations, caisse) ─────────────


def _insert_customer_profile(*, salon_id: str, full_name: str) -> str:
    """Insère une fiche client walk-in directement en base."""
    profile_id = str(uuid.uuid4())
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO customer_profiles (id, salon_id, full_name) "
                "VALUES (:id, :salon_id, :full_name)"
            ),
            {"id": profile_id, "salon_id": salon_id, "full_name": full_name},
        )
        conn.commit()
    return profile_id


def _seed_ticket(
    salon_id: str,
    *,
    issued_date: datetime.date,
    ticket_number: int,
    status: str,
    customer_profile_id: str | None = None,
    hairdresser_id: str | None = None,
    estimated_wait_minutes: int = 15,
    created_at: datetime.datetime | None = None,
    started_at: datetime.datetime | None = None,
    completed_at: datetime.datetime | None = None,
    service_id: str | None = None,
) -> str:
    """Insère directement en base un ticket walk-in (statut/jour/horodatages contrôlés).

    Bypass des gardes de la borne HTTP (`POST /queue`, verrou consultatif
    ADR-0040) — seul le SQL des lectures dashboard est exercé ici, pas le
    parcours complet de prise de ticket (déjà couvert par #157). `created_at`/
    `started_at`/`completed_at` ne sont écrits que si explicitement fournis
    (sinon défaut serveur / `NULL`), pour contrôler l'attente réelle
    (`count_waiting_beyond_estimate`) et l'ordre `list_in_progress_details`.
    """
    ticket_id = str(uuid.uuid4())
    columns = [
        "id",
        "salon_id",
        "customer_profile_id",
        "hairdresser_id",
        "issued_date",
        "ticket_number",
        "status",
        "estimated_wait_minutes",
    ]
    values = [
        ":id",
        ":salon_id",
        ":customer",
        ":hairdresser",
        ":date",
        ":number",
        ":status",
        ":wait",
    ]
    params: dict[str, object] = {
        "id": ticket_id,
        "salon_id": salon_id,
        "customer": customer_profile_id,
        "hairdresser": hairdresser_id,
        "date": issued_date,
        "number": ticket_number,
        "status": status,
        "wait": estimated_wait_minutes,
    }
    for column, value in (
        ("created_at", created_at),
        ("started_at", started_at),
        ("completed_at", completed_at),
    ):
        if value is not None:
            columns.append(column)
            values.append(f":{column}")
            params[column] = value

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                f"INSERT INTO queue_tickets ({', '.join(columns)}) "
                f"VALUES ({', '.join(values)})"
            ),
            params,
        )
        if service_id is not None:
            conn.execute(
                text(
                    "INSERT INTO queue_ticket_services "
                    "(queue_ticket_id, service_id, salon_id) "
                    "VALUES (:ticket, :service, :salon)"
                ),
                {"ticket": ticket_id, "service": service_id, "salon": salon_id},
            )
        conn.commit()
    return ticket_id


def _attach_ticket_service(salon_id: str, queue_ticket_id: str, service_id: str) -> None:
    """Ajoute une **deuxième** prestation à un ticket déjà créé (liste en-cours, #148)."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO queue_ticket_services (queue_ticket_id, service_id, salon_id) "
                "VALUES (:ticket, :service, :salon)"
            ),
            {"ticket": queue_ticket_id, "service": service_id, "salon": salon_id},
        )
        conn.commit()


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
    ailleurs) : seule la **lecture agrégée** (`net_revenue_between`/
    `net_revenue_series`) est exercée ici. `transaction_id` reste `NULL`
    (nullable, aucune jointure requise par la lecture testée).
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


def _record_payment(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    amount: str,
    queue_ticket_id: str,
    client_id: str | None = None,
) -> str:
    """Enregistre un paiement `VALIDATED` **via l'API réelle**, lié à un ticket.

    C'est ce qui alimente la timeline d'activité (`ListRecentActivity`, patron
    #36/#43) et couvre l'écart de caisse (`payment_anomaly`). `client_id` est
    **optionnel** (résolution du nom d'affichage, `payments.client_id →
    users.full_name`) — un ticket anonyme ne porte aucun `client_name`.
    """
    body: dict[str, object] = {
        "amount": amount,
        "payment_method": "CASH",
        "queue_ticket_id": queue_ticket_id,
    }
    if client_id is not None:
        body["client_id"] = client_id
    resp = client.post(
        f"/salons/{salon_id}/payments", json=body, headers=_auth(manager_token)
    )
    assert resp.status_code == 201, f"Enregistrement paiement échoué : {resp.text}"
    return resp.json()["id"]


def _day_noon(day: datetime.date) -> datetime.datetime:
    """Midi (fuseau salon) du jour civil donné — bucket sans ambiguïté de bord."""
    return datetime.datetime.combine(day, datetime.time(12, 0), tzinfo=SALON_TIMEZONE)


def _now_salon() -> datetime.datetime:
    """Instant présent **aware** dans le fuseau salon (`Africa/Abidjan` = UTC+0, #148)."""
    return datetime.datetime.now(SALON_TIMEZONE)


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


# ─── Groupe 1 : KPI — agrégats réels + évolution + statut ticket réel ────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardKpisE2E:
    """`GET /salons/{id}/dashboard/kpis` bout-en-bout : `GROUP BY`/évolution SQL réels."""

    def test_waiting_and_clients_kpis_reflect_real_aggregates_with_evolution(
        self, _e2e_client: TestClient
    ) -> None:
        """`waiting_clients`/`clients_count` dérivent de `GROUP BY status`/`COUNT(DISTINCT)` réels.

        Aujourd'hui : 2 tickets `waiting`, 1 ticket `done` (fiche A) → en attente
        = 2, clientes = 1. Hier (période précédente, longueur 1 jour) : 1 ticket
        `waiting`, 1 ticket `done` (fiche B) → en attente = 1, clientes = 1.
        Évolution « en attente » = up (2 > 1).
        """
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        client_a = _insert_customer_profile(salon_id=salon_id, full_name="Cliente A")
        client_b = _insert_customer_profile(salon_id=salon_id, full_name="Cliente B")

        today = _now_salon().date()
        yesterday = today - datetime.timedelta(days=1)

        # Aujourd'hui.
        _seed_ticket(
            salon_id, issued_date=today, ticket_number=1, status="waiting",
            customer_profile_id=client_a,
        )
        _seed_ticket(
            salon_id, issued_date=today, ticket_number=2, status="waiting",
            customer_profile_id=client_a,
        )
        _seed_ticket(
            salon_id, issued_date=today, ticket_number=3, status="done",
            customer_profile_id=client_a,
        )
        # Hier (période précédente).
        _seed_ticket(
            salon_id, issued_date=yesterday, ticket_number=1, status="waiting",
            customer_profile_id=client_b,
        )
        _seed_ticket(
            salon_id, issued_date=yesterday, ticket_number=2, status="done",
            customer_profile_id=client_b,
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
        """`revenue` dérive du **net `cash_journal`** réel (pas d'un comptage de tickets)."""
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

    def test_in_progress_kpi_derived_from_real_ticket_status(
        self, _e2e_client: TestClient
    ) -> None:
        """`in_progress` compte les tickets `in_progress` — décompte direct, aucune arithmétique de créneau."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        today = _now_salon().date()

        # En cours : statut stocké, décompté directement.
        _seed_ticket(salon_id, issued_date=today, ticket_number=1, status="in_progress")
        # `waiting`/`done` : jamais « en cours », quel que soit l'horodatage.
        _seed_ticket(salon_id, issued_date=today, ticket_number=2, status="waiting")
        _seed_ticket(salon_id, issued_date=today, ticket_number=3, status="done")

        kpis = _dashboard_kpis(_e2e_client, manager_token, salon_id)
        assert kpis["in_progress"]["current"] == 1

    def test_other_salon_data_excluded_from_kpis(self, _e2e_client: TestClient) -> None:
        """Isolation §11.2 : les tickets du salon B n'entrent jamais dans les KPI du salon A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        today = _now_salon().date()
        _seed_ticket(salon_b_id, issued_date=today, ticket_number=1, status="waiting")
        _seed_cash_journal(
            salon_b_id, manager_b_id, amount="50000.00", created_at=_day_noon(today)
        )

        kpis = _dashboard_kpis(_e2e_client, token_a, salon_a_id)
        assert kpis["waiting_clients"]["current"] == 0
        assert decimal.Decimal(kpis["revenue"]["current"]) == decimal.Decimal("0.00")

    def test_kpis_response_has_no_pii(self, _e2e_client: TestClient) -> None:
        """§11.3 : compteurs-only, aucun `customer_profile_id`/téléphone/jeton dans la réponse."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        today = _now_salon().date()
        client_a = _insert_customer_profile(
            salon_id=salon_id, full_name="Cliente Confidentielle"
        )
        _seed_ticket(
            salon_id, issued_date=today, ticket_number=1, status="waiting",
            customer_profile_id=client_a,
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


# ─── Groupe 2 : tickets en cours — jointures de noms réelles ─────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardInProgressE2E:
    """`GET /salons/{id}/dashboard/in-progress` : jointures `customer_profiles`/`users`/`services` réelles."""

    def test_in_progress_list_resolves_names_via_real_joins(
        self, _e2e_client: TestClient
    ) -> None:
        """Cliente, coiffeuse et prestations résolues par jointure SQL réelle (#43/#36)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        client_a = _insert_customer_profile(salon_id=salon_id, full_name="Awa Koné")
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

        now = _now_salon().replace(tzinfo=None)
        today = now.date()
        ticket_id = _seed_ticket(
            salon_id, issued_date=today, ticket_number=1, status="in_progress",
            customer_profile_id=client_a, hairdresser_id=hairdresser_id,
            started_at=now, service_id=service_1,
        )
        _attach_ticket_service(salon_id, ticket_id, service_2)

        # Statut `waiting` — ne doit jamais apparaître dans « en cours ».
        _seed_ticket(salon_id, issued_date=today, ticket_number=2, status="waiting")

        result = _dashboard_in_progress(_e2e_client, manager_token, salon_id)

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["queue_ticket_id"] == ticket_id
        assert item["client_name"] == "Awa Koné"
        assert item["hairdresser_name"] == "Fatou D."
        assert set(item["service_names"]) == {"Coupe femme", "Coloration"}
        assert item["status"] == "in_progress"

        # Émission maîtrisée (§11.3) : le nom d'affichage est présent, jamais un
        # identifiant ou un contact.
        raw = _e2e_client.get(
            f"/salons/{salon_id}/dashboard/in-progress", headers=_auth(manager_token)
        ).text
        assert client_a not in raw
        assert hairdresser_id not in raw
        assert _PHONE_HAIRDRESSER_LOCAL not in raw

    def test_in_progress_empty_when_no_ticket_in_progress(
        self, _e2e_client: TestClient
    ) -> None:
        """Aucun ticket `in_progress` → liste vide (état légitime, pas une erreur)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        today = _now_salon().date()
        _seed_ticket(salon_id, issued_date=today, ticket_number=1, status="waiting")

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

    def test_attendance_series_buckets_reflect_real_ticket_counts_with_zero_fill(
        self, _e2e_client: TestClient
    ) -> None:
        """Bucket = nombre de tickets (tous statuts) par jour ; jour sans ticket = `0`."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        today = _now_salon().date()
        two_days_ago = today - datetime.timedelta(days=2)

        _seed_ticket(salon_id, issued_date=two_days_ago, ticket_number=1, status="expired")
        _seed_ticket(salon_id, issued_date=today, ticket_number=1, status="waiting")
        _seed_ticket(salon_id, issued_date=today, ticket_number=2, status="waiting")

        series = _dashboard_attendance_series(
            _e2e_client, manager_token, salon_id,
            period="custom", date_from=two_days_ago.isoformat(), date_to=today.isoformat(),
        )

        by_day = {b["bucket_start"]: b["count"] for b in series["buckets"]}
        assert by_day[two_days_ago.isoformat()] == 1
        assert by_day[(today - datetime.timedelta(days=1)).isoformat()] == 0
        assert by_day[today.isoformat()] == 2


# ─── Groupe 4 : timeline d'activité — paiements réels uniquement (#148) ──────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardActivityE2E:
    """`GET /salons/{id}/dashboard/activity` : paiements réels, triés — plus de notifications."""

    def test_activity_reflects_real_payments_sorted_by_recency(
        self, _e2e_client: TestClient
    ) -> None:
        """Flux borné aux **paiements**, trié décroissant — aucune notification, faits réels seuls.

        Les notifications ont disparu avec le pivot walk-in exclusif (#148) : la
        timeline n'a plus rien à fusionner ni à dédupliquer, elle **liste
        directement** les paiements horodatés (patron #36) triés par
        `occurred_at` décroissant.
        """
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_a = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_A_LOCAL, full_name="Cliente Activité"
        )
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        service_5000 = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="5000.00"
        )
        service_8000 = _create_service(
            _e2e_client, manager_token, salon_id, name="Coloration", price="8000.00"
        )
        today = _now_salon().date()

        ticket_1 = _seed_ticket(
            salon_id, issued_date=today, ticket_number=1, status="done",
            service_id=service_5000,
        )
        _record_payment(
            _e2e_client, manager_token, salon_id,
            amount="5000.00", queue_ticket_id=ticket_1, client_id=client_a,
        )
        ticket_2 = _seed_ticket(
            salon_id, issued_date=today, ticket_number=2, status="done",
            service_id=service_8000,
        )
        _record_payment(
            _e2e_client, manager_token, salon_id,
            amount="8000.00", queue_ticket_id=ticket_2, client_id=client_a,
        )

        feed = _dashboard_activity(_e2e_client, manager_token, salon_id, limit=20)
        items = feed["items"]

        assert len(items) == 2
        assert {item["kind"] for item in items} == {"payment"}

        occurred_at = [
            datetime.datetime.fromisoformat(item["occurred_at"]) for item in items
        ]
        assert occurred_at == sorted(occurred_at, reverse=True)
        # Le paiement le plus récent (8000.00, enregistré en second) vient en tête.
        assert decimal.Decimal(items[0]["amount"]) == decimal.Decimal("8000.00")
        assert decimal.Decimal(items[1]["amount"]) == decimal.Decimal("5000.00")
        for item in items:
            assert item["client_name"] == "Cliente Activité"
            assert item["currency"] == "XOF"
            assert item["label"] == "Paiement enregistré"

    def test_activity_respects_limit_top_n(self, _e2e_client: TestClient) -> None:
        """`limit` borne le flux (garde de coût §12.1, top-N)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="1000.00"
        )
        today = _now_salon().date()

        for ticket_number in range(1, 6):
            ticket_id = _seed_ticket(
                salon_id, issued_date=today, ticket_number=ticket_number, status="done",
                service_id=service_id,
            )
            _record_payment(
                _e2e_client, manager_token, salon_id,
                amount="1000.00", queue_ticket_id=ticket_id,
            )

        feed = _dashboard_activity(_e2e_client, manager_token, salon_id, limit=2)
        assert len(feed["items"]) == 2

    def test_activity_isolated_per_salon(self, _e2e_client: TestClient) -> None:
        """Isolation §11.2 : un paiement du salon B n'apparaît jamais dans le flux A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b = _create_service(
            _e2e_client, token_b, salon_b_id, name="Coupe B", price="9000.00"
        )
        today = _now_salon().date()

        ticket_b = _seed_ticket(
            salon_b_id, issued_date=today, ticket_number=1, status="done",
            service_id=service_b,
        )
        _record_payment(
            _e2e_client, token_b, salon_b_id,
            amount="9000.00", queue_ticket_id=ticket_b,
        )

        feed_a = _dashboard_activity(_e2e_client, token_a, salon_a_id)
        assert feed_a["items"] == []


# ─── Groupe 5 : alertes — dérivées de faits réels (#148) ─────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDashboardAlertsE2E:
    """`GET /salons/{id}/dashboard/alerts` : `prolonged_wait`/`payment_anomaly` réels.

    L'ancienne alerte `late` (RDV `CONFIRMED` dont le créneau était dépassé sans
    clôture) n'a **pas d'équivalent walk-in** — un ticket n'a pas de créneau
    horaire — et a disparu avec le pivot (#148). Seules deux alertes subsistent.
    """

    def test_alerts_derived_from_real_prolonged_wait_and_payment_anomaly(
        self, _e2e_client: TestClient
    ) -> None:
        """Les deux alertes restantes dérivent de tickets réellement persistés."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        now = _now_salon()
        today = now.date()

        # `prolonged_wait` : `waiting` dont l'attente réelle (30 min) dépasse
        # l'estimation figée (5 min).
        _seed_ticket(
            salon_id, issued_date=today, ticket_number=1, status="waiting",
            estimated_wait_minutes=5, created_at=now - datetime.timedelta(minutes=30),
        )
        # `waiting` dont l'attente réelle **n'excède pas** l'estimation : ne
        # doit jamais peser dans l'alerte (contrôle négatif).
        _seed_ticket(
            salon_id, issued_date=today, ticket_number=2, status="waiting",
            estimated_wait_minutes=60, created_at=now,
        )
        # `payment_anomaly` : `done` sans aucun paiement rattaché (#36).
        _seed_ticket(
            salon_id, issued_date=today, ticket_number=3, status="done",
            completed_at=now,
        )

        alerts = _dashboard_alerts(_e2e_client, manager_token, salon_id)
        by_kind = {item["kind"]: item for item in alerts["items"]}

        assert by_kind["prolonged_wait"]["count"] == 1
        assert by_kind["prolonged_wait"]["severity"] == "info"
        assert by_kind["payment_anomaly"]["count"] == 1
        assert by_kind["payment_anomaly"]["severity"] == "warning"
        assert "late" not in by_kind

        # Ordre d'affichage stable (autorité serveur) : anomalie de paiement
        # avant attente prolongée.
        kinds_order = [item["kind"] for item in alerts["items"]]
        assert kinds_order.index("payment_anomaly") < kinds_order.index("prolonged_wait")

    def test_alerts_empty_when_no_alerts(self, _e2e_client: TestClient) -> None:
        """Salon sans ticket en attente prolongée ni écart de caisse → liste vide."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        alerts = _dashboard_alerts(_e2e_client, manager_token, salon_id)
        assert alerts["items"] == []

    def test_alerts_isolated_per_salon(self, _e2e_client: TestClient) -> None:
        """Isolation §11.2 : un écart de caisse du salon B n'entre jamais dans les alertes A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        today = _now_salon().date()
        _seed_ticket(
            salon_b_id, issued_date=today, ticket_number=1, status="done",
            completed_at=_now_salon(),
        )

        alerts_a = _dashboard_alerts(_e2e_client, token_a, salon_a_id)
        assert alerts_a["items"] == []
