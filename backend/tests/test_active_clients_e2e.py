"""Tests e2e pour US-6.4 — clients actifs, dashboard gérant (#42).

Groupe `TestActiveClientsE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de
    `SqlAppointmentRepository.segment_active_clients` — la requête
    `select(min(appointment_date), sum(case in-period), sum(case before))
    .where(salon_id=…, status IN (...)).group_by(client_id)`. Aucune suite
    unitaire/API (adossée à un fake en mémoire) ne couvre ce SQL : c'est le
    seul code qui satisfait réellement le critère d'acceptation #42
    *« segmentation des clients sur une période donnée »*.

Scénarios (spec `specs/clients-actifs-segmentation.md`, miroir
`test_service_demand_e2e.py` #41) :
    - trois clients aux profils distincts (nouveau, récurrent, inactif) →
      `segment_active_clients` produit les trois compteurs corrects sur le
      chemin SQL réel (pas seulement un fake) ;
    - filtre de statut : un RDV `PENDING`/`CANCELLED`/`NO_SHOW` ne compte
      **jamais** comme une visite (« annulés exclus », §8.1) ;
    - bornes de période : `date_from`/`date_to` réaffirmées en SQL
      (`appointment_date`) ;
    - défaut de période : sans bornes, la segmentation porte sur le **mois
      civil courant** (`month_bounds`, symétrie #40) ;
    - isolation §11.2 : une visite dans un autre salon n'entre jamais dans
      la segmentation (filtre `salon_id` réaffirmé en SQL) ;
    - salon sans RDV réalisé → les trois compteurs valent `0` (état normal,
      pas une erreur) ;
    - `401` sans jeton, `403` inter-salons ;
    - anti-oracle (§11.1/§11.3) : aucune PII (`client_id`, jeton) dans la
      réponse agrégée — seulement des compteurs et des dates.

Les RDV sont insérés **directement en base** (bypass des gardes HTTP de
réservation — créneaux/heures d'ouverture, hors périmètre #42) pour
contrôler statut et date sans dépendre du parcours de réservation complet
(miroir `test_daily_summary_e2e.py` #39, `test_service_demand_e2e.py` #41).
Aucun coiffeur ni prestation n'est nécessaire : la segmentation ne dépend
que de `appointments.client_id`/`status`/`appointment_date`
(`hairdresser_id` est nullable).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_active_clients_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225078999xxxx).
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
from coiflink_api.domain.revenue import month_bounds
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-active-clients-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des clients actifs.
_E2E_PHONE_PREFIX = "+225078999"
_PHONE_MANAGER_A_LOCAL = "0789990001"   # gérant A — parcours principal
_PHONE_MANAGER_B_LOCAL = "0789990002"   # gérant B — isolation inter-salons
_PHONE_CLIENT_NEW_LOCAL = "0789990003"
_PHONE_CLIENT_RECURRING_LOCAL = "0789990004"
_PHONE_CLIENT_INACTIVE_LOCAL = "0789990005"
_PASSWORD = "active-clients-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-active-clients-a"
_SALON_NAME_B = "e2e-salon-active-clients-b"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → appointments → salon_members → salons → users.
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
                "DELETE FROM appointments WHERE salon_id IN "
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
    - Supprime les données de test (plage +225078999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e des clients actifs.")

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
        json={"full_name": "Gérant E2E Clients Actifs", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client_account(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte client via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E Clients Actifs", "phone": phone, "password": _PASSWORD},
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
    *,
    day: datetime.date,
    status: str = "COMPLETED",
    start_time: str = "10:00",
) -> str:
    """Insère directement en base un RDV (statut/jour contrôlés), sans coiffeur ni prestation.

    Bypass des gardes de réservation HTTP (créneaux/heures d'ouverture) — seul
    l'agrégat `GROUP BY client_id` du dépôt est testé ici, pas le parcours
    complet de réservation (déjà couvert par `test_appointment_concurrency.py`,
    #21). `hairdresser_id` est nullable : la segmentation ne s'appuie que sur
    `client_id`/`status`/`appointment_date`.
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
                "(salon_id, client_id, appointment_date, start_time, end_time, status) "
                "VALUES (:salon_id, :client_id, :day, :start_time, :end_time, :status) "
                "RETURNING id"
            ),
            {
                "salon_id": salon_id,
                "client_id": client_id,
                "day": day,
                "start_time": start_time,
                "end_time": end_time.isoformat(),
                "status": status,
            },
        )
        appointment_id = row.scalar_one()
        conn.commit()
    return str(appointment_id)


