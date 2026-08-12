"""Tests e2e pour US-6.5 — performance des coiffeurs, dashboard gérant (#43).

Groupe `TestHairdresserPerformanceE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlAppointmentRepository.
    performance_by_hairdresser` (deux agrégats `GROUP BY hairdresser_id` :
    compteurs planning + occurrences de prestations) et de
    `SqlCashJournalEntryRepository.net_revenue_by_hairdresser` (somme signée du
    journal de caisse jointe `payments → appointments.hairdresser_id`), puis leur
    **fusion** par `SummarizeHairdresserPerformance`. Aucune suite unitaire/API
    (adossée à des fakes en mémoire) ne couvre ce SQL : c'est le seul code qui
    satisfait réellement le critère d'acceptation #43 *« indicateurs par
    coiffeur cohérents avec le planning et la caisse »*.

Scénarios (spec `specs/performance-des-coiffeurs.md`, miroir
`test_service_demand_e2e.py` #41) :
    - deux coiffeurs, RDV variés (réalisés, annulés, en attente) → prestations
      réalisées et taux d'annulation reflètent exactement le `GROUP BY` réel
      (pas seulement un fake), classement trié par CA décroissant ;
    - le CA attribué dérive du **journal de caisse** (paiements réels via
      l'API), pas d'un comptage de RDV — un coiffeur avec des RDV réalisés mais
      **aucun paiement enregistré** a un CA à `0.00` ;
    - bornes de période : `date_from`/`date_to` réaffirmées en SQL
      (`appointment_date`, planning **et** caisse partagent la même fenêtre) ;
    - défaut de période : sans bornes, la performance porte sur le **mois
      civil courant** (`month_bounds`, symétrie #42) ;
    - isolation §11.2 : un coiffeur/RDV d'un autre salon n'entre jamais dans le
      classement (filtre `salon_id` réaffirmé en SQL, planning et caisse) ;
    - un coiffeur sans RDV assigné sur la période n'apparaît pas (liste dérivée
      du planning, spec §Open Questions 10) ;
    - salon sans coiffeur assigné → liste vide (état normal, pas une erreur) ;
    - `401` sans jeton, `403` inter-salons ;
    - §11.3 : la réponse porte l'identité **d'affichage** du coiffeur
      (`hairdresser_id` + nom) mais **aucune** PII client (`client_id`,
      `appointment_id`) ni contact employé (téléphone, e-mail).

Les RDV sont insérés **directement en base** (bypass des gardes HTTP de
réservation — créneaux/heures d'ouverture, hors périmètre #43) pour contrôler
statut, date et coiffeur assigné sans dépendre du parcours de réservation
complet. Les **paiements**, eux, passent par l'API réelle (`POST /payments`) :
c'est ce qui peuple le journal de caisse et donc le CA attribué (miroir
`seed_dev_data.py`).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_hairdresser_performance_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225079999xxxx).
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
from coiflink_api.domain.revenue import month_bounds
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-hairdresser-performance-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e de la performance des coiffeurs.
_E2E_PHONE_PREFIX = "+225079999"
_PHONE_MANAGER_A_LOCAL = "0799990001"   # gérant A — parcours principal
_PHONE_MANAGER_B_LOCAL = "0799990002"   # gérant B — isolation inter-salons
_PHONE_CLIENT_LOCAL = "0799990003"
_PHONE_HAIRDRESSER_1_LOCAL = "0799990004"
_PHONE_HAIRDRESSER_2_LOCAL = "0799990005"
_PASSWORD = "hairdresser-performance-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-hairdresser-performance-a"
_SALON_NAME_B = "e2e-salon-hairdresser-performance-b"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → cash_journal → payments → appointment_services →
    appointments → services → salon_members → salons → users.
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
                "DELETE FROM cash_journal WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text(
                "DELETE FROM payments WHERE salon_id IN "
                "(SELECT id FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix))"
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
    - Supprime les données de test (plage +225079999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e de la performance des coiffeurs.")

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


def _register_manager(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte gérant via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Performance", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client_account(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte client via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E Performance", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str) -> str:
    """Crée un salon via l'API et retourne son UUID."""
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(
    client: TestClient, token: str, salon_id: str, *, name: str, price: str
) -> str:
    """Crée une prestation active via l'API et retourne son UUID."""
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": name, "price": price, "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _add_hairdresser(
    client: TestClient, manager_token: str, salon_id: str, *, full_name: str, phone: str
) -> str:
    """Inscrit un coiffeur, l'enregistre comme membre du salon, retourne son UUID."""
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


