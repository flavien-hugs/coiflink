"""Tests e2e — gestion des coiffeuses (#150).

Groupe `TestEmployeeAndQueueE2E` (PostgreSQL requis) exerçant le **chemin SQL
réel** qu'aucune suite unitaire/API (adossée à des fakes en mémoire,
`test_employee_usecases.py`/`test_employee_management_api.py`) ne peut
couvrir :

    - la **jointure** `salon_members × users` de `SqlSalonMemberRepository.
      list_for_salon`/`find_by_id` (identité + champs pro réels) ;
    - la retraduction de la violation d'unicité **globale** `users.phone`/
      `users.email` en `PhoneAlreadyInUse`/`EmailAlreadyInUse` à la
      modification de profil (`SqlUserRepository.update_identity`) ;
    - l'effet réel de la désactivation (`salon_members.status = INACTIVE`) sur
      `_require_salon_hairdresser` : une coiffeuse désactivée est refusée à
      la prise en charge d'un ticket walk-in (`404 HairdresserNotInSalon`),
      puis acceptée après réactivation ;
    - la retraduction réelle (SQLSTATE `23505`) de l'index unique partiel
      **global** `uq_queue_tickets_hairdresser_in_progress` en
      `HairdresserAlreadyBusy` (`409`) : une coiffeuse déjà `in_progress` sur
      un ticket est refusée sur un second, puis acceptée une fois le premier
      clôturé (#173).

La lecture de la file d'attente (jointures de noms, filtre de statuts,
dérivation « payée ») a été retirée avec la simplification de la route
combinée au pivot walk-in exclusif (#148) — elle ne couvre plus désormais
que des tickets, sous `GET .../queue/tickets` (`test_queue_ticket_api.py`).

Les tickets sont insérés **directement en base** (bypass de la borne HTTP
d'émission, patron #148/#157 — miroir `_seed_ticket` de
`test_hairdresser_performance_e2e.py`).

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
            "DELETE FROM queue_ticket_services WHERE salon_id IN "
            "(SELECT id FROM salons WHERE owner_id IN "
            "(SELECT id FROM users WHERE phone LIKE :prefix))",
            "DELETE FROM queue_tickets WHERE salon_id IN "
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


def _seed_ticket(
    salon_id: str,
    *,
    day: datetime.date,
    ticket_number: int,
    status: str = "waiting",
) -> str:
    """Insère directement en base un ticket walk-in `waiting` (bypass borne HTTP).

    Miroir `_seed_ticket` de `test_hairdresser_performance_e2e.py` : un walk-in
    n'a **jamais** de coiffeuse pré-assignée (`hairdresser_id` posé uniquement
    par `StartQueueTicket.execute`), donc omis ici — c'est précisément ce que
    la route `start` doit accepter/refuser selon l'éligibilité de la coiffeuse.
    """
    engine = get_engine()
    with engine.connect() as conn:
        ticket_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO queue_tickets "
                "(id, salon_id, issued_date, ticket_number, status, "
                "estimated_wait_minutes) "
                "VALUES (:id, :salon_id, :day, :number, :status, 0)"
            ),
            {
                "id": ticket_id,
                "salon_id": salon_id,
                "day": day,
                "number": ticket_number,
                "status": status,
            },
        )
        conn.commit()
    return ticket_id


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
        """Désactiver une coiffeuse retire son éligibilité à la prise en charge d'un ticket.

        Équivalent ticket walk-in de l'ancienne assignation RDV (#150) :
        `StartQueueTicket.execute` → `_require_salon_hairdresser`
        (`coiflink_api/application/queue_ticket.py`) refuse un `hairdresser_id`
        qui n'est pas membre `ACTIVE` du salon — une coiffeuse désactivée est
        donc refusée à `POST .../queue/tickets/{id}/start` (`404
        HairdresserNotInSalon`, cf. `coiflink_api/adapters/inbound/
        queue_tickets.py`), puis acceptée une fois réactivée.
        """
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)
        employee = _create_employee(
            client, token, salon_id, phone=_PHONE_HAIRDRESSER_1_LOCAL
        )

        deactivate = client.delete(
            f"/salons/{salon_id}/employees/{employee['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deactivate.status_code == 200
        assert deactivate.json()["status"] == "INACTIVE"

        ticket_id = _seed_ticket(
            salon_id, day=datetime.date(2026, 8, 13), ticket_number=1
        )
        start = client.post(
            f"/salons/{salon_id}/queue/tickets/{ticket_id}/start",
            json={"hairdresser_id": employee["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start.status_code == 404

        reactivate = client.post(
            f"/salons/{salon_id}/employees/{employee['id']}/reactivate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reactivate.status_code == 200
        assert reactivate.json()["status"] == "ACTIVE"

        start_again = client.post(
            f"/salons/{salon_id}/queue/tickets/{ticket_id}/start",
            json={"hairdresser_id": employee["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start_again.status_code == 200
        assert start_again.json()["status"] == "in_progress"
        assert start_again.json()["hairdresser_id"] == employee["id"]

    def test_hairdresser_already_busy_rejected_by_real_unique_index(
        self, _e2e_client: TestClient
    ) -> None:
        """#173 : l'index unique partiel global `uq_queue_tickets_hairdresser_in_progress`
        refuse réellement (SQLSTATE 23505, retraduit par
        `SqlQueueTicketRepository.start` en `HairdresserAlreadyBusy`, 409) d'affecter une
        coiffeuse déjà `in_progress` sur un autre ticket. Ni le pré-contrôle applicatif
        (`is_hairdresser_busy`) ni la garde TOCTOU habituelle (`WHERE status = 'waiting'`)
        ne suffiraient seuls à couvrir la course concurrente : c'est la contrainte base
        qui est exercée ici, pas seulement `StartQueueTicket.execute` (déjà couvert par
        les fakes, `test_queue_ticket_usecases.py`).

        Le scénario multi-salons (portée volontairement **globale**, pas par salon) est
        déjà couvert au niveau applicatif par `test_busy_scope_is_global_across_salons`
        (fake `SalonScopeRepository`) — non reproduit ici : `POST .../employees` refuse
        aujourd'hui tout doublon de téléphone (`PhoneAlreadyInUse`), il n'existe encore
        aucune route produit pour rattacher une coiffeuse existante à un second salon.
        """
        client = _e2e_client
        _register_manager(client, phone=_PHONE_MANAGER_A_LOCAL)
        token = _login(client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(client, token, name=_SALON_NAME_A)
        employee = _create_employee(
            client, token, salon_id, phone=_PHONE_HAIRDRESSER_1_LOCAL
        )

        ticket_1 = _seed_ticket(salon_id, day=datetime.date(2026, 8, 13), ticket_number=1)
        ticket_2 = _seed_ticket(salon_id, day=datetime.date(2026, 8, 13), ticket_number=2)

        start_first = client.post(
            f"/salons/{salon_id}/queue/tickets/{ticket_1}/start",
            json={"hairdresser_id": employee["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start_first.status_code == 200

        start_second = client.post(
            f"/salons/{salon_id}/queue/tickets/{ticket_2}/start",
            json={"hairdresser_id": employee["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start_second.status_code == 409

        # Une fois le premier ticket clôturé, la coiffeuse redevient assignable.
        complete_first = client.post(
            f"/salons/{salon_id}/queue/tickets/{ticket_1}/complete",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert complete_first.status_code == 200

        start_second_retry = client.post(
            f"/salons/{salon_id}/queue/tickets/{ticket_2}/start",
            json={"hairdresser_id": employee["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start_second_retry.status_code == 200
        assert start_second_retry.json()["hairdresser_id"] == employee["id"]
