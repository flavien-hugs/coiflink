"""Tests e2e pour US-5.4 — détection des écarts de caisse (#36).

Groupe `TestCashDiscrepanciesE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlPaymentRepository.list_completed_without_payment`
    / `count_completed_without_payment` — la requête `NOT EXISTS` sur
    `payments.appointment_id`, le `LEFT JOIN appointment_services` + `GROUP BY` pour le
    **montant attendu**, la résolution `users.full_name`, les bornes de dates sur
    `appointment_date`, l'isolation `salon_id`, le tri et la pagination. Aucune suite
    unitaire/API (adossées à `FakePaymentRepository`) ne couvre ce SQL : c'est le seul
    code qui satisfait réellement le critère d'acceptation #36 *« un RDV terminé sans
    paiement est signalé comme écart »*.

Scénarios (spec `specs/detection-ecarts-de-caisse.md`, section Testing Plan) :
    - RDV `COMPLETED` **sans** paiement → **signalé**, `expected_amount` correct ;
    - RDV `COMPLETED` **avec** paiement `VALIDATED` → **absent** ;
    - RDV `COMPLETED` dont le paiement est `ADJUSTED` (corrigé) → **absent** ;
    - RDV `COMPLETED` dont le seul paiement est `CANCELLED` → **signalé** ;
    - RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` → **jamais** signalé ;
    - isolation §11.2 : RDV d'un autre salon absent ; un paiement d'un autre salon ne
      couvre jamais un RDV ;
    - `expected_amount` = somme des `price_at_booking` (plusieurs lignes) ;
    - résolution `client_name` = `users.full_name` ;
    - bornes de dates `date_from`/`date_to` inclusives ; hors plage → exclu ;
    - pagination (`limit`/`offset`/`total`) et tri `appointment_date DESC, start_time DESC` ;
    - `401` sans jeton, `403` inter-salons (pile complète).

Les RDV, lignes de prestation et paiements sont insérés **directement en base** (bypass
des gardes HTTP) pour contrôler statuts, `price_at_booking` et l'absence/présence de
paiement — ce que les API de réservation/encaissement ne permettent pas.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_cash_discrepancies_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225076998xxxx).
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
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-discrepancies-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des écarts de caisse.
_E2E_PHONE_PREFIX = "+225076998"
_PHONE_A_LOCAL = "0769980001"   # gérant A — parcours principal
_PHONE_B_LOCAL = "0769980002"   # gérant B — isolation inter-salons
_PHONE_CLIENT_LOCAL = "0769980003"   # client — résolution client_name
_PASSWORD = "discrepancies-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-discrepancies-a"
_SALON_NAME_B = "e2e-salon-discrepancies-b"

_SERVICE_PRICE = "5000.00"
_CLIENT_NAME = "Client E2E Écarts"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK.

    Ordre : payments → cash_journal → appointment_services → appointments →
    audit_logs → services → salon_members → salons → users. Toutes les données
    sont rattachées à un salon dont le propriétaire porte le préfixe réservé.
    """
    engine = get_engine()
    salons_of_prefix = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}
    with engine.connect() as conn:
        conn.execute(
            text(f"DELETE FROM payments WHERE salon_id IN ({salons_of_prefix})"), params
        )
        conn.execute(
            text(f"DELETE FROM cash_journal WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM appointment_services WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM appointments WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
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
            text("DELETE FROM users WHERE phone LIKE :prefix"), params
        )
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT) ; skip sans `DATABASE_URL`."""
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e des écarts de caisse.")

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


# ─── Helpers API ──────────────────────────────────────────────────────────────


def _register_manager(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Écarts", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client(client: TestClient, *, phone: str = _PHONE_CLIENT_LOCAL) -> str:
    resp = client.post(
        "/auth/register",
        json={"full_name": _CLIENT_NAME, "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str = _SALON_NAME_A) -> str:
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(
    client: TestClient, token: str, salon_id: str, *, price: str = _SERVICE_PRICE
) -> str:
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": "Coupe homme", "price": price, "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


# ─── Helpers SQL (insertion directe — bypass des gardes HTTP) ─────────────────


def _insert_appointment(
    *,
    salon_id: str,
    client_id: str,
    appointment_date: datetime.date,
    start_time: str = "09:00",
    end_time: str = "10:00",
    status: str = "COMPLETED",
) -> str:
    """Insère un RDV directement en base pour contrôler son statut.

    `slot` est une colonne générée (COMPUTED) — pas d'insertion manuelle.
    `hairdresser_id` est laissé NULL (non pertinent pour la détection d'écart).
    """
    appt_id = str(uuid.uuid4())
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO appointments "
                "(id, salon_id, client_id, appointment_date, start_time, end_time, status) "
                "VALUES (:id, :salon_id, :client_id, :date, :start, :end, :status)"
            ),
            {
                "id": appt_id,
                "salon_id": salon_id,
                "client_id": client_id,
                "date": appointment_date,
                "start": start_time,
                "end": end_time,
                "status": status,
            },
        )
        conn.commit()
    return appt_id


def _insert_appointment_service(
    *, salon_id: str, appointment_id: str, service_id: str, price: str
) -> None:
    """Rattache une prestation (prix figé `price_at_booking`) à un RDV."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO appointment_services "
                "(appointment_id, service_id, salon_id, price_at_booking) "
                "VALUES (:appt, :service, :salon, :price)"
            ),
            {
                "appt": appointment_id,
                "service": service_id,
                "salon": salon_id,
                "price": decimal.Decimal(price),
            },
        )
        conn.commit()