def _seed_appointment(
    salon_id: str,
    client_id: str,
    hairdresser_id: str,
    *,
    day: datetime.date,
    start_time: str,
    status: str,
    service_id: str | None = None,
    price_at_booking: str | None = None,
) -> str:
    """Insère directement en base un RDV (statut/jour/coiffeur contrôlés).

    Bypass des gardes de réservation HTTP (créneaux/heures d'ouverture) — seul
    l'agrégat `GROUP BY hairdresser_id` du dépôt est testé ici, pas le parcours
    complet de réservation (déjà couvert par `test_appointment_concurrency.py`,
    #21). Si `service_id` est fourni, une ligne `appointment_services` est
    ajoutée (nécessaire pour `services_completed` et pour qu'un paiement lié au
    RDV soit acceptable par `RecordPayment`).
    """
    end_time = (
        datetime.datetime.combine(day, datetime.time.fromisoformat(start_time))
        + datetime.timedelta(minutes=30)
    ).time()
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
                "start_time": start_time,
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


def _record_payment_for_appointment(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    amount: str,
    appointment_id: str,
    client_id: str,
) -> str:
    """Enregistre un paiement `VALIDATED` lié à un RDV et retourne son UUID.

    C'est ce qui peuple le `cash_journal` (ligne `PAYMENT`) que
    `net_revenue_by_hairdresser` agrège — le CA attribué dérive de la caisse,
    jamais d'un comptage de RDV.
    """
    resp = client.post(
        f"/salons/{salon_id}/payments",
        json={
            "amount": amount,
            "payment_method": "CASH",
            "appointment_id": appointment_id,
            "client_id": client_id,
        },
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Enregistrement paiement échoué : {resp.text}"
    return resp.json()["id"]


def _hairdresser_performance(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    """`GET /salons/{id}/hairdresser-performance` (US-6.5, #43)."""
    resp = client.get(
        f"/salons/{salon_id}/hairdresser-performance",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Performance des coiffeurs échouée : {resp.text}"
    return resp.json()


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestHairdresserPerformanceE2E:
    """`GET /salons/{id}/hairdresser-performance` bout-en-bout : GROUP BY SQL réel."""

    # ── Parcours 1 : agrégat réel (planning + caisse fusionnés) ────────────────

    def test_metrics_reflect_real_planning_and_cash_journal(
        self, _e2e_client: TestClient
    ) -> None:
        """Deux coiffeurs, RDV variés → prestations/annulations (planning réel) + CA (caisse réelle).

        Coiffeur 1 : 2 RDV `COMPLETED` (payés), 1 `CANCELLED`, 1 `PENDING` — total
        assigné = 4, annulés = 1, prestations réalisées = 2, CA = somme des deux
        paiements. Coiffeur 2 : 1 RDV `COMPLETED` (payé) de montant supérieur — doit
        apparaître **avant** le coiffeur 1 (tri CA décroissant).
        """
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_1 = _add_hairdresser(
            _e2e_client,
            manager_token,
            salon_id,
            full_name="Coiffeur Un",
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
        )
        hairdresser_2 = _add_hairdresser(
            _e2e_client,
            manager_token,
            salon_id,
            full_name="Coiffeur Deux",
            phone=_PHONE_HAIRDRESSER_2_LOCAL,
        )
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="10000.00"
        )
        today = datetime.date.today()
        period_from = today.replace(day=1)

        appt1 = _seed_appointment(
            salon_id, client_id, hairdresser_1, day=today, start_time="09:00",
            status="COMPLETED", service_id=service_id, price_at_booking="10000.00",
        )
        appt2 = _seed_appointment(
            salon_id, client_id, hairdresser_1, day=today, start_time="10:00",
            status="COMPLETED", service_id=service_id, price_at_booking="10000.00",
        )
        _seed_appointment(
            salon_id, client_id, hairdresser_1, day=today, start_time="11:00",
            status="CANCELLED",
        )
        _seed_appointment(
            salon_id, client_id, hairdresser_1, day=today, start_time="12:00",
            status="PENDING",
        )
        appt3 = _seed_appointment(
            salon_id, client_id, hairdresser_2, day=today, start_time="09:00",
            status="COMPLETED", service_id=service_id, price_at_booking="10000.00",
        )

        _record_payment_for_appointment(
            _e2e_client, manager_token, salon_id,
            amount="10000.00", appointment_id=appt1, client_id=client_id,
        )
        _record_payment_for_appointment(
            _e2e_client, manager_token, salon_id,
            amount="10000.00", appointment_id=appt2, client_id=client_id,
        )
        _record_payment_for_appointment(
            _e2e_client, manager_token, salon_id,
            amount="10000.00", appointment_id=appt3, client_id=client_id,
        )

        report = _hairdresser_performance(
            _e2e_client,
            manager_token,
            salon_id,
            date_from=period_from.isoformat(),
            date_to=today.isoformat(),
        )

        by_id = {row["hairdresser_id"]: row for row in report["hairdressers"]}

        row1 = by_id[hairdresser_1]
        assert row1["services_completed"] == 2
        assert row1["cancelled_count"] == 1
        assert row1["total_count"] == 4
        assert decimal.Decimal(row1["revenue"]) == decimal.Decimal("20000.00")
        assert decimal.Decimal(row1["cancellation_rate"]) == decimal.Decimal("0.2500")

        row2 = by_id[hairdresser_2]
        assert row2["services_completed"] == 1
        assert row2["cancelled_count"] == 0
        assert row2["total_count"] == 1
        assert decimal.Decimal(row2["revenue"]) == decimal.Decimal("10000.00")
        assert decimal.Decimal(row2["cancellation_rate"]) == decimal.Decimal("0.0000")

        # Coiffeur 1 (CA 20000) doit passer avant coiffeur 2 (CA 10000).
        ordered_ids = [row["hairdresser_id"] for row in report["hairdressers"]]
        assert ordered_ids.index(hairdresser_1) < ordered_ids.index(hairdresser_2)

    def test_completed_without_payment_has_zero_revenue(
        self, _e2e_client: TestClient
    ) -> None:
        """Un coiffeur avec des RDV réalisés mais aucun paiement enregistré a un CA à 0.00.

        Le CA dérive de la **caisse**, pas d'un comptage de RDV : les prestations
        réalisées et le CA sont deux sources indépendantes.
        """
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client,
            manager_token,
            salon_id,
            full_name="Coiffeur Sans Paiement",
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
        )
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="10000.00"
        )
        today = datetime.date.today()
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="09:00",
            status="COMPLETED", service_id=service_id, price_at_booking="10000.00",
        )

        report = _hairdresser_performance(
            _e2e_client,
            manager_token,
            salon_id,
            date_from=today.replace(day=1).isoformat(),
            date_to=today.isoformat(),
        )

        row = next(r for r in report["hairdressers"] if r["hairdresser_id"] == hairdresser_id)
        assert row["services_completed"] == 1
        assert decimal.Decimal(row["revenue"]) == decimal.Decimal("0.00")

    # ── Parcours 2 : bornes de période ─────────────────────────────────────────

    def test_date_bounds_filter_planning_and_cash(self, _e2e_client: TestClient) -> None:
        """`date_from`/`date_to` réaffirmées en SQL, planning et caisse partagent la fenêtre."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client,
            manager_token,
            salon_id,
            full_name="Coiffeur Bornes",
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
        )
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe", price="10000.00"
        )
        today = datetime.date.today()
        old_day = today - datetime.timedelta(days=30)

        appt_old = _seed_appointment(
            salon_id, client_id, hairdresser_id, day=old_day, start_time="09:00",
            status="COMPLETED", service_id=service_id, price_at_booking="10000.00",
        )
        _record_payment_for_appointment(
            _e2e_client, manager_token, salon_id,
            amount="10000.00", appointment_id=appt_old, client_id=client_id,
        )

        # Fenêtre bornée sur aujourd'hui uniquement → le RDV ancien est exclu.
        report = _hairdresser_performance(
            _e2e_client,
            manager_token,
            salon_id,
            date_from=today.isoformat(),
            date_to=today.isoformat(),
        )
        assert report["hairdressers"] == []

        # Fenêtre couvrant l'ancien RDV → le coiffeur apparaît avec son CA.
        report_wide = _hairdresser_performance(
            _e2e_client,
            manager_token,
            salon_id,
            date_from=old_day.isoformat(),
            date_to=old_day.isoformat(),
        )
        assert len(report_wide["hairdressers"]) == 1
        assert report_wide["hairdressers"][0]["hairdresser_id"] == hairdresser_id
        assert decimal.Decimal(report_wide["hairdressers"][0]["revenue"]) == decimal.Decimal(
            "10000.00"
        )

    # ── Parcours 3 : défaut de période (mois civil courant) ────────────────────

    def test_missing_bounds_default_to_current_month(self, _e2e_client: TestClient) -> None:
        """Sans `date_from`/`date_to`, la performance porte sur le mois civil courant."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client,
            manager_token,
            salon_id,
            full_name="Coiffeur Défaut",
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
        )
        today = datetime.date.today()
        month_from, month_to = month_bounds(today)
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="09:00",
            status="COMPLETED",
        )

        report = _hairdresser_performance(_e2e_client, manager_token, salon_id)

        assert report["date_from"] == month_from.isoformat()
        assert report["date_to"] == month_to.isoformat()
        assert any(r["hairdresser_id"] == hairdresser_id for r in report["hairdressers"])

    # ── Parcours 4 : isolation §11.2 ───────────────────────────────────────────

    def test_other_salon_hairdresser_not_counted(self, _e2e_client: TestClient) -> None:
        """Un coiffeur/RDV du salon B n'entre jamais dans le classement du salon A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        hairdresser_b = _add_hairdresser(
            _e2e_client,
            token_b,
            salon_b_id,
            full_name="Coiffeur Salon B",
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
        )
        service_b = _create_service(
            _e2e_client, token_b, salon_b_id, name="Coupe B", price="10000.00"
        )
        today = datetime.date.today()
        appt_b = _seed_appointment(
            salon_b_id, client_id, hairdresser_b, day=today, start_time="09:00",
            status="COMPLETED", service_id=service_b, price_at_booking="10000.00",
        )
        _record_payment_for_appointment(
            _e2e_client, token_b, salon_b_id,
            amount="10000.00", appointment_id=appt_b, client_id=client_id,
        )

        report_a = _hairdresser_performance(
            _e2e_client,
            token_a,
            salon_a_id,
            date_from=today.replace(day=1).isoformat(),
            date_to=today.isoformat(),
        )
        assert report_a["hairdressers"] == []

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Le jeton du gérant A est refusé pour consulter la performance du salon B."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.get(
            f"/salons/{salon_b_id}/hairdresser-performance",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    # ── Parcours 5 : listes vides / dérivées du planning ────────────────────────

    def test_salon_without_assigned_hairdresser_returns_empty_list(
        self, _e2e_client: TestClient
    ) -> None:
        """Un salon sans coiffeur assigné renvoie une liste vide (état normal)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        report = _hairdresser_performance(_e2e_client, manager_token, salon_id)

        assert report["hairdressers"] == []

    # ── Parcours 6 : deny-by-default (ADR-0015) ─────────────────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        assert manager_id

        resp = _e2e_client.get(f"/salons/{salon_id}/hairdresser-performance")
        assert resp.status_code == 401

    # ── Parcours 7 : identité employé maîtrisée, absence de PII client (§11.3) ──

    def test_response_exposes_hairdresser_identity_but_no_client_pii(
        self, _e2e_client: TestClient
    ) -> None:
        """La réponse porte le nom du coiffeur mais aucune PII client ni contact employé."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client,
            manager_token,
            salon_id,
            full_name="Coiffeur Identité",
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
        )
        appointment_id = _seed_appointment(
            salon_id, client_id, hairdresser_id, day=datetime.date.today(),
            start_time="09:00", status="COMPLETED",
        )

        resp = _e2e_client.get(
            f"/salons/{salon_id}/hairdresser-performance",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        # Identité **d'affichage** du coiffeur : présente (c'est l'objet du KPI).
        assert "Coiffeur Identité" in resp.text
        # Aucune PII client ni jeton ni contact employé.
        assert manager_token not in resp.text
        assert client_id not in resp.text
        assert appointment_id not in resp.text
        assert _PHONE_HAIRDRESSER_1_LOCAL not in resp.text
