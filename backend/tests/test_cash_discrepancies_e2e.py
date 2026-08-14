"""Tests e2e pour US-5.4 — détection des écarts de caisse (#36).

Groupe `TestCashDiscrepanciesE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlPaymentRepository.list_completed_without_payment`
    / `count_completed_without_payment` — la requête `NOT EXISTS` sur
    `payments.queue_ticket_id`, le `LEFT JOIN queue_ticket_services → services` pour le
    **montant attendu** (résolution en direct, aucun prix figé côté ticket), la
    résolution `customer_profiles.full_name`, les bornes de dates sur `issued_date`,
    l'isolation `salon_id`, le tri et la pagination. Aucune suite unitaire/API
    (adossées à `FakePaymentRepository`) ne couvre ce SQL : c'est le seul code qui
    satisfait réellement le critère d'acceptation #36 *« un ticket walk-in terminé
    sans paiement est signalé comme écart »*.

Scénarios (miroir de la spec RDV d'origine, `specs/detection-ecarts-de-caisse.md`,
adapté au pivot walk-in exclusif) :
    - ticket `done` **sans** paiement → **signalé**, `expected_amount` correct ;
    - ticket `done` **avec** paiement `VALIDATED` → **absent** ;
    - ticket `done` dont le paiement est `ADJUSTED` (corrigé) → **absent** ;
    - ticket `done` dont le seul paiement est `CANCELLED` → **signalé** ;
    - ticket `waiting`/`called`/`in_progress`/`expired` → **jamais** signalé ;
    - isolation §11.2 : ticket d'un autre salon absent ; un paiement d'un autre salon
      ne couvre jamais un ticket ;
    - `expected_amount` = somme des `Service.price` **actuels** (plusieurs lignes) ;
    - résolution `client_name` = `customer_profiles.full_name` ;
    - bornes de dates `date_from`/`date_to` inclusives ; hors plage → exclu ;
    - pagination (`limit`/`offset`/`total`) et tri `issued_date DESC, ticket_number DESC` ;
    - `401` sans jeton, `403` inter-salons (pile complète).

Les tickets, lignes de prestation et paiements sont insérés **directement en base**
(bypass des gardes HTTP) pour contrôler statuts et l'absence/présence de paiement —
ce que les API de la borne/de l'encaissement ne permettent pas.

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
_PASSWORD = "discrepancies-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-discrepancies-a"
_SALON_NAME_B = "e2e-salon-discrepancies-b"

_SERVICE_PRICE = "5000.00"
_CUSTOMER_NAME = "Client E2E Écarts"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK.

    Ordre : payments → cash_journal → queue_ticket_services → queue_tickets →
    customer_profiles → audit_logs → services → salon_members → salons → users.
    Toutes les données sont rattachées à un salon dont le propriétaire porte le
    préfixe réservé.
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
                f"DELETE FROM queue_ticket_services WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM queue_tickets WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(f"DELETE FROM customer_profiles WHERE salon_id IN ({salons_of_prefix})"),
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


def _insert_customer_profile(*, salon_id: str, full_name: str = _CUSTOMER_NAME) -> str:
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


def _insert_queue_ticket(
    *,
    salon_id: str,
    customer_profile_id: str | None,
    issued_date: datetime.date,
    ticket_number: int,
    status: str = "done",
) -> str:
    """Insère un ticket de passage directement en base pour contrôler son statut."""
    ticket_id = str(uuid.uuid4())
    completed_at = (
        datetime.datetime.now(datetime.timezone.utc) if status == "done" else None
    )
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO queue_tickets "
                "(id, salon_id, customer_profile_id, issued_date, ticket_number, "
                "status, estimated_wait_minutes, completed_at) "
                "VALUES (:id, :salon_id, :customer, :date, :number, :status, 0, "
                ":completed_at)"
            ),
            {
                "id": ticket_id,
                "salon_id": salon_id,
                "customer": customer_profile_id,
                "date": issued_date,
                "number": ticket_number,
                "status": status,
                "completed_at": completed_at,
            },
        )
        conn.commit()
    return ticket_id


def _insert_queue_ticket_service(
    *, salon_id: str, queue_ticket_id: str, service_id: str
) -> None:
    """Rattache une prestation à un ticket (aucun prix figé — résolution en direct)."""
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


def _insert_payment(
    *,
    salon_id: str,
    queue_ticket_id: str,
    recorded_by: str,
    amount: str = _SERVICE_PRICE,
    status: str = "VALIDATED",
    payment_method: str = "CASH",
) -> str:
    """Insère un paiement rattaché à un ticket avec un statut choisi (VALIDATED/ADJUSTED/…)."""
    payment_id = str(uuid.uuid4())
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO payments "
                "(id, salon_id, queue_ticket_id, amount, currency, payment_method, "
                "status, recorded_by, receipt_number) "
                "VALUES (:id, :salon_id, :ticket, :amount, 'XOF', :method, :status, :by, "
                "(SELECT COALESCE(MAX(receipt_number), 0) + 1 FROM payments "
                "WHERE salon_id = :salon_id))"
            ),
            {
                "id": payment_id,
                "salon_id": salon_id,
                "ticket": queue_ticket_id,
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


# ─── Décor commun (gérant A + salon A + prestation + fiche client) ────────────


def _setup_salon_a(client: TestClient) -> tuple[str, str, str, str, str]:
    """Monte gérant A, salon A, une prestation et une fiche client walk-in.

    Retourne (token, salon_id, service_id, customer_profile_id, manager_id).
    """
    manager_id = _register_manager(client)
    token = _login(client)
    salon_id = _create_salon(client, token)
    service_id = _create_service(client, token, salon_id)
    customer_profile_id = _insert_customer_profile(salon_id=salon_id)
    return token, salon_id, service_id, customer_profile_id, manager_id


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCashDiscrepanciesE2E:
    """`GET /salons/{id}/cash-discrepancies` bout-en-bout : rapprochement SQL réel (§11.2, #36)."""

    _DATE = datetime.date(2026, 6, 15)

    # ── Cœur du critère #36 : ticket terminé sans paiement ───────────────────

    def test_completed_without_payment_is_flagged(self, _e2e_client: TestClient) -> None:
        """Un ticket `done` sans paiement est signalé comme écart (critère #36)."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert len(page["items"]) == 1
        item = page["items"][0]
        assert item["queue_ticket_id"] == ticket_id
        assert item["expected_amount"] == _SERVICE_PRICE

    def test_completed_with_validated_payment_is_absent(self, _e2e_client: TestClient) -> None:
        """Un ticket `done` couvert par un paiement `VALIDATED` n'est pas un écart."""
        token, salon_id, service_id, customer_id, manager_id = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )
        _insert_payment(
            salon_id=salon_id, queue_ticket_id=ticket_id, recorded_by=manager_id, status="VALIDATED"
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 0
        assert page["items"] == []

    def test_completed_with_adjusted_payment_is_absent(self, _e2e_client: TestClient) -> None:
        """Un ticket `done` dont le paiement a été corrigé (`ADJUSTED`) reste couvert."""
        token, salon_id, service_id, customer_id, manager_id = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )
        _insert_payment(
            salon_id=salon_id, queue_ticket_id=ticket_id, recorded_by=manager_id, status="ADJUSTED"
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 0

    def test_completed_with_only_cancelled_payment_is_flagged(self, _e2e_client: TestClient) -> None:
        """Un ticket `done` dont le seul paiement est `CANCELLED` est un écart (non encaissé)."""
        token, salon_id, service_id, customer_id, manager_id = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )
        _insert_payment(
            salon_id=salon_id, queue_ticket_id=ticket_id, recorded_by=manager_id, status="CANCELLED"
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert page["items"][0]["queue_ticket_id"] == ticket_id

    # ── Statuts de ticket : seul `done` compte ────────────────────────────────

    @pytest.mark.parametrize("status", ["waiting", "called", "in_progress", "expired"])
    def test_non_done_status_never_flagged(
        self, _e2e_client: TestClient, status: str
    ) -> None:
        """Un ticket `waiting`/`called`/`in_progress`/`expired` n'est jamais un écart."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1, status=status,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 0

    # ── Montant attendu : somme des Service.price actuels ────────────────────

    def test_expected_amount_sums_multiple_services(self, _e2e_client: TestClient) -> None:
        """`expected_amount` est la somme des `Service.price` actuels des lignes du ticket."""
        token, salon_id, _, customer_id, _ = _setup_salon_a(_e2e_client)
        service_one = _create_service(_e2e_client, token, salon_id, price="2000.00")
        service_two = _create_service(_e2e_client, token, salon_id, price="3500.00")
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_one
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_two
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert page["items"][0]["expected_amount"] == "5500.00"

    # ── Résolution du client_name (jointure customer_profiles, §11.3) ────────

    def test_client_name_resolved_via_join(self, _e2e_client: TestClient) -> None:
        """`client_name` reflète `customer_profiles.full_name` via la jointure."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["items"][0]["client_name"] == _CUSTOMER_NAME

    def test_anonymous_ticket_has_null_client_name(self, _e2e_client: TestClient) -> None:
        """Un ticket anonyme (`customer_profile_id = NULL`) n'a pas de nom de client."""
        token, salon_id, service_id, _, _ = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=None,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert page["items"][0]["client_name"] is None
        assert page["items"][0]["customer_profile_id"] is None

    # ── Isolation inter-salons (§11.2) ───────────────────────────────────────

    def test_other_salon_discrepancy_absent(self, _e2e_client: TestClient) -> None:
        """Un ticket `done` non payé du salon B n'apparaît jamais dans le salon A."""
        token_a, salon_a_id, _, customer_id, _ = _setup_salon_a(_e2e_client)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id)
        ticket_b_id = _insert_queue_ticket(
            salon_id=salon_b_id, customer_profile_id=None,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_b_id, queue_ticket_id=ticket_b_id, service_id=service_b_id
        )

        page = _list_discrepancies(_e2e_client, token_a, salon_a_id)
        assert page["total"] == 0

    def test_payment_in_same_salon_only_covers_ticket(self, _e2e_client: TestClient) -> None:
        """Le rapprochement `NOT EXISTS` est salon-scopé : le paiement porte le bon `salon_id`.

        Un ticket du salon A payé (VALIDATED) est couvert ; un ticket du salon A **non**
        payé reste un écart — les deux dans la même liste salon-scopée.
        """
        token, salon_id, service_id, customer_id, manager_id = _setup_salon_a(_e2e_client)
        paid_ticket = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=paid_ticket, service_id=service_id
        )
        _insert_payment(
            salon_id=salon_id, queue_ticket_id=paid_ticket, recorded_by=manager_id, status="VALIDATED"
        )
        unpaid_ticket = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=2,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=unpaid_ticket, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        assert page["total"] == 1
        assert page["items"][0]["queue_ticket_id"] == unpaid_ticket

    # ── Filtre de dates (bornes inclusives sur issued_date) ──────────────────

    def test_date_from_excludes_older(self, _e2e_client: TestClient) -> None:
        """`date_from` exclut les tickets antérieurs à la borne."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        old_ticket = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=datetime.date(2026, 6, 1), ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=old_ticket, service_id=service_id
        )
        new_ticket = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=datetime.date(2026, 6, 30), ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=new_ticket, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id, date_from="2026-06-15")
        assert page["total"] == 1
        assert page["items"][0]["queue_ticket_id"] == new_ticket

    def test_date_to_excludes_newer(self, _e2e_client: TestClient) -> None:
        """`date_to` exclut les tickets postérieurs à la borne."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        old_ticket = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=datetime.date(2026, 6, 1), ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=old_ticket, service_id=service_id
        )
        new_ticket = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=datetime.date(2026, 6, 30), ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=new_ticket, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id, date_to="2026-06-15")
        assert page["total"] == 1
        assert page["items"][0]["queue_ticket_id"] == old_ticket

    def test_date_bounds_are_inclusive(self, _e2e_client: TestClient) -> None:
        """Un ticket exactement sur la borne est inclus (bornes inclusives des deux côtés)."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        ticket_id = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=self._DATE, ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
        )

        page = _list_discrepancies(
            _e2e_client, token, salon_id, date_from="2026-06-15", date_to="2026-06-15"
        )
        assert page["total"] == 1

    # ── Tri (issued_date DESC, ticket_number DESC) ───────────────────────────

    def test_orders_most_recent_first(self, _e2e_client: TestClient) -> None:
        """Les écarts sont triés du plus récent au plus ancien (`issued_date DESC`)."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        older = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=datetime.date(2026, 6, 10), ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=older, service_id=service_id
        )
        newer = _insert_queue_ticket(
            salon_id=salon_id, customer_profile_id=customer_id,
            issued_date=datetime.date(2026, 6, 20), ticket_number=1,
        )
        _insert_queue_ticket_service(
            salon_id=salon_id, queue_ticket_id=newer, service_id=service_id
        )

        page = _list_discrepancies(_e2e_client, token, salon_id)
        ids = [item["queue_ticket_id"] for item in page["items"]]
        assert ids.index(newer) < ids.index(older)

    # ── Pagination (limit/offset/total sous le même filtre) ──────────────────

    def test_pagination_total_reflects_all_matches(self, _e2e_client: TestClient) -> None:
        """`total` compte tous les écarts du filtre, indépendamment de `limit`."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        for day in (10, 11, 12):
            ticket_id = _insert_queue_ticket(
                salon_id=salon_id,
                customer_profile_id=customer_id,
                issued_date=datetime.date(2026, 6, day),
                ticket_number=day,
            )
            _insert_queue_ticket_service(
                salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
            )

        page = _list_discrepancies(_e2e_client, token, salon_id, limit=1, offset=0)
        assert page["total"] == 3
        assert len(page["items"]) == 1

    def test_pagination_offset_skips_items(self, _e2e_client: TestClient) -> None:
        """`offset` avance dans la page sans changer `total` (tri plus-récent-d'abord)."""
        token, salon_id, service_id, customer_id, _ = _setup_salon_a(_e2e_client)
        ticket_ids = []
        for day in (10, 11, 12):
            ticket_id = _insert_queue_ticket(
                salon_id=salon_id,
                customer_profile_id=customer_id,
                issued_date=datetime.date(2026, 6, day),
                ticket_number=day,
            )
            _insert_queue_ticket_service(
                salon_id=salon_id, queue_ticket_id=ticket_id, service_id=service_id
            )
            ticket_ids.append(ticket_id)

        page_first = _list_discrepancies(_e2e_client, token, salon_id, limit=1, offset=0)
        page_second = _list_discrepancies(_e2e_client, token, salon_id, limit=1, offset=1)
        assert page_first["items"][0]["queue_ticket_id"] != page_second["items"][0]["queue_ticket_id"]
        # Le plus récent (dernier jour) arrive en premier ; offset=0 → 2026-06-12.
        assert page_first["items"][0]["queue_ticket_id"] == ticket_ids[-1]

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
