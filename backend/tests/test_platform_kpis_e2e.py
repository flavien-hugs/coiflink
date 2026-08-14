"""Tests e2e pour US-6.6 — KPI globaux de la plateforme (admin, #44).

Groupe `TestPlatformKpisE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlPlatformKpiRepository.compute_snapshot` —
    sept `SELECT` scalaires indépendants (`COUNT` sur `salons`/`users`/
    `queue_tickets`, `SUM` net signé sur `cash_journal`), filtrés par statut de
    salon, rôle utilisateur, bornes de mois civil (`issued_date`) et bornes
    UTC de mois (`cash_journal.created_at`). Aucune suite unitaire/API (adossée à
    un dépôt en mémoire) ne couvre ce SQL : c'est le seul code qui satisfait
    réellement le critère d'acceptation #44 *« dashboard admin avec KPI globaux
    agrégés »* (cf. finding de revue automatisée sur la PR #130).

**Assertions en delta.** `GET /admin/kpis` agrège **toute la plateforme** (pas
un salon scopé) : chaque test relève un instantané `before`, sème des données
isolées par préfixe téléphonique, relève `after`, puis compare les **deltas**
(`after - before`). Ce patron rend les tests robustes à une éventuelle activité
résiduelle d'autres suites e2e (chacune nettoie son propre préfixe dans
`finally`) sans supposer une base strictement vierge, sauf pour le scénario
« plateforme vide » qui vérifie explicitement l'absence de toute donnée au
moment précis de l'appel (miroir de l'exigence du plan de test de la spec).

Rebranché sur `queue_tickets` (pivot walk-in exclusif, #148) : les anciens RDV
insérés directement en base sont remplacés par des tickets walk-in.

Scénarios (spec `specs/kpi-globaux-plateforme-admin.md`, §Testing Plan
« Intégration SQL réelle ») :
    - `salons_total` compte **tous** les statuts, `salons_active` **seulement**
      `ACTIVE` ;
    - `clients_total` ne compte **que** les comptes `CLIENT` (exclut
      `MANAGER`/`HAIRDRESSER`/`ADMIN`) ;
    - `tickets_this_month` filtre aux **bornes inclusives** du mois civil
      (`issued_date`), un jour avant/après le mois est exclu ;
    - `tickets_total` compte **tous** les tickets, y compris `expired` ;
    - `revenue_total`/`revenue_this_month` = somme **signée** du journal de
      caisse (paiement + ajustement négatif = net), `revenue_this_month`
      exclut une opération d'un mois antérieur (bornes UTC) ;
    - plateforme sans salon/ticket/paiement → tous les compteurs à `0`, revenus
      `"0.00"` (état vide légitime, ≠ erreur) ;
    - `401` sans jeton, `403` pour un rôle autre qu'`ADMIN` ;
    - aucune PII (client, salon, jeton) dans la réponse agrégée.

Aucun endpoint d'inscription `ADMIN` n'existe (PRD §9.1) : le compte est créé
via l'inscription **client** puis promu `ADMIN` par une écriture SQL directe
(miroir `test_admin_transactions_e2e.py`, #37). Les tickets et l'opération de
caisse antérieure sont insérés **directement en base** (bypass des gardes HTTP
de la borne walk-in / contrôle du montant) pour fixer `issued_date` et
`created_at` sans dépendre du jour d'exécution du test.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_platform_kpis_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225070998xxxx).
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
from coiflink_api.domain.time_window import day_start_utc
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-platform-kpis-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des KPI globaux plateforme.
_E2E_PHONE_PREFIX = "+225070998"
_PASSWORD = "platform-kpis-e2e-strong-password-2024"

_KPIS_URL = "/admin/kpis"
_AMOUNT_QUANTUM = decimal.Decimal("0.01")


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → cash_journal → payments → queue_tickets →
    services → salon_members → salons → users.
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
                "DELETE FROM queue_tickets WHERE salon_id IN "
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
    - Supprime les données de test (plage +225070998) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e des KPI globaux plateforme.")

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

_phone_counter = 0


def _next_phone() -> str:
    """Génère un numéro local unique dans la plage réservée à ce fichier.

    Forme `070998NNNN` (10 chiffres) : les 6 premiers chiffres correspondent au
    préfixe `_E2E_PHONE_PREFIX` (`+225070998`), les 4 derniers incrémentent —
    garantit l'unicité et le nettoyage par `_wipe_test_data` (filtre `LIKE`).
    """
    global _phone_counter
    _phone_counter += 1
    return f"070998{_phone_counter:04d}"


def _register_manager(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte gérant via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E KPI Plateforme", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client_account(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte client via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E KPI Plateforme", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _register_and_promote_admin(client: TestClient, *, phone: str) -> str:
    """Inscrit un compte client puis le promeut `ADMIN` en base (aucun endpoint dédié).

    `Login` relit toujours `role` depuis la base : la promotion est effective
    dès la connexion suivante, sans mock ni fixture (miroir #37).
    """
    resp = client.post(
        "/auth/register",
        json={"full_name": "Admin E2E KPI Plateforme", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription admin échouée : {resp.text}"
    user_id = resp.json()["id"]

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET role = 'ADMIN' WHERE id = :uid"),
            {"uid": user_id},
        )
        conn.commit()
    return user_id


def _login(client: TestClient, *, phone: str) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str) -> str:
    """Crée un salon via l'API (statut `ACTIVE` par défaut) et retourne son UUID."""
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _add_hairdresser(client: TestClient, manager_token: str, salon_id: str, *, phone: str) -> str:
    """Inscrit un coiffeur et l'enregistre comme membre du salon (rôle `HAIRDRESSER`)."""
    resp = client.post(
        f"/salons/{salon_id}/employees",
        json={"full_name": "Coiffeur E2E KPI Plateforme", "phone": phone, "password": _PASSWORD},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Inscription coiffeur échouée : {resp.text}"
    return resp.json()["id"]


def _set_salon_status(salon_id: str, status: str) -> None:
    """Fixe le statut d'un salon par SQL direct (aucun endpoint HTTP de transition)."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE salons SET status = :status WHERE id = :sid"),
            {"status": status, "sid": salon_id},
        )
        conn.commit()


def _seed_ticket(
    salon_id: str, *, day: datetime.date, ticket_number: int = 1, status: str = "done"
) -> str:
    """Insère directement en base un ticket walk-in **anonyme** (jour/statut contrôlés).

    Bypass des gardes de la borne HTTP — seuls les compteurs globaux
    (`tickets_total`/`tickets_this_month`) sont testés ici, pas le parcours de
    prise de ticket. `customer_profile_id` reste `NULL` (nullable, ticket
    anonyme) : la lecture globale ne s'appuie que sur `issued_date`/`status`.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "INSERT INTO queue_tickets "
                "(salon_id, issued_date, ticket_number, status, estimated_wait_minutes) "
                "VALUES (:salon_id, :day, :number, :status, 0) "
                "RETURNING id"
            ),
            {
                "salon_id": salon_id,
                "day": day,
                "number": ticket_number,
                "status": status,
            },
        )
        ticket_id = row.scalar_one()
        conn.commit()
    return str(ticket_id)


