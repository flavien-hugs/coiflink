"""Tests e2e pour US-5.1/5.2 — enregistrement d'un paiement (#33) et historique
des transactions filtrable (#35), socle de #34.

Groupe TestRecordPaymentE2E (PostgreSQL requis) :
    pile complète : HTTP (TestClient) → router → cas d'usage → dépôts SQL réels
    (paiement, journal de caisse, prestation) + journal d'audit réel + JWT réel.

Scénarios (spec `specs/*.md`, cf. finding de revue automatisée sur la PR #111) :
    1. Montant cohérent (= prix de la prestation active liée) → `201` + **une**
       ligne `PAYMENT` au journal de caisse + une entrée d'audit
       `PAYMENT_RECORDED` **neutre** (metadata vide, aucune PII).
    2. Montant incohérent → `422`, **aucune** trace (ni `payments`, ni
       `cash_journal`, ni `audit_logs`) — atomicité §8.2/§11.4.
    3. Isolation inter-salons (§11.2) : le jeton du gérant A est refusé sur le
       salon du gérant B (`403` générique) ; référencer une prestation du salon B
       depuis le salon A est indiscernable d'une référence inexistante (`422`
       `PaymentReferenceNotFound`, aucun oracle).
    4. Deny-by-default : accès sans jeton → `401`.

Groupe TestListTransactionsE2E (PostgreSQL requis, US-5.2, #35) :
    exerce `SqlPaymentRepository.list_for_salon`/`count_for_salon` — chemin SQL
    réel (jointure `users.full_name`, clauses `WHERE` cumulées, tri, pagination)
    qu'aucune suite unitaire/API (adossées à `FakePaymentRepository`) ne couvre.
    Scénarios : isolation inter-salons, tri plus-récent-d'abord, filtres
    (mode/montant), résolution du `client_name` par jointure, pagination
    (`limit`/`offset`/`total` sous le même filtre), cohérence avec la ligne
    `PAYMENT` du journal de caisse (#34) ; recherche texte `q` sur le nom client
    (#40) : échappement `LIKE` d'un `%` littéral, `count_for_salon` cohérent avec
    `list_for_salon` sous jointure `users` (régression du COUNT), exclusion d'un
    paiement walk-in (`client_id=None`, aucun nom à comparer).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_payments_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225075999xxxx).
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

from coiflink_api.adapters.outbound.persistence.payment_repository import (
    SqlPaymentRepository,
)
from coiflink_api.adapters.outbound.persistence.session import (
    get_engine,
    get_sessionmaker,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.domain.transaction import validate_transaction_filter
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-payments-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des paiements.
_E2E_PHONE_PREFIX = "+225075999"
_PHONE_A_LOCAL = "0759990001"   # gérant A — parcours principal
_PHONE_B_LOCAL = "0759990002"   # gérant B — isolation inter-salons
_PHONE_CLIENT_LOCAL = "0759990003"   # client — résolution client_name (US-5.2)
_PHONE_CLIENT_Q_MATCH_LOCAL = "0759990004"  # client au nom portant un "%" littéral (#40)
_PHONE_CLIENT_Q_OTHER_LOCAL = "0759990005"  # client au nom proche, sans "%" (contrôle négatif, #40)
_PASSWORD = "payments-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-payments-a"
_SALON_NAME_B = "e2e-salon-payments-b"

_SERVICE_PRICE = "5000.00"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → cash_journal → payments → services → salon_members →
    salons → users.
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
    - Supprime les données de test (plage +225075999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e des paiements.")

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


def _register_manager(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    """Inscrit un compte gérant via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Paiements", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription échouée : {resp.text}"
    return resp.json()["id"]


