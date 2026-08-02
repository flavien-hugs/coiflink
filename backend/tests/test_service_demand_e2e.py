"""Tests e2e pour US-6.3 — prestations les plus demandées, dashboard gérant (#41).

Groupe `TestServiceDemandE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlAppointmentRepository.demand_by_service` —
    la requête `select(service_id, name, count(), sum(price_at_booking))
    .join(appointments).join(services).where(salon_id, status IN (...))
    .group_by(service_id, name)`. Aucune suite unitaire/API (adossée à
    `FakeAppointmentRepository`) ne couvre ce SQL : c'est le seul code qui satisfait
    réellement le critère d'acceptation #41 *« top prestations par volume et par
    revenu »*.

Scénarios (spec `specs/prestations-les-plus-demandees.md`) :
    - plusieurs prestations, plusieurs RDV `COMPLETED` multi-prestations → `volume`
      (COUNT) et `revenue` (SUM `price_at_booking`) reflètent exactement le
      `GROUP BY` réel, et `by_volume`/`by_revenue` produisent deux ordres distincts
      (départage domaine appliqué à un agrégat SQL réel) ;
    - filtre de statut : un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` ne pèse
      ni en volume ni en revenu (« annulés exclus », §8.1) ;
    - bornes de période : `date_from`/`date_to` réaffirmées en SQL
      (`appointment_date`) ;
    - isolation §11.2 : une prestation réalisée dans un autre salon n'apparaît
      jamais (filtre `salon_id` réaffirmé en SQL) ;
    - une prestation désactivée (`is_active=false`) mais présente dans un RDV
      `COMPLETED` reste **nommée** (FK `RESTRICT`, jointure composite) ;
    - salon sans RDV réalisé → classements vides (état normal, pas une erreur) ;
    - `401` sans jeton, `403` inter-salons ;
    - aucune PII (client, coiffeur, RDV, jeton) dans la réponse agrégée.

Les RDV sont insérés **directement en base** (bypass des gardes HTTP de réservation
— créneaux/heures d'ouverture, hors périmètre #41) pour contrôler statut, date et
prix figé sans dépendre du parcours de réservation complet (miroir
`test_daily_summary_e2e.py` #39, `test_receipts_e2e.py` #38).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_service_demand_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225076999xxxx).
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
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-service-demand-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des prestations les plus demandées.
_E2E_PHONE_PREFIX = "+225076999"
_PHONE_MANAGER_A_LOCAL = "0769990001"   # gérant A — parcours principal
_PHONE_MANAGER_B_LOCAL = "0769990002"   # gérant B — isolation inter-salons
_PHONE_CLIENT_LOCAL = "0769990003"
_PASSWORD = "service-demand-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-service-demand-a"
_SALON_NAME_B = "e2e-salon-service-demand-b"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → appointment_services → appointments → services →
    salon_members → salons → users.
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
    - Supprime les données de test (plage +225076999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e des prestations demandées.")

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
        json={"full_name": "Gérant E2E Demande", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client_account(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte client via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E Demande", "phone": phone, "password": _PASSWORD},
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


def _deactivate_service(
    client: TestClient, token: str, salon_id: str, service_id: str
) -> None:
    """Désactive une prestation (soft-delete, `is_active=false`) via l'API."""
    resp = client.delete(
        f"/salons/{salon_id}/services/{service_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204, f"Désactivation prestation échouée : {resp.text}"


def _add_hairdresser(
    client: TestClient, manager_token: str, salon_id: str, *, phone: str
) -> str:
    """Inscrit un coiffeur, l'enregistre comme membre du salon, retourne son UUID."""
    resp_register = client.post(
        "/auth/register",
        json={"full_name": "Coiffeur E2E Demande", "phone": phone, "password": _PASSWORD},
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


def _seed_appointment_with_service(
    salon_id: str,
    client_id: str,
    hairdresser_id: str,
    service_id: str,
    price_at_booking: str,
    *,
    status: str = "COMPLETED",
    day: datetime.date | None = None,
    start_time: str = "10:00",
) -> str:
    """Insère directement en base un RDV (statut/jour/prix contrôlés) avec une prestation.

    Bypass des gardes de réservation HTTP (créneaux/heures d'ouverture) — seul
    l'agrégat `GROUP BY service_id` du dépôt est testé ici, pas le parcours complet
    de réservation (déjà couvert par `test_appointment_concurrency.py`, #21).
    L'exclusion de créneau (`ex_appointments_hairdresser_slot`) ne s'applique
    qu'aux statuts `PENDING`/`CONFIRMED` : plusieurs RDV `COMPLETED` au même
    coiffeur/créneau peuvent coexister sans conflit.
    """
    day = day or datetime.date.today()
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


def _service_demand(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    """`GET /salons/{id}/service-demand` (US-6.3, #41)."""
    resp = client.get(
        f"/salons/{salon_id}/service-demand",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Classement des prestations échoué : {resp.text}"
    return resp.json()


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestServiceDemandE2E:
    """`GET /salons/{id}/service-demand` bout-en-bout : GROUP BY SQL réel."""

    # ── Parcours 1 : agrégat réel (GROUP BY service_id) ───────────────────────

    def test_volume_and_revenue_reflect_real_group_by(
        self, _e2e_client: TestClient
    ) -> None:
        """Plusieurs prestations, plusieurs RDV `COMPLETED` → agrégat SQL réel.

        `by_volume` et `by_revenue` doivent produire deux **ordres distincts** :
        « Coupe homme » (3×, 30000) domine en volume et en revenu ; entre « Barbe »
        (2×, 10000) et « Tresses » (1×, 20000), le volume et le revenu s'inversent.
        """
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769990099"
        )
        coupe_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe homme", price="10000.00"
        )
        barbe_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Barbe", price="5000.00"
        )
        tresses_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Tresses", price="20000.00"
        )
        for _ in range(3):
            _seed_appointment_with_service(
                salon_id, client_id, hairdresser_id, coupe_id, "10000.00"
            )
        for _ in range(2):
            _seed_appointment_with_service(
                salon_id, client_id, hairdresser_id, barbe_id, "5000.00"
            )
        _seed_appointment_with_service(
            salon_id, client_id, hairdresser_id, tresses_id, "20000.00"
        )

        demand = _service_demand(_e2e_client, manager_token, salon_id)

        by_volume = {row["service_id"]: row for row in demand["by_volume"]}
        assert by_volume[coupe_id]["volume"] == 3
        assert decimal.Decimal(by_volume[coupe_id]["revenue"]) == decimal.Decimal("30000.00")
        assert by_volume[barbe_id]["volume"] == 2
        assert decimal.Decimal(by_volume[barbe_id]["revenue"]) == decimal.Decimal("10000.00")
        assert by_volume[tresses_id]["volume"] == 1
        assert decimal.Decimal(by_volume[tresses_id]["revenue"]) == decimal.Decimal(
            "20000.00"
        )

        volume_order = [row["service_id"] for row in demand["by_volume"]]
        assert volume_order == [coupe_id, barbe_id, tresses_id]

        revenue_order = [row["service_id"] for row in demand["by_revenue"]]
        assert revenue_order == [coupe_id, tresses_id, barbe_id]

    def test_non_completed_statuses_excluded(self, _e2e_client: TestClient) -> None:
        """Un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` ne pèse ni en volume ni en revenu."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769990098"
        )
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe homme", price="10000.00"
        )
        for i, status in enumerate(("PENDING", "CANCELLED", "NO_SHOW")):
            _seed_appointment_with_service(
                salon_id,
                client_id,
                hairdresser_id,
                service_id,
                "10000.00",
                status=status,
                start_time=f"{9 + i:02d}:00",
            )
        _seed_appointment_with_service(
            salon_id,
            client_id,
            hairdresser_id,
            service_id,
            "10000.00",
            status="COMPLETED",
            start_time="15:00",
        )

        demand = _service_demand(_e2e_client, manager_token, salon_id)

        assert len(demand["by_volume"]) == 1
        assert demand["by_volume"][0]["volume"] == 1
        assert decimal.Decimal(demand["by_volume"][0]["revenue"]) == decimal.Decimal(
            "10000.00"
        )

    # ── Parcours 2 : bornes de période ─────────────────────────────────────────

    def test_date_bounds_filter_appointments(self, _e2e_client: TestClient) -> None:
        """`date_from`/`date_to` réaffirmées en SQL (`appointment_date`)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769990097"
        )
        old_service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Ancienne prestation", price="8000.00"
        )
        recent_service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Prestation récente", price="12000.00"
        )
        old_day = datetime.date.today() - datetime.timedelta(days=30)
        today = datetime.date.today()
        _seed_appointment_with_service(
            salon_id, client_id, hairdresser_id, old_service_id, "8000.00", day=old_day
        )
        _seed_appointment_with_service(
            salon_id, client_id, hairdresser_id, recent_service_id, "12000.00", day=today
        )

        # Sans bornes → toute l'histoire, les deux prestations comptent.
        unbounded = _service_demand(_e2e_client, manager_token, salon_id)
        assert {row["service_id"] for row in unbounded["by_volume"]} == {
            old_service_id,
            recent_service_id,
        }

        # Bornée sur aujourd'hui → seule la prestation récente compte.
        bounded = _service_demand(
            _e2e_client,
            manager_token,
            salon_id,
            date_from=today.isoformat(),
            date_to=today.isoformat(),
        )
        assert {row["service_id"] for row in bounded["by_volume"]} == {recent_service_id}
        assert bounded["date_from"] == today.isoformat()
        assert bounded["date_to"] == today.isoformat()

    # ── Parcours 3 : isolation §11.2 ───────────────────────────────────────────

    def test_other_salon_service_not_counted(self, _e2e_client: TestClient) -> None:
        """Une prestation réalisée dans le salon B n'apparaît jamais dans le classement de A."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        hairdresser_b_id = _add_hairdresser(
            _e2e_client, token_b, salon_b_id, phone="0769990096"
        )
        service_b_id = _create_service(
            _e2e_client, token_b, salon_b_id, name="Prestation salon B", price="15000.00"
        )
        _seed_appointment_with_service(
            salon_b_id, client_id, hairdresser_b_id, service_b_id, "15000.00"
        )

        demand_a = _service_demand(_e2e_client, token_a, salon_a_id)
        assert demand_a["by_volume"] == []
        assert demand_a["by_revenue"] == []

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Le jeton du gérant A est refusé pour consulter le classement du salon B."""
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.get(
            f"/salons/{salon_b_id}/service-demand",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    # ── Parcours 4 : prestation désactivée reste nommée ────────────────────────

    def test_soft_deleted_service_still_named(self, _e2e_client: TestClient) -> None:
        """Une prestation `is_active=false` présente dans un RDV réalisé reste nommée."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769990095"
        )
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Prestation retirée", price="7000.00"
        )
        _seed_appointment_with_service(
            salon_id, client_id, hairdresser_id, service_id, "7000.00"
        )
        _deactivate_service(_e2e_client, manager_token, salon_id, service_id)

        demand = _service_demand(_e2e_client, manager_token, salon_id)

        assert len(demand["by_volume"]) == 1
        assert demand["by_volume"][0]["service_id"] == service_id
        assert demand["by_volume"][0]["name"] == "Prestation retirée"

    # ── Parcours 5 : état vide ──────────────────────────────────────────────────

    def test_salon_without_completed_appointments_returns_empty_rankings(
        self, _e2e_client: TestClient
    ) -> None:
        """Un salon sans RDV réalisé renvoie deux classements vides (état normal)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)

        demand = _service_demand(_e2e_client, manager_token, salon_id)

        assert demand["by_volume"] == []
        assert demand["by_revenue"] == []

    # ── Parcours 6 : deny-by-default (ADR-0015) ─────────────────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        assert manager_id

        resp = _e2e_client.get(f"/salons/{salon_id}/service-demand")
        assert resp.status_code == 401

    # ── Parcours 7 : absence de PII (§11.3) ─────────────────────────────────────

    def test_response_contains_no_pii(self, _e2e_client: TestClient) -> None:
        """La réponse agrégée ne révèle aucune PII (client, coiffeur, RDV, jeton)."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        client_id = _register_client_account(_e2e_client, phone=_PHONE_CLIENT_LOCAL)
        assert manager_id
        manager_token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, manager_token, name=_SALON_NAME_A)
        hairdresser_id = _add_hairdresser(
            _e2e_client, manager_token, salon_id, phone="0769990094"
        )
        service_id = _create_service(
            _e2e_client, manager_token, salon_id, name="Coupe homme", price="10000.00"
        )
        appointment_id = _seed_appointment_with_service(
            salon_id, client_id, hairdresser_id, service_id, "10000.00"
        )

        resp = _e2e_client.get(
            f"/salons/{salon_id}/service-demand",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert manager_token not in resp.text
        assert client_id not in resp.text
        assert hairdresser_id not in resp.text
        assert appointment_id not in resp.text
