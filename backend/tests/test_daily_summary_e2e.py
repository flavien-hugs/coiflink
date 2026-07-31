"""Tests e2e pour US-6.1 — RDV du jour, dashboard gérant (#39).

Groupe `TestDailyAppointmentsSummaryE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlAppointmentRepository.count_by_status_for_day`
    — la requête `select(status, func.count()).where(salon_id=…, appointment_date=…)
    .group_by(status)`. Aucune suite unitaire/API (adossée à
    `FakeAppointmentRepository`) ne couvre ce SQL : c'est le seul code qui satisfait
    réellement le critère d'acceptation #39 *« décompte du jour par statut »*.

Scénarios (spec `specs/*.md`, cf. finding de revue automatisée sur la PR #121) :
    - plusieurs RDV du jour, statuts variés → `by_status` reflète exactement le
      `GROUP BY` réel (pas seulement le fake) ;
    - un statut sans RDV du jour vaut `0` (jamais absent de `by_status`) ;
    - `total` = somme de tous les compteurs, y compris `PENDING` ;
    - isolation §11.2 : un RDV d'un autre salon n'entre jamais dans le décompte
      (filtre `salon_id` réaffirmé en SQL) ;
    - filtre de date : un RDV d'un autre jour n'est jamais compté (filtre
      `appointment_date` réaffirmé en SQL) ;
    - `date` absent du paramètre → jour civil courant (`Africa/Abidjan`) ;
    - `401` sans jeton, `403` inter-salons ;
    - aucune PII (client, coiffeur, notes) dans la réponse agrégée.

Les RDV sont insérés **directement en base** (bypass des gardes HTTP de réservation
— créneaux/heures d'ouverture, hors périmètre #39) pour contrôler statut et date
sans dépendre du parcours de réservation complet (miroir de `test_receipts_e2e.py`,
#38).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_daily_summary_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225076995xxxx).
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
_TEST_JWT_SECRET = "test-only-daily-summary-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e du décompte du jour.
_E2E_PHONE_PREFIX = "+225076995"
_PHONE_MANAGER_A_LOCAL = "0769950001"   # gérant A — parcours principal
_PHONE_MANAGER_B_LOCAL = "0769950002"   # gérant B — isolation inter-salons
_PHONE_CLIENT_LOCAL = "0769950003"
_PHONE_HAIRDRESSER_LOCAL = "0769950004"
_PASSWORD = "daily-summary-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-daily-summary-a"
_SALON_NAME_B = "e2e-salon-daily-summary-b"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : appointment_services → appointments → audit_logs → salon_members →
    salons → users.
    """
    engine = get_engine()
    with engine.connect() as conn:
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
                "DELETE FROM audit_logs WHERE salon_id IN "
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
    - Supprime les données de test (plage +225076995) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e du décompte du jour.")

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
        json={"full_name": "Gérant E2E Dashboard", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client_account(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte client via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E Dashboard", "phone": phone, "password": _PASSWORD},
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


def _seed_appointment(
    salon_id: str,
    client_id: str,
    hairdresser_id: str,
    *,
    day: datetime.date,
    start_time: str,
    status: str,
) -> str:
    """Insère un RDV directement en base, avec un statut et un jour donnés.

    Bypass des gardes de réservation HTTP (créneaux/heures d'ouverture) — seul le
    décompte `GROUP BY status` du dépôt est testé ici, pas le parcours complet de
    réservation (déjà couvert par `test_appointment_concurrency.py`, #21).
    """
    engine = get_engine()
    with engine.connect() as conn:
        end_time_dt = (
            datetime.datetime.combine(day, datetime.time.fromisoformat(start_time))
            + datetime.timedelta(minutes=30)
        ).time()
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
                "end_time": end_time_dt.isoformat(),
                "status": status,
            },
        )
        appointment_id = row.scalar_one()
        conn.commit()
    return str(appointment_id)