def _active_clients(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    """`GET /salons/{id}/active-clients` (US-6.4, #42)."""
    resp = client.get(
        f"/salons/{salon_id}/active-clients",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Segmentation des clients échouée : {resp.text}"
    return resp.json()


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestActiveClientsE2E:
    """`GET /salons/{id}/active-clients` bout-en-bout : GROUP BY SQL réel."""

    # ── Parcours 1 : segmentation réelle (GROUP BY client_id) ─────────────────

    def test_new_recurring_inactive_segments_reflect_real_group_by(
        self, _e2e_client: TestClient
    ) -> None:
        """Trois profils distincts → `segment_active_clients` agrège correctement en SQL réel.

        - Client « nouveau » : une visite `COMPLETED` **dans** la période, aucune avant.
        - Client « récurrent » : une visite **avant** la période, une **dans**.
        - Client « inactif » : une visite **avant** la période, aucune dans.
        """
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        client_new = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_NEW_LOCAL)
        client_recurring = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_RECURRING_LOCAL
        )
        client_inactive = _register_client_account(
            _e2e_client, phone=_PHONE_CLIENT_INACTIVE_LOCAL
        )

        today = datetime.date.today()
        period_from = today - datetime.timedelta(days=5)
        period_to = today
        before_period = period_from - datetime.timedelta(days=10)
        in_period = period_from + datetime.timedelta(days=1)

        _seed_appointment(salon_id, client_new, day=in_period)

        _seed_appointment(salon_id, client_recurring, day=before_period)
        _seed_appointment(salon_id, client_recurring, day=in_period)

        _seed_appointment(salon_id, client_inactive, day=before_period)

        segments = _active_clients(
            _e2e_client,
            manager_token,
            salon_id,
            date_from=period_from.isoformat(),
            date_to=period_to.isoformat(),
        )

        assert segments["new"] == 1
        assert segments["recurring"] == 1
        assert segments["inactive"] == 1
        assert segments["active"] == 2
        assert segments["date_from"] == period_from.isoformat()
        assert segments["date_to"] == period_to.isoformat()

    def test_non_completed_statuses_excluded(self, _e2e_client: TestClient) -> None:
        """Un RDV `PENDING`/`CANCELLED`/`NO_SHOW` ne compte jamais comme une visite."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_NEW_LOCAL)

        today = datetime.date.today()
        period_from = today - datetime.timedelta(days=5)
        period_to = today
        for i, status in enumerate(("PENDING", "CANCELLED", "NO_SHOW")):
            _seed_appointment(
                salon_id,
                client_id,
                day=period_from + datetime.timedelta(days=1),
                status=status,
                start_time=f"{9 + i:02d}:00",
            )

        segments = _active_clients(
            _e2e_client,
            manager_token,
            salon_id,
            date_from=period_from.isoformat(),
            date_to=period_to.isoformat(),
        )

        assert segments["new"] == 0
        assert segments["recurring"] == 0
        assert segments["inactive"] == 0
        assert segments["active"] == 0

    # ── Parcours 2 : défaut de période (mois civil courant) ────────────────────

    def test_missing_bounds_default_to_current_month(self, _e2e_client: TestClient) -> None:
        """Sans `date_from`/`date_to`, la segmentation porte sur le mois civil courant."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_NEW_LOCAL)

        today = datetime.date.today()
        month_from, month_to = month_bounds(today)
        _seed_appointment(salon_id, client_id, day=today)

        segments = _active_clients(_e2e_client, manager_token, salon_id)

        assert segments["date_from"] == month_from.isoformat()
        assert segments["date_to"] == month_to.isoformat()
        assert segments["new"] == 1

    # ── Parcours 3 : isolation §11.2 ───────────────────────────────────────────

    def test_other_salon_visit_not_counted(self, _e2e_client: TestClient) -> None:
        """Une visite dans le salon B n'entre jamais dans la segmentation du salon A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_NEW_LOCAL)

        today = datetime.date.today()
        period_from = today - datetime.timedelta(days=5)
        _seed_appointment(salon_b_id, client_id, day=period_from + datetime.timedelta(days=1))

        segments = _active_clients(
            _e2e_client,
            token_a,
            salon_a_id,
            date_from=period_from.isoformat(),
            date_to=today.isoformat(),
        )

        assert segments["new"] == 0
        assert segments["recurring"] == 0
        assert segments["inactive"] == 0

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Le jeton du gérant A est refusé pour consulter la segmentation du salon B."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.get(
            f"/salons/{salon_b_id}/active-clients",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    # ── Parcours 4 : état vide ──────────────────────────────────────────────────

    def test_salon_without_completed_appointments_returns_zero_segments(
        self, _e2e_client: TestClient
    ) -> None:
        """Un salon sans RDV réalisé renvoie les trois compteurs à `0` (état normal)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        segments = _active_clients(_e2e_client, manager_token, salon_id)

        assert segments["new"] == 0
        assert segments["recurring"] == 0
        assert segments["inactive"] == 0
        assert segments["active"] == 0

    # ── Parcours 5 : deny-by-default (ADR-0015) ─────────────────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        assert manager_id

        resp = _e2e_client.get(f"/salons/{salon_id}/active-clients")
        assert resp.status_code == 401

    # ── Parcours 6 : anti-oracle / absence de PII (§11.1/§11.3) ─────────────────

    def test_response_contains_no_pii(self, _e2e_client: TestClient) -> None:
        """La réponse agrégée ne révèle aucune PII (client, jeton) — anti-oracle §11.1."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_NEW_LOCAL)
        appointment_id = _seed_appointment(salon_id, client_id, day=datetime.date.today())

        resp = _e2e_client.get(
            f"/salons/{salon_id}/active-clients",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert manager_token not in resp.text
        assert client_id not in resp.text
        assert appointment_id not in resp.text