def _register_client(client: TestClient, *, phone: str = _PHONE_CLIENT_LOCAL) -> str:
    """Inscrit un compte client via l'API et retourne son UUID (résolution `client_name`)."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E Paiements", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _register_named_client(client: TestClient, *, phone: str, full_name: str) -> str:
    """Inscrit un compte client avec un `full_name` **personnalisé** (filtre `q`, #40)."""
    resp = client.post(
        "/auth/register",
        json={"full_name": full_name, "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post(
        "/auth/login", json={"identifier": phone, "password": _PASSWORD}
    )
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str = _SALON_NAME_A) -> str:
    """Crée un salon via l'API et retourne son UUID."""
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
    """Crée une prestation active via l'API et retourne son UUID."""
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": "Coupe homme", "price": price, "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _payments_url(salon_id: str) -> str:
    return f"/salons/{salon_id}/payments"


def _list_transactions(
    client: TestClient, token: str, salon_id: str, **params: object
) -> dict:
    """`GET /salons/{id}/payments` (historique filtrable, US-5.2, #35)."""
    resp = client.get(
        _payments_url(salon_id),
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Liste des transactions échouée : {resp.text}"
    return resp.json()


def _count_audit_entries(payment_id: str, action: str | None = None) -> int:
    """Compte les entrées d'audit `audit_logs` pour un paiement donné."""
    engine = get_engine()
    with engine.connect() as conn:
        if action:
            result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_logs "
                    "WHERE entity_type = 'payment' AND entity_id = :eid AND action = :action"
                ),
                {"eid": payment_id, "action": action},
            )
        else:
            result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_logs "
                    "WHERE entity_type = 'payment' AND entity_id = :eid"
                ),
                {"eid": payment_id},
            )
        return result.scalar_one()