def _add_hairdresser(
    client: TestClient, manager_token: str, salon_id: str, *, phone: str
) -> str:
    """Inscrit un coiffeur, l'enregistre comme membre du salon, retourne son UUID."""
    resp_register = client.post(
        "/auth/register",
        json={"full_name": "Coiffeur E2E Dashboard", "phone": phone, "password": _PASSWORD},
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


def _daily_summary(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    """`GET /salons/{id}/appointments/daily-summary` (US-6.1, #39)."""
    resp = client.get(
        f"/salons/{salon_id}/appointments/daily-summary",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Décompte du jour échoué : {resp.text}"
    return resp.json()


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestDailyAppointmentsSummaryE2E:
    """`GET /salons/{id}/appointments/daily-summary` bout-en-bout : GROUP BY SQL réel."""

    # ── Parcours 1 : décompte réel par statut (GROUP BY) ──────────────────────

    def test_counts_reflect_real_group_by(self, _e2e_client: TestClient) -> None:
        """Plusieurs RDV du jour, statuts variés → `by_status` reflète le GROUP BY réel."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769950099"
        )
        today = datetime.date.today()
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="09:00", status="CONFIRMED"
        )
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="10:00", status="CONFIRMED"
        )
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="11:00", status="COMPLETED"
        )
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="12:00", status="CANCELLED"
        )

        summary = _daily_summary(_e2e_client, manager_token, salon_id)
        assert summary["by_status"]["CONFIRMED"] == 2
        assert summary["by_status"]["COMPLETED"] == 1
        assert summary["by_status"]["CANCELLED"] == 1

    def test_status_without_appointments_is_zero(self, _e2e_client: TestClient) -> None:
        """Un statut sans RDV du jour vaut `0`, jamais absent de `by_status`."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769950098"
        )
        today = datetime.date.today()
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="09:00", status="CONFIRMED"
        )

        summary = _daily_summary(_e2e_client, manager_token, salon_id)
        for status in ("PENDING", "CANCELLED", "COMPLETED", "NO_SHOW"):
            assert summary["by_status"][status] == 0

    def test_total_sums_all_statuses_including_pending(
        self, _e2e_client: TestClient
    ) -> None:
        """`total` = somme de tous les compteurs, y compris `PENDING`."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769950097"
        )
        today = datetime.date.today()
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="09:00", status="PENDING"
        )
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="10:00", status="CONFIRMED"
        )

        summary = _daily_summary(_e2e_client, manager_token, salon_id)
        assert summary["total"] == 2

    # ── Parcours 2 : isolation §11.2 (salon et jour) ──────────────────────────

    def test_other_salon_appointments_not_counted(self, _e2e_client: TestClient) -> None:
        """Un RDV du salon B n'entre jamais dans le décompte du salon A (filtre SQL)."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        hairdresser_b_id = _add_hairdresser(
            _e2e_client, token_b, salon_b_id, phone="0769950096"
        )
        today = datetime.date.today()
        _seed_appointment(
            salon_b_id, client_id, hairdresser_b_id, day=today, start_time="09:00", status="CONFIRMED"
        )

        summary = _daily_summary(_e2e_client, token_a, salon_a_id)
        assert summary["total"] == 0

    def test_other_day_appointments_not_counted(self, _e2e_client: TestClient) -> None:
        """Un RDV d'un autre jour n'entre jamais dans le décompte (filtre `appointment_date`)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769950095"
        )
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        _seed_appointment(
            salon_id,
            client_id,
            hairdresser_id,
            day=yesterday,
            start_time="09:00",
            status="COMPLETED",
        )

        summary = _daily_summary(_e2e_client, manager_token, salon_id)
        assert summary["total"] == 0

    def test_explicit_date_param_targets_that_day(self, _e2e_client: TestClient) -> None:
        """Le paramètre `date` cible explicitement un jour ≠ aujourd'hui."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769950094"
        )
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        _seed_appointment(
            salon_id,
            client_id,
            hairdresser_id,
            day=yesterday,
            start_time="09:00",
            status="COMPLETED",
        )

        summary = _daily_summary(
            _e2e_client, manager_token, salon_id, date=yesterday.isoformat()
        )
        assert summary["total"] == 1
        assert summary["by_status"]["COMPLETED"] == 1

    def test_no_date_param_defaults_to_today(self, _e2e_client: TestClient) -> None:
        """Sans paramètre `date`, le décompte porte sur le jour civil courant."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769950093"
        )
        today = datetime.date.today()
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="09:00", status="CONFIRMED"
        )

        summary = _daily_summary(_e2e_client, manager_token, salon_id)
        assert summary["date"] == today.isoformat()
        assert summary["total"] == 1

    # ── Parcours 3 : deny-by-default et RBAC (ADR-0015) ───────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        assert manager_id

        resp = _e2e_client.get(f"/salons/{salon_id}/appointments/daily-summary")
        assert resp.status_code == 401

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Le jeton du gérant A est refusé pour consulter le décompte du salon B."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.get(
            f"/salons/{salon_b_id}/appointments/daily-summary",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    # ── Parcours 4 : absence de PII (§11.3) ───────────────────────────────────

    def test_response_contains_no_pii(self, _e2e_client: TestClient) -> None:
        """La réponse agrégée ne révèle aucune PII (client, coiffeur, jeton)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769950092"
        )
        today = datetime.date.today()
        _seed_appointment(
            salon_id, client_id, hairdresser_id, day=today, start_time="09:00", status="CONFIRMED"
        )

        resp = _e2e_client.get(
            f"/salons/{salon_id}/appointments/daily-summary",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert manager_token not in resp.text
        assert client_id not in resp.text
        assert hairdresser_id not in resp.text
