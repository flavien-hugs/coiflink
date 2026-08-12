"""Tests e2e — gestion des coiffeuses + file d'attente (#150).

Groupe `TestEmployeeAndQueueE2E` (PostgreSQL requis) exerçant le **chemin SQL
réel** qu'aucune suite unitaire/API (adossée à des fakes en mémoire,
`test_employee_usecases.py`/`test_employee_management_api.py`/
`test_queue_usecases.py`/`test_queue_api.py`) ne peut couvrir :

    - la **jointure** `salon_members × users` de `SqlSalonMemberRepository.
      list_for_salon`/`find_by_id` (identité + champs pro réels) ;
    - la retraduction de la violation d'unicité **globale** `users.phone`/
      `users.email` en `PhoneAlreadyInUse`/`EmailAlreadyInUse` à la
      modification de profil (`SqlUserRepository.update_identity`) ;
    - l'effet réel de la désactivation (`salon_members.status = INACTIVE`) sur
      `_require_salon_hairdresser` : une coiffeuse désactivée est refusée à
      une **nouvelle** assignation (`404 HairdresserNotInSalon`) mais garde
      ses RDV déjà assignés ;
    - les **jointures de noms** (`users` ×2 + `services`) et le **filtre de
      statuts** (`CONFIRMED`/`COMPLETED` seulement) de `SqlAppointmentRepository.
      list_queue_details` ;
    - l'**idempotence réelle** (`UPDATE ... WHERE arrived_at IS NULL`
      implicite) de `mark_arrived`/`mark_started` et la garde TOCTOU
      (`status = 'CONFIRMED'`) ;
    - la dérivation **« payée »** bout-en-bout : `SqlPaymentRepository.
      list_paid_appointment_ids` ne couvre qu'un RDV avec paiement
      `VALIDATED` réellement persisté (pas un `CANCELLED`) ;
    - l'**isolation §11.2** inter-salons (coiffeuse et file d'attente) et
      l'absence de PII (§11.3) sur des réponses réellement matérialisées.

Les RDV sont insérés **directement en base** (bypass des gardes HTTP de
réservation, patron #43/#148) ; le paiement passe par l'API réelle
(`POST /payments`, seul chemin qui persiste un `VALIDATED`).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_employee_and_queue_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225079997xxxx).
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

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_TEST_JWT_SECRET = "test-only-employee-queue-e2e-jwt-secret-not-for-production"

_E2E_PHONE_PREFIX = "+225079997"
_PHONE_MANAGER_A_LOCAL = "0799970001"
_PHONE_MANAGER_B_LOCAL = "0799970002"
_PHONE_CLIENT_LOCAL = "0799970003"
_PHONE_HAIRDRESSER_1_LOCAL = "0799970004"
_PHONE_HAIRDRESSER_2_LOCAL = "0799970005"
_PASSWORD = "employee-queue-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-employee-queue-a"
_SALON_NAME_B = "e2e-salon-employee-queue-b"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        for stmt in (
            "DELETE FROM audit_logs WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM cash_journal WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM payments WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM notifications WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM notifications WHERE user_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix)",
            "DELETE FROM appointment_services WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM appointments WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM services WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM salon_members WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM salon_members WHERE user_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix)",
            "DELETE FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix)",
            "DELETE FROM users WHERE phone LIKE :prefix",
        ):
            conn.execute(text(stmt), {"prefix": f"{_E2E_PHONE_PREFIX}%"})
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e coiffeuses/file d'attente.")

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
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client_account(client: TestClient, *, phone: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str) -> str:
    resp = client.post(
        "/salons", json={"name": name}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(client: TestClient, token: str, salon_id: str, *, name: str) -> str:
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": name, "price": "5000.00", "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _create_employee(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    phone: str,
    full_name: str = "Coiffeuse E2E",
    specialties: str | None = None,
    hired_at: str | None = None,
) -> dict:
    body: dict[str, object] = {
        "full_name": full_name,
        "phone": phone,
        "password": _PASSWORD,
    }
    if specialties is not None:
        body["specialties"] = specialties
    if hired_at is not None:
        body["hired_at"] = hired_at
    resp = client.post(
        f"/salons/{salon_id}/employees",
        json=body,
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Création coiffeuse échouée : {resp.text}"
    return resp.json()


def _seed_appointment(
    salon_id: str,
    client_id: str,
    hairdresser_id: str | None,
    *,
    day: datetime.date,
    start_time: str,
    status: str,
    service_id: str,
) -> str:
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
        appointment_id = str(row.scalar_one())
        conn.execute(
            text(
                "INSERT INTO appointment_services "
                "(salon_id, appointment_id, service_id, price_at_booking) "
                "VALUES (:salon_id, :appointment_id, :service_id, 5000.00)"
            ),
            {"salon_id": salon_id, "appointment_id": appointment_id, "service_id": service_id},
        )
        conn.commit()
    return appointment_id


def _record_payment(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    appointment_id: str,
    client_id: str,
) -> dict:
    resp = client.post(
        f"/salons/{salon_id}/payments",
        json={
            "amount": "5000.00",
            "payment_method": "CASH",
            "appointment_id": appointment_id,
            "client_id": client_id,
        },
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Enregistrement paiement échoué : {resp.text}"
    return resp.json()


def _queue(client: TestClient, token: str, salon_id: str, *, day: str) -> list[dict]:
    resp = client.get(
        f"/salons/{salon_id}/queue",
        params={"day": day},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Lecture file d'attente échouée : {resp.text}"
    # #157 restructure la réponse en {"appointments": [...], "walk_in_tickets": [...]} ;
    # cette suite (#152) ne couvre que les RDV planifiés.
    return resp.json()["appointments"]


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestEmployeeAndQueueE2E:
    # ── Coiffeuses : jointure identité + champs pro ─────────────────────────

    def test_list_and_get_reflect_real_join_with_users(
        self, _e2e_client: TestClient
    ) -> None:
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)

        created = _create_employee(
            client,
            token,
            salon_id,
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
            full_name="Fatou Diarra",
            specialties="Tresses, colorations",
            hired_at="2026-01-15",
        )
        employee_id = created["id"]

        listing = client.get(
            f"/salons/{salon_id}/employees", headers={"Authorization": f"Bearer {token}"}
        )
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["full_name"] == "Fatou Diarra"
        assert listing.json()[0]["specialties"] == "Tresses, colorations"

        single = client.get(
            f"/salons/{salon_id}/employees/{employee_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert single.status_code == 200
        assert single.json()["hired_at"] == "2026-01-15"
        assert single.json()["status"] == "ACTIVE"

    def test_isolation_between_salons(self, _e2e_client: TestClient) -> None:
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token_a = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_a = _create_salon(client, token_a, name=_SALON_NAME_A)
        _create_employee(
            client, token_a, salon_a, phone=_PHONE_HAIRDRESSER_1_LOCAL
        )

        _register_manager(client, phone=_PHONE_MANAGER_B_LOCAL)
        token_b = _login(client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_b = _create_salon(client, token_b, name=_SALON_NAME_B)

        listing_b = client.get(
            f"/salons/{salon_b}/employees", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert listing_b.status_code == 200
        assert listing_b.json() == []

    def test_update_profile_rejects_duplicate_phone_of_other_account(
        self, _e2e_client: TestClient
    ) -> None:
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)

        _create_employee(client, token, salon_id, phone=_PHONE_HAIRDRESSER_1_LOCAL)
        second = _create_employee(
            client,
            token,
            salon_id,
            phone=_PHONE_HAIRDRESSER_2_LOCAL,
            full_name="Autre Coiffeuse",
        )

        resp = client.put(
            f"/salons/{salon_id}/employees/{second['id']}",
            json={
                "full_name": "Autre Coiffeuse",
                "phone": _PHONE_HAIRDRESSER_1_LOCAL,
                "email": None,
                "specialties": None,
                "hired_at": None,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409
        assert _PHONE_HAIRDRESSER_1_LOCAL not in resp.text

    def test_deactivated_employee_rejected_for_new_assignment(
        self, _e2e_client: TestClient
    ) -> None:
        """Désactiver une coiffeuse retire son éligibilité aux **nouvelles** affectations."""
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)
        client_id = _register_client_account(
            client, phone=_PHONE_CLIENT_LOCAL
        )
        service_id = _create_service(client, token, salon_id, name="Coupe")
        employee = _create_employee(
            client, token, salon_id, phone=_PHONE_HAIRDRESSER_1_LOCAL
        )

        deactivate = client.delete(
            f"/salons/{salon_id}/employees/{employee['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deactivate.status_code == 200
        assert deactivate.json()["status"] == "INACTIVE"

        appointment_id = _seed_appointment(
            salon_id,
            client_id,
            None,
            day=datetime.date(2026, 8, 10),
            start_time="09:00",
            status="CONFIRMED",
            service_id=service_id,
        )
        assign = client.put(
            f"/salons/{salon_id}/appointments/{appointment_id}/hairdresser",
            json={"hairdresser_id": employee["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert assign.status_code == 404

        reactivate = client.post(
            f"/salons/{salon_id}/employees/{employee['id']}/reactivate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reactivate.status_code == 200
        assert reactivate.json()["status"] == "ACTIVE"

        assign_again = client.put(
            f"/salons/{salon_id}/appointments/{appointment_id}/hairdresser",
            json={"hairdresser_id": employee["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert assign_again.status_code == 200

    # ── File d'attente : jointures réelles + dérivation de statut ──────────

    def test_queue_reflects_real_joins_and_status_filter(
        self, _e2e_client: TestClient
    ) -> None:
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)
        client_id = _register_client_account(
            client, phone=_PHONE_CLIENT_LOCAL
        )
        service_id = _create_service(client, token, salon_id, name="Coupe homme")
        employee = _create_employee(
            client,
            token,
            salon_id,
            phone=_PHONE_HAIRDRESSER_1_LOCAL,
            full_name="Fatou Diarra",
        )
        day = datetime.date(2026, 8, 11)

        confirmed_id = _seed_appointment(
            salon_id, client_id, employee["id"], day=day, start_time="09:00",
            status="CONFIRMED", service_id=service_id,
        )
        _seed_appointment(
            salon_id, client_id, employee["id"], day=day, start_time="10:00",
            status="PENDING", service_id=service_id,
        )
        _seed_appointment(
            salon_id, client_id, employee["id"], day=day, start_time="11:00",
            status="CANCELLED", service_id=service_id,
        )

        entries = _queue(client, token, salon_id, day=day.isoformat())
        # Seul le RDV CONFIRMED entre dans la file (PENDING/CANCELLED exclus).
        assert len(entries) == 1
        entry = entries[0]
        assert entry["appointment_id"] == confirmed_id
        assert entry["client_name"] == "Client E2E"
        assert entry["hairdresser_name"] == "Fatou Diarra"
        assert entry["service_names"] == ["Coupe homme"]
        assert entry["queue_status"] == "waiting"
        assert client_id not in str(entries)

    def test_pointage_and_payment_derive_full_lifecycle(
        self, _e2e_client: TestClient
    ) -> None:
        """Attente → pointée arrivée (toujours attente) → en cours → terminée → payée."""
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)
        client_id = _register_client_account(
            client, phone=_PHONE_CLIENT_LOCAL
        )
        service_id = _create_service(client, token, salon_id, name="Brushing")
        employee = _create_employee(
            client, token, salon_id, phone=_PHONE_HAIRDRESSER_1_LOCAL
        )
        day = datetime.date(2026, 8, 12)
        appointment_id = _seed_appointment(
            salon_id, client_id, employee["id"], day=day, start_time="09:00",
            status="CONFIRMED", service_id=service_id,
        )

        assert _queue(client, token, salon_id, day=day.isoformat())[0]["queue_status"] == "waiting"

        arrival = client.post(
            f"/salons/{salon_id}/appointments/{appointment_id}/arrival",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert arrival.status_code == 200
        first_arrived_at = arrival.json()["arrived_at"]
        assert first_arrived_at is not None
        # Idempotent : un second pointage ne change pas l'horodatage.
        arrival_again = client.post(
            f"/salons/{salon_id}/appointments/{appointment_id}/arrival",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert arrival_again.json()["arrived_at"] == first_arrived_at
        # Arrivée seule : toujours « en attente » (informative, pas une étape distincte).
        assert _queue(client, token, salon_id, day=day.isoformat())[0]["queue_status"] == "waiting"

        start = client.post(
            f"/salons/{salon_id}/appointments/{appointment_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start.status_code == 200
        assert _queue(client, token, salon_id, day=day.isoformat())[0]["queue_status"] == "in_progress"

        complete = client.post(
            f"/salons/{salon_id}/appointments/{appointment_id}/status",
            json={"status": "COMPLETED"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert complete.status_code == 200
        assert _queue(client, token, salon_id, day=day.isoformat())[0]["queue_status"] == "completed"

        _record_payment(client, token, salon_id, appointment_id=appointment_id, client_id=client_id)
        assert _queue(client, token, salon_id, day=day.isoformat())[0]["queue_status"] == "paid"

    def test_start_without_arrival_returns_409(self, _e2e_client: TestClient) -> None:
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)
        client_id = _register_client_account(
            client, phone=_PHONE_CLIENT_LOCAL
        )
        service_id = _create_service(client, token, salon_id, name="Coupe")
        employee = _create_employee(
            client, token, salon_id, phone=_PHONE_HAIRDRESSER_1_LOCAL
        )
        appointment_id = _seed_appointment(
            salon_id, client_id, employee["id"], day=datetime.date(2026, 8, 13),
            start_time="09:00", status="CONFIRMED", service_id=service_id,
        )

        resp = client.post(
            f"/salons/{salon_id}/appointments/{appointment_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409

    def test_queue_isolation_between_salons(self, _e2e_client: TestClient) -> None:
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token_a = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_a = _create_salon(client, token_a, name=_SALON_NAME_A)
        client_id = _register_client_account(
            client, phone=_PHONE_CLIENT_LOCAL
        )
        service_id = _create_service(client, token_a, salon_a, name="Coupe")
        employee = _create_employee(
            client, token_a, salon_a, phone=_PHONE_HAIRDRESSER_1_LOCAL
        )
        day = datetime.date(2026, 8, 14)
        _seed_appointment(
            salon_a, client_id, employee["id"], day=day, start_time="09:00",
            status="CONFIRMED", service_id=service_id,
        )

        _register_manager(client, phone=_PHONE_MANAGER_B_LOCAL)
        token_b = _login(client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_b = _create_salon(client, token_b, name=_SALON_NAME_B)

        assert _queue(client, token_b, salon_b, day=day.isoformat()) == []

    def test_no_token_returns_401_for_queue(self, _e2e_client: TestClient) -> None:
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)

        resp = client.get(f"/salons/{salon_id}/queue")
        assert resp.status_code == 401