def _fetch_audit_entries(payment_id: str) -> list[dict]:
    """Récupère toutes les entrées d'audit pour un paiement, en ordre chronologique."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT action, actor_user_id, salon_id, entity_type, entity_id, "
                "metadata FROM audit_logs "
                "WHERE entity_type = 'payment' AND entity_id = :eid "
                "ORDER BY created_at"
            ),
            {"eid": payment_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _count_payments(salon_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM payments WHERE salon_id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


def _count_cash_journal_entries(salon_id: str, operation_type: str | None = None) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        if operation_type:
            return conn.execute(
                text(
                    "SELECT COUNT(*) FROM cash_journal "
                    "WHERE salon_id = :sid AND operation_type = :op"
                ),
                {"sid": salon_id, "op": operation_type},
            ).scalar_one()
        return conn.execute(
            text("SELECT COUNT(*) FROM cash_journal WHERE salon_id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


def _fetch_cash_journal_entry(salon_id: str, payment_id: str) -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT operation_type, amount, performed_by, transaction_id "
                "FROM cash_journal WHERE salon_id = :sid AND transaction_id = :tid"
            ),
            {"sid": salon_id, "tid": payment_id},
        ).fetchone()
    assert row is not None, "Aucune ligne de journal pour ce paiement."
    return dict(row._mapping)


def _count_audit_entries_for_salon(salon_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM audit_logs WHERE salon_id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestRecordPaymentE2E:
    """Enregistrement d'un paiement bout-en-bout : HTTP → cas d'usage → SQL réel + audit réel."""

    # ── Parcours 1 : montant cohérent (§5.3/§8.2, cœur de #33) ────────────────

    def test_coherent_amount_returns_201(self, _e2e_client: TestClient) -> None:
        """Montant = prix de la prestation active liée → 201."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    def test_coherent_amount_creates_one_payment_journal_line(
        self, _e2e_client: TestClient
    ) -> None:
        """Le paiement validé inscrit exactement une ligne `PAYMENT` au journal."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        payment_id = resp.json()["id"]

        assert _count_cash_journal_entries(salon_id, "PAYMENT") == 1
        entry = _fetch_cash_journal_entry(salon_id, payment_id)
        assert entry["operation_type"] == "PAYMENT"
        assert str(entry["transaction_id"]) == payment_id

    def test_coherent_amount_records_payment_recorded_audit_entry(
        self, _e2e_client: TestClient
    ) -> None:
        """La création enregistre une entrée `PAYMENT_RECORDED` dans `audit_logs`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        payment_id = resp.json()["id"]
        assert _count_audit_entries(payment_id, "PAYMENT_RECORDED") == 1

    def test_payment_audit_entry_metadata_is_empty(self, _e2e_client: TestClient) -> None:
        """`metadata` de l'entrée d'audit est vide — ni montant, ni mode, ni client (§11.3)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        payment_id = resp.json()["id"]

        entries = _fetch_audit_entries(payment_id)
        assert len(entries) == 1
        assert entries[0]["metadata"] == {}

    def test_payment_audit_entry_actor_matches_manager(
        self, _e2e_client: TestClient
    ) -> None:
        """L'`actor_user_id` de l'entrée d'audit correspond au gérant authentifié."""
        manager_id = _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        payment_id = resp.json()["id"]

        entries = _fetch_audit_entries(payment_id)
        assert str(entries[0]["actor_user_id"]) == manager_id

    def test_response_recorded_by_matches_manager(self, _e2e_client: TestClient) -> None:
        """`recorded_by` de la réponse correspond au gérant authentifié, jamais au corps."""
        manager_id = _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
                # Champ privilégié : doit être ignoré (extra="ignore").
                "recorded_by": "00000000-0000-0000-0000-000000000000",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["recorded_by"] == manager_id

    def test_response_contains_no_token(self, _e2e_client: TestClient) -> None:
        """La réponse de création ne révèle pas le jeton d'accès (PRD §11.1)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert token not in resp.text

    # ── Parcours 2 : montant incohérent — aucune trace (atomicité §8.2/§11.4) ─

    def test_incoherent_amount_returns_422(self, _e2e_client: TestClient) -> None:
        """Montant ≠ prix de la prestation liée → 422 (cœur de #33)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": "4999.00",
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_incoherent_amount_leaves_no_payment_row(self, _e2e_client: TestClient) -> None:
        """Un montant incohérent ne crée aucune ligne `payments` (rejeté avant écriture)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": "4999.00",
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert _count_payments(salon_id) == 0

    def test_incoherent_amount_leaves_no_cash_journal_row(
        self, _e2e_client: TestClient
    ) -> None:
        """Un montant incohérent ne crée aucune ligne au journal de caisse."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": "4999.00",
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert _count_cash_journal_entries(salon_id) == 0

    def test_incoherent_amount_leaves_no_audit_entry(self, _e2e_client: TestClient) -> None:
        """Un montant incohérent ne crée aucune entrée d'audit (atomicité §11.4).

        La création de la prestation (`SERVICE_CREATED`) journalise déjà une
        entrée sur ce salon : on compare un **delta**, pas un total absolu.
        """
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)
        baseline = _count_audit_entries_for_salon(salon_id)

        _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": "4999.00",
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert _count_audit_entries_for_salon(salon_id) == baseline

    def test_incoherent_amount_error_does_not_reveal_expected_price(
        self, _e2e_client: TestClient
    ) -> None:
        """Le message d'erreur ne reprend jamais le prix attendu ni le montant saisi (§11.3)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": "4999.00",
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert _SERVICE_PRICE not in resp.text
        assert "4999" not in resp.text

    # ── Parcours 3 : isolation inter-salons (§11.2) ───────────────────────────

    def test_cross_salon_payment_recording_returns_403(
        self, _e2e_client: TestClient
    ) -> None:
        """Le jeton du gérant A est refusé pour encaisser sur le salon du gérant B."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id)

        resp = _e2e_client.post(
            _payments_url(salon_b_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_b_id,
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    def test_cross_salon_403_message_is_generic(self, _e2e_client: TestClient) -> None:
        """Le 403 inter-salons est générique — il ne révèle pas l'existence du salon B."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id)

        resp = _e2e_client.post(
            _payments_url(salon_b_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_b_id,
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.json()["detail"] == "Accès refusé."
        assert salon_b_id not in resp.text

    def test_cross_salon_service_reference_returns_422_not_404(
        self, _e2e_client: TestClient
    ) -> None:
        """Référencer, depuis le salon A, une prestation du salon B → 422 (sans oracle §11.2)."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id)

        resp = _e2e_client.post(
            _payments_url(salon_a_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                # Prestation du salon B, référencée dans la portée du salon A.
                "service_id": service_b_id,
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 422
        assert service_b_id not in resp.text

    def test_cross_salon_service_reference_leaves_no_payment_row(
        self, _e2e_client: TestClient
    ) -> None:
        """Une référence hors salon ne crée aucune ligne `payments` (rejetée avant écriture)."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id)

        _e2e_client.post(
            _payments_url(salon_a_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_b_id,
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert _count_payments(salon_a_id) == 0

    # ── Parcours 4 : deny-by-default (ADR-0015) ───────────────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """POST sans jeton → 401 (deny-by-default, ADR-0015)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
        )
        assert resp.status_code == 401


# ─── Groupe e2e : historique des transactions filtrable (PostgreSQL requis) ──


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestListTransactionsE2E:
    """`GET /salons/{id}/payments` bout-en-bout : jointure/filtres/tri/pagination SQL réels."""

    # ── Parcours 1 : isolation inter-salons (§11.2) ───────────────────────────

    def test_lists_only_this_salon_transactions(self, _e2e_client: TestClient) -> None:
        """Un paiement du salon B n'apparaît jamais dans l'historique du salon A."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id)
        _e2e_client.post(
            _payments_url(salon_b_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_b_id,
            },
            headers={"Authorization": f"Bearer {token_b}"},
        )

        page = _list_transactions(_e2e_client, token_a, salon_a_id)
        assert page["items"] == []
        assert page["total"] == 0

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Le jeton du gérant A est refusé pour lister l'historique du salon B."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)

        resp = _e2e_client.get(
            _payments_url(salon_b_id),
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

    # ── Parcours 2 : tri plus-récent-d'abord ──────────────────────────────────

    def test_orders_most_recent_first(self, _e2e_client: TestClient) -> None:
        """Deux paiements successifs apparaissent triés du plus récent au plus ancien."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_first = _create_service(_e2e_client, token, salon_id, price="1000.00")
        service_second = _create_service(_e2e_client, token, salon_id, price="2000.00")

        resp_first = _e2e_client.post(
            _payments_url(salon_id),
            json={"amount": "1000.00", "payment_method": "CASH", "service_id": service_first},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp_second = _e2e_client.post(
            _payments_url(salon_id),
            json={"amount": "2000.00", "payment_method": "CASH", "service_id": service_second},
            headers={"Authorization": f"Bearer {token}"},
        )
        payment_first_id = resp_first.json()["id"]
        payment_second_id = resp_second.json()["id"]

        page = _list_transactions(_e2e_client, token, salon_id)
        ids = [item["id"] for item in page["items"]]
        assert ids.index(payment_second_id) < ids.index(payment_first_id)

    # ── Parcours 3 : filtres (mode, montant) ──────────────────────────────────

    def test_filter_by_payment_method(self, _e2e_client: TestClient) -> None:
        """`payment_method=CASH` n'affiche que les transactions en espèces."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_cash = _create_service(_e2e_client, token, salon_id, price="1000.00")
        service_card = _create_service(_e2e_client, token, salon_id, price="2000.00")

        _e2e_client.post(
            _payments_url(salon_id),
            json={"amount": "1000.00", "payment_method": "CASH", "service_id": service_cash},
            headers={"Authorization": f"Bearer {token}"},
        )
        _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": "2000.00",
                "payment_method": "CARD_MANUAL",
                "service_id": service_card,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        page = _list_transactions(_e2e_client, token, salon_id, payment_method="CASH")
        assert page["total"] == 1
        assert page["items"][0]["payment_method"] == "CASH"

    def test_filter_by_amount_range(self, _e2e_client: TestClient) -> None:
        """`amount_min`/`amount_max` restreignent la liste à la plage demandée."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_low = _create_service(_e2e_client, token, salon_id, price="1000.00")
        service_high = _create_service(_e2e_client, token, salon_id, price="9000.00")

        _e2e_client.post(
            _payments_url(salon_id),
            json={"amount": "1000.00", "payment_method": "CASH", "service_id": service_low},
            headers={"Authorization": f"Bearer {token}"},
        )
        _e2e_client.post(
            _payments_url(salon_id),
            json={"amount": "9000.00", "payment_method": "CASH", "service_id": service_high},
            headers={"Authorization": f"Bearer {token}"},
        )

        page = _list_transactions(
            _e2e_client, token, salon_id, amount_min="5000.00", amount_max="9500.00"
        )
        assert page["total"] == 1
        assert page["items"][0]["amount"] == "9000.00"

    # ── Parcours 4 : résolution du client_name (jointure users, §11.3) ───────

    def test_client_name_resolved_via_join(self, _e2e_client: TestClient) -> None:
        """`client_name` reflète `users.full_name` via la jointure (client_id fourni)."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        client_id = _register_client(_e2e_client)
        token = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
                "client_id": client_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        page = _list_transactions(_e2e_client, token, salon_id)
        assert page["items"][0]["client_name"] == "Client E2E Paiements"

    def test_walk_in_payment_has_null_client_name(self, _e2e_client: TestClient) -> None:
        """Un paiement sans `client_id` (walk-in) affiche `client_name: null`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        page = _list_transactions(_e2e_client, token, salon_id)
        assert page["items"][0]["client_name"] is None

    # ── Parcours 5 : pagination (limit/offset/total sous le même filtre) ─────

    def test_pagination_total_reflects_all_matches(self, _e2e_client: TestClient) -> None:
        """`total` compte toutes les transactions du filtre, indépendamment de `limit`."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        for price in ("1000.00", "2000.00", "3000.00"):
            service_id = _create_service(_e2e_client, token, salon_id, price=price)
            _e2e_client.post(
                _payments_url(salon_id),
                json={"amount": price, "payment_method": "CASH", "service_id": service_id},
                headers={"Authorization": f"Bearer {token}"},
            )

        page = _list_transactions(_e2e_client, token, salon_id, limit=1, offset=0)
        assert page["total"] == 3
        assert len(page["items"]) == 1

    def test_pagination_offset_skips_items(self, _e2e_client: TestClient) -> None:
        """`offset` avance dans la page sans changer `total` (tri plus-récent-d'abord)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        payment_ids = []
        for price in ("1000.00", "2000.00", "3000.00"):
            service_id = _create_service(_e2e_client, token, salon_id, price=price)
            resp = _e2e_client.post(
                _payments_url(salon_id),
                json={"amount": price, "payment_method": "CASH", "service_id": service_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            payment_ids.append(resp.json()["id"])

        page_first = _list_transactions(_e2e_client, token, salon_id, limit=1, offset=0)
        page_second = _list_transactions(_e2e_client, token, salon_id, limit=1, offset=1)
        assert page_first["items"][0]["id"] != page_second["items"][0]["id"]
        # Le plus récent (dernier créé) arrive en premier ; offset=0 → dernier payment.
        assert page_first["items"][0]["id"] == payment_ids[-1]

    # ── Parcours 6 : cohérence avec le journal de caisse (§8.2, #34) ──────────

    def test_transaction_amount_matches_cash_journal_line(
        self, _e2e_client: TestClient
    ) -> None:
        """Le montant listé correspond à la ligne `PAYMENT` du journal (même source)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        service_id = _create_service(_e2e_client, token, salon_id)

        resp = _e2e_client.post(
            _payments_url(salon_id),
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": service_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        payment_id = resp.json()["id"]

        page = _list_transactions(_e2e_client, token, salon_id)
        transaction = next(item for item in page["items"] if item["id"] == payment_id)
        journal_entry = _fetch_cash_journal_entry(salon_id, payment_id)

        assert decimal.Decimal(transaction["amount"]) == journal_entry["amount"]
        assert transaction["status"] == "VALIDATED"

    # ── Parcours 7 : recherche texte `q` — chemin SQL réel, jointure `users` (#40) ─

    def _setup_q_filter_payments(
        self, client: TestClient
    ) -> tuple[str, str, str, str, str]:
        """Monte gérant + salon + 3 paiements : client au nom "%", client proche, walk-in.

        Retourne `(token, salon_id, matching_payment_id, other_payment_id,
        walk_in_payment_id)`.
        """
        _register_manager(client)
        token = _login(client)
        salon_id = _create_salon(client, token)

        matching_client_id = _register_named_client(
            client, phone=_PHONE_CLIENT_Q_MATCH_LOCAL, full_name="Réduction 20% Camara"
        )
        other_client_id = _register_named_client(
            client, phone=_PHONE_CLIENT_Q_OTHER_LOCAL, full_name="Session 20 ans Camara"
        )

        service_matching = _create_service(client, token, salon_id, price="1000.00")
        service_other = _create_service(client, token, salon_id, price="2000.00")
        service_walk_in = _create_service(client, token, salon_id, price="3000.00")

        matching_payment_id = client.post(
            _payments_url(salon_id),
            json={
                "amount": "1000.00",
                "payment_method": "CASH",
                "service_id": service_matching,
                "client_id": matching_client_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        other_payment_id = client.post(
            _payments_url(salon_id),
            json={
                "amount": "2000.00",
                "payment_method": "CASH",
                "service_id": service_other,
                "client_id": other_client_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        # Paiement walk-in : aucun `client_id`, donc aucun nom à comparer sous `q`.
        walk_in_payment_id = client.post(
            _payments_url(salon_id),
            json={
                "amount": "3000.00",
                "payment_method": "CASH",
                "service_id": service_walk_in,
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]

        return token, salon_id, matching_payment_id, other_payment_id, walk_in_payment_id

    def test_q_filter_escapes_percent_literal_in_client_name(
        self, _e2e_client: TestClient
    ) -> None:
        """`q="20%"` ne matche que le nom contenant **littéralement** "20%" (échappement `LIKE`).

        Sans `escape_like`, `%` serait un joker : le motif `%20%%` équivaudrait à
        « contient 20 » et retournerait aussi « Session 20 ans Camara », qui ne
        porte pourtant pas le `%`.
        """
        token, salon_id, matching_payment_id, other_payment_id, _walk_in = (
            self._setup_q_filter_payments(_e2e_client)
        )

        page = _list_transactions(_e2e_client, token, salon_id, q="20%")

        ids = [item["id"] for item in page["items"]]
        assert ids == [matching_payment_id]
        assert other_payment_id not in ids
        assert page["items"][0]["client_name"] == "Réduction 20% Camara"

    def test_count_for_salon_with_q_matches_list_length(
        self, _e2e_client: TestClient
    ) -> None:
        """`count_for_salon` sous `q` égale `len(list_for_salon(...))` (régression jointure du COUNT, #40).

        Avant #40, `count_for_salon` ne joignait pas `users` : ajouter la clause `q`
        (qui référence `User.full_name`) sans étendre la jointure du COUNT ferait
        échouer la requête, ou — join mal posé — fausserait silencieusement le
        total. Appel **direct** du dépôt (nouvelle `Session`) pour isoler
        `SqlPaymentRepository` du routeur HTTP.
        """
        token, salon_id, matching_payment_id, other_payment_id, _walk_in = (
            self._setup_q_filter_payments(_e2e_client)
        )
        salon_uuid = uuid.UUID(salon_id)
        transaction_filter = validate_transaction_filter(q="Camara")

        session = get_sessionmaker()()
        try:
            repository = SqlPaymentRepository(session)
            results = repository.list_for_salon(
                salon_uuid, filter=transaction_filter, limit=50, offset=0
            )
            total = repository.count_for_salon(salon_uuid, filter=transaction_filter)
        finally:
            session.close()

        result_ids = {str(transaction.payment.id) for transaction in results}
        assert result_ids == {matching_payment_id, other_payment_id}
        assert total == len(results) == 2

    def test_payment_without_client_excluded_when_q_filter_set(
        self, _e2e_client: TestClient
    ) -> None:
        """Un paiement walk-in (`client_id=None`) n'a pas de nom à comparer → exclu sous `q`."""
        token, salon_id, matching_payment_id, other_payment_id, walk_in_payment_id = (
            self._setup_q_filter_payments(_e2e_client)
        )
        salon_uuid = uuid.UUID(salon_id)

        session = get_sessionmaker()()
        try:
            repository = SqlPaymentRepository(session)
            filtered = repository.list_for_salon(
                salon_uuid,
                filter=validate_transaction_filter(q="Camara"),
                limit=50,
                offset=0,
            )
            unfiltered_total = repository.count_for_salon(
                salon_uuid, filter=validate_transaction_filter()
            )
        finally:
            session.close()

        filtered_ids = {str(transaction.payment.id) for transaction in filtered}
        assert walk_in_payment_id not in filtered_ids
        assert filtered_ids == {matching_payment_id, other_payment_id}
        # Le total non filtré compte bien les 3 paiements, walk-in inclus.
        assert unfiltered_total == 3

    # ── Parcours 8 : deny-by-default (ADR-0015) ───────────────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        _register_manager(_e2e_client)
        token = _login(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        resp = _e2e_client.get(_payments_url(salon_id))
        assert resp.status_code == 401