def _create_service(client: TestClient, token: str, salon_id: str, *, price: str) -> str:
    """Crée une prestation active via l'API et retourne son UUID."""
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": "Coupe E2E KPI", "price": price, "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _record_payment(
    client: TestClient, token: str, salon_id: str, service_id: str, *, price: str
) -> str:
    """Enregistre un paiement `VALIDATED` (montant cohérent) et retourne son UUID."""
    resp = client.post(
        f"/salons/{salon_id}/payments",
        json={"amount": price, "payment_method": "CASH", "service_id": service_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Enregistrement paiement échoué : {resp.text}"
    return resp.json()["id"]


def _adjust_payment(
    client: TestClient, token: str, salon_id: str, payment_id: str, *, delta: str
) -> None:
    """Corrige un paiement (ligne `ADJUSTMENT`, delta signé) via l'API réelle."""
    resp = client.post(
        f"/salons/{salon_id}/payments/{payment_id}/adjustments",
        json={"amount": delta},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Correction paiement échouée : {resp.text}"


def _seed_past_cash_journal_payment(
    salon_id: str, performed_by: str, *, amount: str, created_at: datetime.datetime
) -> None:
    """Insère directement une ligne `cash_journal` `PAYMENT` datée dans le passé.

    Aucune API ne permet de contrôler `created_at` d'une ligne de caisse (horodatage
    serveur) : bypass ciblé pour prouver que `revenue_this_month` exclut une
    opération d'un mois antérieur tout en la comptant dans `revenue_total`.
    `transaction_id` reste `NULL` (nullable) : pas de paiement associé requis.
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO cash_journal "
                "(salon_id, transaction_id, operation_type, amount, performed_by, created_at) "
                "VALUES (:salon_id, NULL, 'PAYMENT', :amount, :performed_by, :created_at)"
            ),
            {
                "salon_id": salon_id,
                "amount": amount,
                "performed_by": performed_by,
                "created_at": created_at,
            },
        )
        conn.commit()


def _get_kpis(client: TestClient, token: str, **params: object) -> dict:
    """`GET /admin/kpis` (US-6.6, #44)."""
    resp = client.get(_KPIS_URL, params=params, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"KPI globaux échoués : {resp.text}"
    return resp.json()


def _dec(value: str) -> decimal.Decimal:
    return decimal.Decimal(value).quantize(_AMOUNT_QUANTUM)


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestPlatformKpisE2E:
    """`GET /admin/kpis` bout-en-bout : agrégats SQL réels (COUNT/SUM globaux)."""

    # ── Parcours 0 : plateforme vide ────────────────────────────────────────────

    def test_empty_platform_returns_zero_counters(self, _e2e_client: TestClient) -> None:
        """Sans salon/ticket/paiement, tous les compteurs valent `0` (état normal, ≠ erreur)."""
        admin_phone = _next_phone()
        admin_id = _register_and_promote_admin(_e2e_client, phone=admin_phone)
        assert admin_id
        admin_token = _login(_e2e_client, phone=admin_phone)

        kpis = _get_kpis(_e2e_client, admin_token)

        assert kpis["salons_total"] == 0
        assert kpis["salons_active"] == 0
        assert kpis["clients_total"] == 0
        assert kpis["tickets_total"] == 0
        assert kpis["tickets_this_month"] == 0
        assert _dec(kpis["revenue_total"]) == decimal.Decimal("0.00")
        assert _dec(kpis["revenue_this_month"]) == decimal.Decimal("0.00")

    # ── Parcours 1 : compteurs de salons (tous statuts vs actifs) ──────────────

    def test_salon_counters_reflect_all_statuses_vs_active(
        self, _e2e_client: TestClient
    ) -> None:
        """`salons_total` compte tous les statuts ; `salons_active` seulement `ACTIVE`."""
        admin_phone = _next_phone()
        admin_id = _register_and_promote_admin(_e2e_client, phone=admin_phone)
        assert admin_id
        admin_token = _login(_e2e_client, phone=admin_phone)

        before = _get_kpis(_e2e_client, admin_token)

        phone_active = _next_phone()
        _register_manager(_e2e_client, phone=phone_active)
        token_active = _login(_e2e_client, phone=phone_active)
        salon_active = _create_salon(_e2e_client, token_active, name="e2e-kpi-salon-active")

        phone_inactive = _next_phone()
        _register_manager(_e2e_client, phone=phone_inactive)
        token_inactive = _login(_e2e_client, phone=phone_inactive)
        salon_inactive = _create_salon(_e2e_client, token_inactive, name="e2e-kpi-salon-inactive")
        _set_salon_status(salon_inactive, "INACTIVE")

        phone_suspended = _next_phone()
        _register_manager(_e2e_client, phone=phone_suspended)
        token_suspended = _login(_e2e_client, phone=phone_suspended)
        salon_suspended = _create_salon(
            _e2e_client, token_suspended, name="e2e-kpi-salon-suspended"
        )
        _set_salon_status(salon_suspended, "SUSPENDED")

        assert salon_active and salon_inactive and salon_suspended

        after = _get_kpis(_e2e_client, admin_token)

        assert after["salons_total"] - before["salons_total"] == 3
        assert after["salons_active"] - before["salons_active"] == 1

    # ── Parcours 2 : clients_total (rôle CLIENT uniquement) ─────────────────────

    def test_clients_total_counts_only_client_role(self, _e2e_client: TestClient) -> None:
        """`clients_total` exclut `MANAGER`/`HAIRDRESSER`/`ADMIN`."""
        admin_phone = _next_phone()
        admin_id = _register_and_promote_admin(_e2e_client, phone=admin_phone)
        assert admin_id
        admin_token = _login(_e2e_client, phone=admin_phone)

        before = _get_kpis(_e2e_client, admin_token)

        manager_phone = _next_phone()
        _register_manager(_e2e_client, phone=manager_phone)
        manager_token = _login(_e2e_client, phone=manager_phone)
        salon_id = _create_salon(_e2e_client, manager_token, name="e2e-kpi-salon-roles")
        _add_hairdresser(_e2e_client, manager_token, salon_id, phone=_next_phone())
        _register_client_account(_e2e_client, phone=_next_phone())

        after = _get_kpis(_e2e_client, admin_token)

        # Seul le compte CLIENT pèse dans clients_total : ni le gérant (MANAGER),
        # ni le coiffeur (HAIRDRESSER), ni l'admin (ADMIN) lui-même.
        assert after["clients_total"] - before["clients_total"] == 1

    # ── Parcours 3 : bornes de mois civil (tickets_this_month) ─────────────────

    def test_tickets_this_month_respects_inclusive_month_bounds(
        self, _e2e_client: TestClient
    ) -> None:
        """Un ticket le 1er/dernier jour du mois compte ; la veille/le lendemain du mois, non."""
        admin_phone = _next_phone()
        admin_id = _register_and_promote_admin(_e2e_client, phone=admin_phone)
        assert admin_id
        admin_token = _login(_e2e_client, phone=admin_phone)

        manager_phone = _next_phone()
        _register_manager(_e2e_client, phone=manager_phone)
        manager_token = _login(_e2e_client, phone=manager_phone)
        salon_id = _create_salon(_e2e_client, manager_token, name="e2e-kpi-salon-month")

        today = datetime.date.today()
        month_from, month_to = month_bounds(today)

        before = _get_kpis(_e2e_client, admin_token)

        # Bornes incluses du mois courant.
        _seed_ticket(salon_id, day=month_from, status="waiting")
        _seed_ticket(salon_id, day=month_to, status="in_progress")
        # Un jour avant/après le mois : exclus de `tickets_this_month`.
        _seed_ticket(
            salon_id, day=month_from - datetime.timedelta(days=1), status="waiting"
        )
        _seed_ticket(
            salon_id, day=month_to + datetime.timedelta(days=1), status="waiting"
        )

        after = _get_kpis(_e2e_client, admin_token)

        assert after["tickets_total"] - before["tickets_total"] == 4
        assert after["tickets_this_month"] - before["tickets_this_month"] == 2
        assert after["month_from"] == month_from.isoformat()
        assert after["month_to"] == month_to.isoformat()

    def test_tickets_total_includes_expired(self, _e2e_client: TestClient) -> None:
        """`tickets_total` compte un ticket `expired` (volume plateforme, tous statuts)."""
        admin_phone = _next_phone()
        admin_id = _register_and_promote_admin(_e2e_client, phone=admin_phone)
        assert admin_id
        admin_token = _login(_e2e_client, phone=admin_phone)

        manager_phone = _next_phone()
        _register_manager(_e2e_client, phone=manager_phone)
        manager_token = _login(_e2e_client, phone=manager_phone)
        salon_id = _create_salon(_e2e_client, manager_token, name="e2e-kpi-salon-expired")

        before = _get_kpis(_e2e_client, admin_token)

        _seed_ticket(salon_id, day=datetime.date.today(), status="expired")

        after = _get_kpis(_e2e_client, admin_token)

        assert after["tickets_total"] - before["tickets_total"] == 1
        assert after["tickets_this_month"] - before["tickets_this_month"] == 1

    # ── Parcours 4 : revenu net (paiement + ajustement + borne de mois) ────────

    def test_revenue_nets_adjustment_and_excludes_prior_month(
        self, _e2e_client: TestClient
    ) -> None:
        """`revenue_total`/`revenue_this_month` : net signé, borné au mois pour `_this_month`."""
        admin_phone = _next_phone()
        admin_id = _register_and_promote_admin(_e2e_client, phone=admin_phone)
        assert admin_id
        admin_token = _login(_e2e_client, phone=admin_phone)

        manager_phone = _next_phone()
        manager_id = _register_manager(_e2e_client, phone=manager_phone)
        manager_token = _login(_e2e_client, phone=manager_phone)
        salon_id = _create_salon(_e2e_client, manager_token, name="e2e-kpi-salon-revenue")
        service_id = _create_service(_e2e_client, manager_token, salon_id, price="10000.00")

        before = _get_kpis(_e2e_client, admin_token)

        # Paiement + correction à la baisse, tous deux horodatés "maintenant"
        # (mois courant) : comptent dans revenue_total ET revenue_this_month.
        payment_id = _record_payment(
            _e2e_client, manager_token, salon_id, service_id, price="10000.00"
        )
        _adjust_payment(
            _e2e_client, manager_token, salon_id, payment_id, delta="-1500.00"
        )

        # Opération datée du mois précédent : compte dans revenue_total, exclue
        # de revenue_this_month (bornes UTC du mois courant).
        month_from, _ = month_bounds(datetime.date.today())
        previous_month_day = month_from - datetime.timedelta(days=1)
        _seed_past_cash_journal_payment(
            salon_id,
            manager_id,
            amount="4000.00",
            created_at=day_start_utc(previous_month_day),
        )

        after = _get_kpis(_e2e_client, admin_token)

        total_delta = _dec(after["revenue_total"]) - _dec(before["revenue_total"])
        this_month_delta = _dec(after["revenue_this_month"]) - _dec(
            before["revenue_this_month"]
        )

        # Net de la période courante : 10000.00 - 1500.00 = 8500.00.
        # Total (incluant le mois précédent) : 8500.00 + 4000.00 = 12500.00.
        assert this_month_delta == decimal.Decimal("8500.00")
        assert total_delta == decimal.Decimal("12500.00")

    # ── Parcours 5 : deny-by-default et RBAC (ADR-0015) ─────────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        resp = _e2e_client.get(_KPIS_URL)
        assert resp.status_code == 401

    def test_manager_role_returns_403(self, _e2e_client: TestClient) -> None:
        """Un gérant (rôle réel résolu en base) n'a pas `STATS_READ_PLATFORM` → 403."""
        manager_phone = _next_phone()
        _register_manager(_e2e_client, phone=manager_phone)
        manager_token = _login(_e2e_client, phone=manager_phone)

        resp = _e2e_client.get(
            _KPIS_URL, headers={"Authorization": f"Bearer {manager_token}"}
        )
        assert resp.status_code == 403

    # ── Parcours 6 : absence de PII (§11.3) ─────────────────────────────────────

    def test_response_contains_no_pii(self, _e2e_client: TestClient) -> None:
        """La réponse agrégée ne révèle aucune identité (salon, client, jeton)."""
        admin_phone = _next_phone()
        admin_id = _register_and_promote_admin(_e2e_client, phone=admin_phone)
        assert admin_id
        admin_token = _login(_e2e_client, phone=admin_phone)

        manager_phone = _next_phone()
        _register_manager(_e2e_client, phone=manager_phone)
        manager_token = _login(_e2e_client, phone=manager_phone)
        salon_id = _create_salon(_e2e_client, manager_token, name="e2e-kpi-salon-pii")
        client_id = _register_client_account(_e2e_client, phone=_next_phone())

        resp = _e2e_client.get(
            _KPIS_URL, headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        assert admin_token not in resp.text
        assert salon_id not in resp.text
        assert client_id not in resp.text
        assert admin_id not in resp.text
