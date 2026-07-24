"""Tests Postgres e2e — planning personnel du coiffeur (US-3.6, #27).

Garanties vérifiées sur PostgreSQL réel via `GET /appointments/assigned` :
    - Un coiffeur ne reçoit que ses propres RDV assignés (isolation inter-coiffeurs,
      §11.2, filtre SQL `hairdresser_id = :hairdresser_id`).
    - Les RDV non assignés (`hairdresser_id IS NULL`) sont systématiquement exclus
      (l'égalité SQL exclut NULL par définition de la sémantique SQL).
    - Les RDV d'un autre coiffeur du même salon sont exclus.
    - Les RDV d'un autre coiffeur dans un autre salon sont exclus.
    - La plage `[date_from, date_to]` est inclusive aux deux bornes.
    - Le filtre de statut fonctionne seul et en combinaison.
    - Les résultats sont triés `(appointment_date ASC, start_time ASC)`.

Ces scénarios complètent les tests unitaires (fakes dans `test_appointment_usecases.py`)
et les tests HTTP sur fakes (`test_appointment_api.py`) : seul ce fichier exerce
la clause `WHERE hairdresser_id = :id` réelle de PostgreSQL.

Les données sont insérées directement en base (bypass des gardes HTTP) pour
contrôler `hairdresser_id` (y compris NULL) et les statuts — ce que l'API de
réservation ne permet pas.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_hairdresser_planning_e2e.py -v

Nettoyage : données de test supprimées avant et après chaque test
(plage réservée : +225074997xxxx).
"""

from __future__ import annotations

import datetime
import os
import uuid
from collections.abc import Generator
from dataclasses import dataclass

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
_TEST_JWT_SECRET = "test-only-hairdresser-planning-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e du planning coiffeur.
_E2E_PHONE_PREFIX = "+225074997"
_PHONE_MANAGER_A = "+22507499700"
_PHONE_MANAGER_B = "+22507499701"
_PHONE_HAIRDRESSER_A = "+22507499702"
_PHONE_HAIRDRESSER_B = "+22507499703"
_PHONE_CLIENT = "+22507499704"
_PASSWORD = "hairdresser-planning-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-hairdresser-planning-salon-a"
_SALON_NAME_B = "e2e-hairdresser-planning-salon-b"