def _insert_payment(
    *,
    salon_id: str,
    appointment_id: str,
    recorded_by: str,
    amount: str = _SERVICE_PRICE,
    status: str = "VALIDATED",
    payment_method: str = "CASH",
) -> str:
    """Insère un paiement rattaché à un RDV avec un statut choisi (VALIDATED/ADJUSTED/…)."""
    payment_id = str(uuid.uuid4())
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO payments "
                "(id, salon_id, appointment_id, amount, currency, payment_method, "
                "status, recorded_by, receipt_number) "
                "VALUES (:id, :salon_id, :appt, :amount, 'XOF', :method, :status, :by, "
                "(SELECT COALESCE(MAX(receipt_number), 0) + 1 FROM payments "
                "WHERE salon_id = :salon_id))"
            ),
            {
                "id": payment_id,
                "salon_id": salon_id,
                "appt": appointment_id,
                "amount": decimal.Decimal(amount),
                "method": payment_method,
                "status": status,
                "by": recorded_by,
            },
        )
        conn.commit()
    return payment_id


def _url(salon_id: str) -> str:
    return f"/salons/{salon_id}/cash-discrepancies"


def _list_discrepancies(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    resp = client.get(
        _url(salon_id),
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Liste des écarts échouée : {resp.text}"
    return resp.json()


# ─── Décor commun (gérant A + salon A + prestation + client) ──────────────────


def _setup_salon_a(client: TestClient) -> tuple[str, str, str, str]:
    """Monte gérant A, salon A, une prestation et un client. Retourne (token, salon, service, client)."""
    manager_id = _register_manager(client)
    client_id = _register_client(client)
    token = _login(client)
    salon_id = _create_salon(client, token)
    service_id = _create_service(client, token, salon_id)
    return token, salon_id, service_id, client_id, manager_id  # type: ignore[return-value]


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCashDiscrepanciesE2E:
    """`GET /salons/{id}/cash-discrepancies` bout-en-bout : rapprochement SQL réel (§11.2, #36)."""

    _DATE = datetime.date(2026, 6, 15)

    # ── Cœur du critère #36 : RDV terminé sans paiement ──────────────────────

    def test_completed_without_payment_is_flagged(self, _e2e_client: TestClient) -> None:
        """Un RDV `COMPLETED` sans paiement est signalé comme écart (critère #36)."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert len(page["items"]) == 1
        item = page["items"][0]
        assert item["appointment_id"] == appt_id
        assert item["expected_amount"] == _SERVICE_PRICE

    def test_completed_with_validated_payment_is_absent(self, _e2e_client: TestClient) -> None:
        """Un RDV `COMPLETED` couvert par un paiement `VALIDATED` n'est pas un écart."""
        token, salon_id, service_id, client_id, manager_id = _setup_salon_a(_e2e_client)
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
        )
        _insert_payment(
            salon_id=salon_id, appointment_id=appt_id, recorded_by=manager_id, status="VALIDATED"
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 0
        assert page["items"] == []

    def test_completed_with_adjusted_payment_is_absent(self, _e2e_client: TestClient) -> None:
        """Un RDV `COMPLETED` dont le paiement a été corrigé (`ADJUSTED`) reste couvert."""
        token, salon_id, service_id, client_id, manager_id = _setup_salon_a(_e2e_client)
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
        )
        _insert_payment(
            salon_id=salon_id, appointment_id=appt_id, recorded_by=manager_id, status="ADJUSTED"
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 0

    def test_completed_with_only_cancelled_payment_is_flagged(self, _e2e_client: TestClient) -> None:
        """Un RDV `COMPLETED` dont le seul paiement est `CANCELLED` est un écart (non encaissé)."""
        token, salon_id, service_id, client_id, manager_id = _setup_salon_a(_e2e_client)
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
        )
        _insert_payment(
            salon_id=salon_id, appointment_id=appt_id, recorded_by=manager_id, status="CANCELLED"
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert page["items"][0]["appointment_id"] == appt_id

    # ── Statuts de RDV : seul COMPLETED compte ───────────────────────────────

    @pytest.mark.parametrize("status", ["PENDING", "CONFIRMED", "CANCELLED", "NO_SHOW"])
    def test_non_completed_status_never_flagged(
        self, _e2e_client: TestClient, status: str
    ) -> None:
        """Un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` n'est jamais un écart."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE, status=status
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 0

    # ── Montant attendu : somme des price_at_booking ─────────────────────────

    def test_expected_amount_sums_multiple_services(self, _e2e_client: TestClient) -> None:
        """`expected_amount` est la somme des `price_at_booking` des lignes du RDV."""
        token, salon_id, _, client_id, _ = _setup_salon_a(_e2e_client)
        service_one = _create_service(_e2e_client, token, salon_id, price="2000.00")
        service_two = _create_service(_e2e_client, token, salon_id, price="3500.00")
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_one, price="2000.00"
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_two, price="3500.00"
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert page["items"][0]["expected_amount"] == "5500.00"

    # ── Résolution du client_name (jointure users, §11.3) ────────────────────

    def test_client_name_resolved_via_join(self, _e2e_client: TestClient) -> None:
        """`client_name` reflète `users.full_name` via la jointure."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["items"][0]["client_name"] == _CLIENT_NAME

    # ── Isolation inter-salons (§11.2) ───────────────────────────────────────

    def test_other_salon_discrepancy_absent(self, _e2e_client: TestClient) -> None:
        """Un RDV `COMPLETED` non payé du salon B n'apparaît jamais dans le salon A."""
        token_a, salon_a_id, _, client_id, _ = _setup_salon_a(_e2e_client)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id)
        appt_b_id = _insert_appointment(
            salon_id=salon_b_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_b_id, appointment_id=appt_b_id, service_id=service_b_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token_a, salon_a_id)
        assert page["total"] == 0

    def test_payment_in_same_salon_only_covers_appointment(self, _e2e_client: TestClient) -> None:
        """Le rapprochement `NOT EXISTS` est salon-scopé : le paiement porte le bon `salon_id`.

        Un RDV du salon A payé (VALIDATED) est couvert ; un RDV du salon A **non** payé
        reste un écart — les deux dans la même liste salon-scopée.
        """
        token, salon_id, service_id, client_id, manager_id = _setup_salon_a(_e2e_client)
        paid_appt = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE, start_time="09:00", end_time="10:00"
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=paid_appt, service_id=service_id, price=_SERVICE_PRICE
        )
        _insert_payment(
            salon_id=salon_id, appointment_id=paid_appt, recorded_by=manager_id, status="VALIDATED"
        )
        unpaid_appt = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE, start_time="11:00", end_time="12:00"
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=unpaid_appt, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert page["items"][0]["appointment_id"] == unpaid_appt

    # ── Filtre de dates (bornes inclusives sur appointment_date) ─────────────

    def test_date_from_excludes_older(self, _e2e_client: TestClient) -> None:
        """`date_from` exclut les RDV antérieurs à la borne."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        old_appt = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=datetime.date(2026, 6, 1)
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=old_appt, service_id=service_id, price=_SERVICE_PRICE
        )
        new_appt = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=datetime.date(2026, 6, 30)
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=new_appt, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token, salon_id, date_from="2026-06-15")
        assert page["total"] == 1
        assert page["items"][0]["appointment_id"] == new_appt

    def test_date_to_excludes_newer(self, _e2e_client: TestClient) -> None:
        """`date_to` exclut les RDV postérieurs à la borne."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        old_appt = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=datetime.date(2026, 6, 1)
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=old_appt, service_id=service_id, price=_SERVICE_PRICE
        )
        new_appt = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=datetime.date(2026, 6, 30)
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=new_appt, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token, salon_id, date_to="2026-06-15")
        assert page["total"] == 1
        assert page["items"][0]["appointment_id"] == old_appt

    def test_date_bounds_are_inclusive(self, _e2e_client: TestClient) -> None:
        """Un RDV exactement sur la borne est inclus (bornes inclusives des deux côtés)."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        appt_id = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=self._DATE
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(
            _e2e_client, token, salon_id, date_from="2026-06-15", date_to="2026-06-15"
        )
        assert page["total"] == 1

    # ── Tri (appointment_date DESC, start_time DESC) ─────────────────────────

    def test_orders_most_recent_first(self, _e2e_client: TestClient) -> None:
        """Les écarts sont triés du plus récent au plus ancien (`appointment_date DESC`)."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        older = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=datetime.date(2026, 6, 10)
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=older, service_id=service_id, price=_SERVICE_PRICE
        )
        newer = _insert_appointment(
            salon_id=salon_id, client_id=client_id, appointment_date=datetime.date(2026, 6, 20)
        )
        _insert_appointment_service(
            salon_id=salon_id, appointment_id=newer, service_id=service_id, price=_SERVICE_PRICE
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        ids = [item["appointment_id"] for item in page["items"]]
        assert ids.index(newer) < ids.index(older)

    # ── Pagination (limit/offset/total sous le même filtre) ──────────────────

    def test_pagination_total_reflects_all_matches(self, _e2e_client: TestClient) -> None:
        """`total` compte tous les écarts du filtre, indépendamment de `limit`."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        for day in (10, 11, 12):
            appt_id = _insert_appointment(
                salon_id=salon_id,
                client_id=client_id,
                appointment_date=datetime.date(2026, 6, day),
            )
            _insert_appointment_service(
                salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
            )

        page = _list_discrepancies(_e2e_client, token, salon_id, limit=1, offset=0)
        assert page["total"] == 3
        assert len(page["items"]) == 1

    def test_pagination_offset_skips_items(self, _e2e_client: TestClient) -> None:
        """`offset` avance dans la page sans changer `total` (tri plus-récent-d'abord)."""
        token, salon_id, service_id, client_id, _ = _setup_salon_a(_e2e_client)
        appt_ids = []
        for day in (10, 11, 12):
            appt_id = _insert_appointment(
                salon_id=salon_id,
                client_id=client_id,
                appointment_date=datetime.date(2026, 6, day),
            )
            _insert_appointment_service(
                salon_id=salon_id, appointment_id=appt_id, service_id=service_id, price=_SERVICE_PRICE
            )
            appt_ids.append(appt_id)

        page_first = _list_discrepancies(_e2e_client, token, salon_id, limit=1, offset=0)
        page_second = _list_discrepancies(_e2e_client, token, salon_id, limit=1, offset=1)
        assert page_first["items"][0]["appointment_id"] != page_second["items"][0]["appointment_id"]
        # Le plus récent (dernier jour) arrive en premier ; offset=0 → 2026-06-12.
        assert page_first["items"][0]["appointment_id"] == appt_ids[-1]

    # ── Sécurité (pile complète) ─────────────────────────────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        token, salon_id, _, _, _ = _setup_salon_a(_e2e_client)
        resp = _e2e_client.get(_url(salon_id))
        assert resp.status_code == 401

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Le jeton du gérant A est refusé pour lister les écarts du salon B (§11.2)."""
        token_a, _, _, _, _ = _setup_salon_a(_e2e_client)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.get(
            _url(salon_b_id),
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403