# Plage de dates de référence pour les tests (milieu d'année future).
_DATE_FROM = datetime.date(2026, 8, 1)
_DATE_TO = datetime.date(2026, 8, 7)


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK.

    Ordre : appointment_services → appointments → audit_logs → services →
    salon_members → salons → users. Couvre à la fois les suppressions par
    client_id et par hairdresser_id (RDV insérés directement en base).
    """
    engine = get_engine()
    users_of_prefix = "SELECT id FROM users WHERE phone LIKE :prefix"
    with engine.connect() as conn:
        params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}
        # Jonctions RDV ↔ prestation (FK appointment_id → appointments CASCADE).
        conn.execute(
            text(
                "DELETE FROM appointment_services WHERE appointment_id IN "
                f"(SELECT id FROM appointments WHERE client_id IN ({users_of_prefix}))"
            ),
            params,
        )
        conn.execute(
            text(
                "DELETE FROM appointment_services WHERE appointment_id IN "
                f"(SELECT id FROM appointments WHERE hairdresser_id IN ({users_of_prefix}))"
            ),
            params,
        )
        # Rendez-vous (FK vers users et salons, RESTRICT).
        conn.execute(
            text(f"DELETE FROM appointments WHERE client_id IN ({users_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM appointments WHERE hairdresser_id IN ({users_of_prefix})"
            ),
            params,
        )
        # Journal d'audit (FK vers users et salons).
        conn.execute(
            text(
                "DELETE FROM audit_logs WHERE salon_id IN "
                f"(SELECT id FROM salons WHERE owner_id IN ({users_of_prefix}))"
            ),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM audit_logs WHERE actor_user_id IN ({users_of_prefix})"
            ),
            params,
        )
        # Prestations (FK salon_id → salons RESTRICT).
        conn.execute(
            text(
                "DELETE FROM services WHERE salon_id IN "
                f"(SELECT id FROM salons WHERE owner_id IN ({users_of_prefix}))"
            ),
            params,
        )
        # Appartenances coiffeur↔salon.
        conn.execute(
            text(f"DELETE FROM salon_members WHERE user_id IN ({users_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE salon_id IN "
                f"(SELECT id FROM salons WHERE owner_id IN ({users_of_prefix}))"
            ),
            params,
        )
        # Salons (FK owner_id → users RESTRICT).
        conn.execute(
            text(f"DELETE FROM salons WHERE owner_id IN ({users_of_prefix})"),
            params,
        )
        # Comptes utilisateurs.
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT) ; skip sans `DATABASE_URL`."""
    if not _DATABASE_URL:
        pytest.skip(
            "DATABASE_URL requis — l'isolation SQL du planning coiffeur (§11.2) "
            "ne peut être vérifiée qu'avec une base PostgreSQL réelle."
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


def _register_manager(client: TestClient, phone: str, name: str) -> str:
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": name, "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée ({phone}): {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, phone: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée ({phone}): {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, name: str) -> str:
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée: {resp.text}"
    return resp.json()["id"]


def _add_hairdresser(
    client: TestClient, token: str, salon_id: str, phone: str, name: str
) -> str:
    resp = client.post(
        f"/salons/{salon_id}/employees",
        json={"full_name": name, "phone": phone, "password": _PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création coiffeur échouée ({phone}): {resp.text}"
    return resp.json()["id"]


def _register_client(client: TestClient) -> str:
    resp = client.post(
        "/auth/register",
        json={
            "full_name": "Client Planning E2E",
            "phone": _PHONE_CLIENT,
            "password": _PASSWORD,
        },
    )
    assert resp.status_code == 201, f"Inscription client échouée: {resp.text}"
    return resp.json()["id"]


def _insert_appointment(
    *,
    salon_id: str,
    client_id: str,
    hairdresser_id: str | None,
    appointment_date: datetime.date,
    start_time: str,
    end_time: str,
    status: str,
) -> str:
    """Insère un RDV directement en base pour contrôler hairdresser_id (y compris NULL).

    `created_at` / `updated_at` sont omis : PostgreSQL applique `server_default=now()`.
    `slot` est une colonne générée (COMPUTED) — pas d'insertion manuelle.
    """
    appt_id = str(uuid.uuid4())
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO appointments "
                "(id, salon_id, client_id, hairdresser_id, appointment_date, "
                "start_time, end_time, status) "
                "VALUES (:id, :salon_id, :client_id, :hairdresser_id, "
                ":date, :start, :end, :status)"
            ),
            {
                "id": appt_id,
                "salon_id": salon_id,
                "client_id": client_id,
                "hairdresser_id": hairdresser_id,
                "date": appointment_date,
                "start": start_time,
                "end": end_time,
                "status": status,
            },
        )
        conn.commit()
    return appt_id


@dataclass
class _Fixture:
    """Décor de test : deux salons, deux coiffeurs, un client."""

    salon_a_id: str
    salon_b_id: str
    hairdresser_a_id: str
    hairdresser_b_id: str
    client_id: str
    token_a: str


@pytest.fixture()
def _fixture(_e2e_client: TestClient) -> _Fixture:
    """Monte le décor complet via l'API.

    - Gérant A → Salon A ; Gérant B → Salon B (isolation inter-salons).
    - Coiffeur A membre de Salon A (principal sous test).
    - Coiffeur B membre de Salon A (isolation inter-coiffeurs dans le même salon).
    - Client pour les FK `client_id`.
    """
    client = _e2e_client

    _register_manager(client, _PHONE_MANAGER_A, "Gérant Planning A")
    token_mgr_a = _login(client, _PHONE_MANAGER_A)
    salon_a_id = _create_salon(client, token_mgr_a, _SALON_NAME_A)

    _register_manager(client, _PHONE_MANAGER_B, "Gérant Planning B")
    token_mgr_b = _login(client, _PHONE_MANAGER_B)
    salon_b_id = _create_salon(client, token_mgr_b, _SALON_NAME_B)

    hairdresser_a_id = _add_hairdresser(
        client, token_mgr_a, salon_a_id, _PHONE_HAIRDRESSER_A, "Coiffeur Planning A"
    )
    token_a = _login(client, _PHONE_HAIRDRESSER_A)

    hairdresser_b_id = _add_hairdresser(
        client, token_mgr_a, salon_a_id, _PHONE_HAIRDRESSER_B, "Coiffeur Planning B"
    )

    client_id = _register_client(client)

    return _Fixture(
        salon_a_id=salon_a_id,
        salon_b_id=salon_b_id,
        hairdresser_a_id=hairdresser_a_id,
        hairdresser_b_id=hairdresser_b_id,
        client_id=client_id,
        token_a=token_a,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestHairdresserPlanningIsolationE2E:
    """Isolation SQL de `GET /appointments/assigned` sur PostgreSQL réel (§11.2, #27).

    Vérifie que `SqlAppointmentRepository.list_for_hairdresser` filtre correctement
    `hairdresser_id = :id` — ce qu'aucun fake ne peut garantir.
    """

    _URL = "/appointments/assigned"

    def _get(
        self,
        client: TestClient,
        token: str,
        *,
        date_from: datetime.date = _DATE_FROM,
        date_to: datetime.date = _DATE_TO,
        status: list[str] | None = None,
    ) -> list[dict]:
        params: list[tuple[str, str]] = [
            ("date_from", date_from.isoformat()),
            ("date_to", date_to.isoformat()),
        ]
        if status:
            for s in status:
                params.append(("status", s))
        resp = client.get(
            self._URL,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, (
            f"GET {self._URL} : attendu 200, obtenu {resp.status_code} — {resp.text}"
        )
        return resp.json()

    # --- Isolation inter-coiffeurs (§11.2) ------------------------------------

    def test_other_hairdresser_same_salon_excluded(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Un RDV du coiffeur B (même salon A) n'apparaît pas dans le planning du coiffeur A."""
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_b_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        assert self._get(_e2e_client, _fixture.token_a) == []

    def test_unassigned_appointments_excluded(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Un RDV non assigné (`hairdresser_id IS NULL`) n'apparaît jamais dans le planning."""
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=None,
            appointment_date=_DATE_FROM,
            start_time="11:00",
            end_time="12:00",
            status="PENDING",
        )
        assert self._get(_e2e_client, _fixture.token_a) == []

    def test_other_hairdresser_other_salon_excluded(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Un RDV du coiffeur B dans le salon B n'apparaît pas dans le planning du coiffeur A."""
        _insert_appointment(
            salon_id=_fixture.salon_b_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_b_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        assert self._get(_e2e_client, _fixture.token_a) == []

    def test_own_appointments_returned(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Les RDV du coiffeur A sont bien retournés."""
        appt_id = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        result = self._get(_e2e_client, _fixture.token_a)
        assert len(result) == 1
        assert result[0]["id"] == appt_id

    # --- Plage de dates inclusive aux deux bornes ─────────────────────────────

    def test_boundary_dates_included(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Les RDV exactement à `date_from` et `date_to` sont inclus."""
        id_first = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        id_last = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_TO,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        result = self._get(_e2e_client, _fixture.token_a)
        ids = {item["id"] for item in result}
        assert id_first in ids
        assert id_last in ids

    def test_appointment_before_range_excluded(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Un RDV la veille de `date_from` n'apparaît pas."""
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM - datetime.timedelta(days=1),
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        assert self._get(_e2e_client, _fixture.token_a) == []

    def test_appointment_after_range_excluded(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Un RDV le lendemain de `date_to` n'apparaît pas."""
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_TO + datetime.timedelta(days=1),
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        assert self._get(_e2e_client, _fixture.token_a) == []

    # --- Filtre statut ─────────────────────────────────────────────────────────

    def test_status_filter_single_excludes_others(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """`status=PENDING` exclut les CONFIRMED."""
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="10:00",
            end_time="11:00",
            status="CONFIRMED",
        )
        result = self._get(_e2e_client, _fixture.token_a, status=["PENDING"])
        assert len(result) == 1
        assert result[0]["status"] == "PENDING"

    def test_status_filter_multi_excludes_unselected(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """`status=PENDING&status=CONFIRMED` exclut les CANCELLED."""
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="10:00",
            end_time="11:00",
            status="CONFIRMED",
        )
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="11:00",
            end_time="12:00",
            status="CANCELLED",
        )
        result = self._get(_e2e_client, _fixture.token_a, status=["PENDING", "CONFIRMED"])
        statuses = {item["status"] for item in result}
        assert statuses == {"PENDING", "CONFIRMED"}
        assert "CANCELLED" not in statuses

    def test_no_status_filter_returns_all_statuses(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Sans filtre de statut, PENDING + CONFIRMED + CANCELLED sont tous retournés."""
        for start, end, s in [
            ("09:00", "10:00", "PENDING"),
            ("10:00", "11:00", "CONFIRMED"),
            ("11:00", "12:00", "CANCELLED"),
        ]:
            _insert_appointment(
                salon_id=_fixture.salon_a_id,
                client_id=_fixture.client_id,
                hairdresser_id=_fixture.hairdresser_a_id,
                appointment_date=_DATE_FROM,
                start_time=start,
                end_time=end,
                status=s,
            )
        result = self._get(_e2e_client, _fixture.token_a)
        assert len(result) == 3

    # --- Tri chronologique ────────────────────────────────────────────────────

    def test_chronological_ordering(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Les résultats sont triés `(appointment_date ASC, start_time ASC)`."""
        # Insertions intentionnellement dans le désordre.
        id_d4_10 = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=datetime.date(2026, 8, 4),
            start_time="10:00",
            end_time="11:00",
            status="PENDING",
        )
        id_d4_09 = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=datetime.date(2026, 8, 4),
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        id_d1_09 = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,  # 2026-08-01
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        result = self._get(_e2e_client, _fixture.token_a)
        assert len(result) == 3
        assert result[0]["id"] == id_d1_09, "Premier attendu : 01/08 09:00"
        assert result[1]["id"] == id_d4_09, "Deuxième attendu : 04/08 09:00"
        assert result[2]["id"] == id_d4_10, "Troisième attendu : 04/08 10:00"

    # --- Scénario intégral multi-critères ─────────────────────────────────────

    def test_full_scenario_all_isolation_invariants(
        self, _e2e_client: TestClient, _fixture: _Fixture
    ) -> None:
        """Décor complet : multi-coiffeurs, multi-salons, multi-statuts, non assignés.

        Vérifie simultanément tous les invariants : seuls les RDV du coiffeur A
        dans la plage apparaissent — jamais ceux d'un autre coiffeur, d'un autre
        salon, non assignés, ou hors plage.
        """
        # RDV du coiffeur A dans la plage — doivent apparaître.
        id_a1 = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        id_a2 = _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM,
            start_time="10:00",
            end_time="11:00",
            status="CONFIRMED",
        )

        # RDV du coiffeur B (même salon A) — exclus.
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_b_id,
            appointment_date=_DATE_FROM,
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )

        # RDV non assigné (hairdresser_id IS NULL, salon A) — exclu.
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=None,
            appointment_date=_DATE_FROM,
            start_time="13:00",
            end_time="14:00",
            status="PENDING",
        )

        # RDV du coiffeur B dans salon B — exclu.
        _insert_appointment(
            salon_id=_fixture.salon_b_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_b_id,
            appointment_date=_DATE_FROM,
            start_time="14:00",
            end_time="15:00",
            status="PENDING",
        )

        # RDV du coiffeur A hors plage — exclus.
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_FROM - datetime.timedelta(days=1),
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )
        _insert_appointment(
            salon_id=_fixture.salon_a_id,
            client_id=_fixture.client_id,
            hairdresser_id=_fixture.hairdresser_a_id,
            appointment_date=_DATE_TO + datetime.timedelta(days=1),
            start_time="09:00",
            end_time="10:00",
            status="PENDING",
        )

        result = self._get(_e2e_client, _fixture.token_a)
        ids = {item["id"] for item in result}

        assert ids == {id_a1, id_a2}, (
            f"Attendu uniquement {{id_a1, id_a2}}, obtenu {ids}."
        )
        for item in result:
            assert item["hairdresser_id"] == _fixture.hairdresser_a_id, (
                "Tous les RDV retournés doivent appartenir au coiffeur A."
            )
