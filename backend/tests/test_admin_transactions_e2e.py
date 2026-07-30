"""Tests e2e pour US-5.6 — supervision agrégée des transactions (admin, #37).

Groupe `TestSummarizeSalonTransactionsE2E` (PostgreSQL requis) :
    exerce le **chemin SQL réel** de `SqlPlatformTransactionRepository.summary_by_salon`
    / `count_salons` — la jointure `cash_journal ⋈ salons`, le `GROUP BY salon_id,
    salon_name`, les `COUNT(*) FILTER` par type d'opération, le `SUM(amount)` net
    signé, les bornes de dates conditionnelles, le tri et la pagination. Aucune
    suite unitaire/API (adossées à un dépôt en mémoire) ne couvre ce SQL : c'est le
    seul code qui satisfait réellement le critère d'acceptation #37 *« supervision
    agrégée, sans PII de paiement »*.

Scénarios (spec `specs/*.md`, cf. finding de revue automatisée sur la PR #116) :
    - deux salons avec activité → deux agrégats, un par salon (jointure `salons`) ;
    - `payment_count`/`adjustment_count` reflètent exactement les lignes
      `PAYMENT`/`ADJUSTMENT` du salon (`COUNT(*) FILTER`) ;
    - `total_amount` = somme signée nette (une correction fait baisser le net et
      incrémente `adjustment_count`, jamais `payment_count`) ;
    - un salon **sans activité** n'apparaît pas dans la page (miroir de `count_salons`) ;
    - bornes de dates (`date_from`/`date_to`) filtrent les agrégats en excluant
      l'activité hors plage ;
    - tri déterministe `salon_name ASC` et pagination (`limit`/`offset`/`total`) ;
    - `401` sans jeton, `403` pour un rôle autre qu'`ADMIN` (pile complète) ;
    - aucune PII de paiement (client, référence, auteur) dans la réponse agrégée.

Aucun endpoint d'inscription ADMIN n'existe (PRD §9.1) : le compte est créé via
l'inscription **client** puis promu `ADMIN` par une écriture SQL directe (miroir du
constat que `authentication.py::Login` relit toujours `role` depuis la base au
moment de la connexion — la promotion est donc effective dès le login suivant).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_admin_transactions_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225076997xxxx).
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
_TEST_JWT_SECRET = "test-only-admin-transactions-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e de la supervision plateforme.
_E2E_PHONE_PREFIX = "+225076997"
_PHONE_ADMIN_LOCAL = "0769970001"   # promu ADMIN — supervision plateforme
_PHONE_MANAGER_A_LOCAL = "0769970002"   # gérant A — salon avec activité
_PHONE_MANAGER_B_LOCAL = "0769970003"   # gérant B — salon avec activité
_PHONE_MANAGER_EMPTY_LOCAL = "0769970004"   # gérant C — salon SANS activité
_PASSWORD = "admin-transactions-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-admin-a"
_SALON_NAME_B = "e2e-salon-admin-b"
_SALON_NAME_EMPTY = "e2e-salon-admin-vide"

_SUMMARY_URL = "/admin/transactions/summary"


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
    - Supprime les données de test (plage +225076997) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e de la supervision plateforme.")

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
        json={"full_name": "Gérant E2E Admin", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_and_promote_admin(client: TestClient, *, phone: str = _PHONE_ADMIN_LOCAL) -> str:
    """Inscrit un compte client puis le promeut `ADMIN` en base (aucun endpoint dédié).

    `Login` relit toujours `role` depuis la base (`authentication.py`) : la
    promotion est donc effective dès la connexion suivante, sans mock ni fixture.
    """
    resp = client.post(
        "/auth/register",
        json={"full_name": "Admin E2E Plateforme", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
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
    """Crée un salon via l'API et retourne son UUID."""
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(
    client: TestClient, token: str, salon_id: str, *, price: str
) -> str:
    """Crée une prestation active via l'API et retourne son UUID."""
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": "Coupe homme", "price": price, "duration_minutes": 30},
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
    """Corrige un paiement (ligne `ADJUSTMENT`, delta signé)."""
    resp = client.post(
        f"/salons/{salon_id}/payments/{payment_id}/adjustments",
        json={"amount": delta},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Correction paiement échouée : {resp.text}"


def _summarize(client: TestClient, token: str, **params: object) -> dict:
    """`GET /admin/transactions/summary` (supervision agrégée, US-5.6, #37)."""
    resp = client.get(
        _SUMMARY_URL, params=params, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, f"Supervision agrégée échouée : {resp.text}"
    return resp.json()


def _summary_for(page: dict, salon_id: str) -> dict:
    return next(item for item in page["items"] if item["salon_id"] == salon_id)


# ─── Groupe e2e : pile complète (PostgreSQL requis) ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestSummarizeSalonTransactionsE2E:
    """`GET /admin/transactions/summary` bout-en-bout : jointure/agrégation SQL réelles."""

    # ── Parcours 1 : agrégats par salon (jointure `salons`) ──────────────────

    def test_two_salons_with_activity_return_two_summaries(
        self, _e2e_client: TestClient
    ) -> None:
        """Deux salons distincts avec activité → deux agrégats, un par salon."""
        admin_id = _register_and_promote_admin(_e2e_client)
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert admin_id and manager_a_id and manager_b_id

        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_a_id = _create_service(_e2e_client, token_a, salon_a_id, price="1000.00")
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id, price="2000.00")
        _record_payment(_e2e_client, token_a, salon_a_id, service_a_id, price="1000.00")
        _record_payment(_e2e_client, token_b, salon_b_id, service_b_id, price="2000.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        page = _summarize(_e2e_client, admin_token)

        ids = {item["salon_id"] for item in page["items"]}
        assert salon_a_id in ids
        assert salon_b_id in ids

    def test_summary_carries_salon_name_from_join(self, _e2e_client: TestClient) -> None:
        """`salon_name` reflète `salons.name` via la jointure (pas un id brut)."""
        _register_and_promote_admin(_e2e_client)
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        service_id = _create_service(_e2e_client, token, salon_id, price="1000.00")
        _record_payment(_e2e_client, token, salon_id, service_id, price="1000.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        page = _summarize(_e2e_client, admin_token)

        assert _summary_for(page, salon_id)["salon_name"] == _SALON_NAME_A

    # ── Parcours 2 : compteurs et montant net (COUNT FILTER / SUM signé) ─────

    def test_payment_count_reflects_payment_lines(self, _e2e_client: TestClient) -> None:
        """`payment_count` compte exactement les lignes `PAYMENT` du salon."""
        _register_and_promote_admin(_e2e_client)
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        for price in ("1000.00", "2000.00"):
            service_id = _create_service(_e2e_client, token, salon_id, price=price)
            _record_payment(_e2e_client, token, salon_id, service_id, price=price)

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        page = _summarize(_e2e_client, admin_token)

        assert _summary_for(page, salon_id)["payment_count"] == 2

    def test_adjustment_lowers_net_and_increments_adjustment_count(
        self, _e2e_client: TestClient
    ) -> None:
        """Une correction fait baisser `total_amount` (net) et incrémente `adjustment_count`,
        jamais `payment_count` (source de vérité #34)."""
        _register_and_promote_admin(_e2e_client)
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        service_id = _create_service(_e2e_client, token, salon_id, price="1000.00")
        payment_id = _record_payment(_e2e_client, token, salon_id, service_id, price="1000.00")
        _adjust_payment(_e2e_client, token, salon_id, payment_id, delta="-200.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        page = _summarize(_e2e_client, admin_token)
        summary = _summary_for(page, salon_id)

        assert summary["payment_count"] == 1
        assert summary["adjustment_count"] == 1
        assert decimal.Decimal(summary["total_amount"]) == decimal.Decimal("800.00")

    # ── Parcours 3 : salon sans activité — absent de la page (§37) ───────────

    def test_salon_without_activity_is_absent(self, _e2e_client: TestClient) -> None:
        """Un salon créé mais sans aucun paiement n'apparaît pas dans la supervision."""
        _register_and_promote_admin(_e2e_client)
        manager_empty_id = _register_manager(
            _e2e_client, phone=_PHONE_MANAGER_EMPTY_LOCAL
        )
        assert manager_empty_id
        token_empty = _login(_e2e_client, phone=_PHONE_MANAGER_EMPTY_LOCAL)
        salon_empty_id = _create_salon(_e2e_client, token_empty, name=_SALON_NAME_EMPTY)

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        page = _summarize(_e2e_client, admin_token)

        ids = {item["salon_id"] for item in page["items"]}
        assert salon_empty_id not in ids

    # ── Parcours 4 : bornes de dates (filtre sur `cash_journal.created_at`) ──

    def test_date_range_excludes_activity_out_of_bounds(
        self, _e2e_client: TestClient
    ) -> None:
        """Une plage de dates future exclut l'activité déjà enregistrée."""
        _register_and_promote_admin(_e2e_client)
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        service_id = _create_service(_e2e_client, token, salon_id, price="1000.00")
        _record_payment(_e2e_client, token, salon_id, service_id, price="1000.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        future = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        page = _summarize(_e2e_client, admin_token, date_from=future)

        ids = {item["salon_id"] for item in page["items"]}
        assert salon_id not in ids

    def test_date_range_includes_activity_in_bounds(self, _e2e_client: TestClient) -> None:
        """Une plage englobant aujourd'hui inclut l'activité enregistrée."""
        _register_and_promote_admin(_e2e_client)
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        service_id = _create_service(_e2e_client, token, salon_id, price="1000.00")
        _record_payment(_e2e_client, token, salon_id, service_id, price="1000.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        today = datetime.date.today().isoformat()
        page = _summarize(_e2e_client, admin_token, date_from=today, date_to=today)

        ids = {item["salon_id"] for item in page["items"]}
        assert salon_id in ids

    # ── Parcours 5 : tri et pagination ────────────────────────────────────────

    def test_sorted_by_salon_name_ascending(self, _e2e_client: TestClient) -> None:
        """Les agrégats sont triés `salon_name ASC` (tri déterministe)."""
        _register_and_promote_admin(_e2e_client)
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        # Noms délibérément inversés pour distinguer l'ordre alphabétique de l'ordre de création.
        salon_z_id = _create_salon(_e2e_client, token_a, name="e2e-salon-admin-zzz")
        salon_a_id = _create_salon(_e2e_client, token_b, name="e2e-salon-admin-aaa")
        service_z_id = _create_service(_e2e_client, token_a, salon_z_id, price="1000.00")
        service_a_id = _create_service(_e2e_client, token_b, salon_a_id, price="1000.00")
        _record_payment(_e2e_client, token_a, salon_z_id, service_z_id, price="1000.00")
        _record_payment(_e2e_client, token_b, salon_a_id, service_a_id, price="1000.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        page = _summarize(_e2e_client, admin_token)

        names = [item["salon_name"] for item in page["items"]]
        assert names == sorted(names)

    def test_pagination_total_reflects_all_matching_salons(
        self, _e2e_client: TestClient
    ) -> None:
        """`total` compte tous les salons avec activité, indépendamment de `limit`."""
        _register_and_promote_admin(_e2e_client)
        manager_a_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        assert manager_a_id and manager_b_id
        token_a = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_MANAGER_B_LOCAL)
        salon_a_id = _create_salon(_e2e_client, token_a, name=_SALON_NAME_A)
        salon_b_id = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        service_a_id = _create_service(_e2e_client, token_a, salon_a_id, price="1000.00")
        service_b_id = _create_service(_e2e_client, token_b, salon_b_id, price="1000.00")
        _record_payment(_e2e_client, token_a, salon_a_id, service_a_id, price="1000.00")
        _record_payment(_e2e_client, token_b, salon_b_id, service_b_id, price="1000.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        page = _summarize(_e2e_client, admin_token, limit=1, offset=0)

        assert page["total"] == 2
        assert len(page["items"]) == 1

    # ── Parcours 6 : deny-by-default et RBAC (ADR-0015) ───────────────────────

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET sans jeton → 401 (deny-by-default, ADR-0015)."""
        resp = _e2e_client.get(_SUMMARY_URL)
        assert resp.status_code == 401

    def test_manager_role_returns_403(self, _e2e_client: TestClient) -> None:
        """Un gérant (pas ADMIN) n'a pas accès à la supervision plateforme."""
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)

        resp = _e2e_client.get(
            _SUMMARY_URL, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403

    # ── Parcours 7 : absence de PII de paiement (§11.3) ───────────────────────

    def test_response_contains_no_payment_pii(self, _e2e_client: TestClient) -> None:
        """La réponse agrégée ne révèle aucune PII de paiement (référence, client, jeton)."""
        _register_and_promote_admin(_e2e_client)
        manager_id = _register_manager(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        assert manager_id
        token = _login(_e2e_client, phone=_PHONE_MANAGER_A_LOCAL)
        salon_id = _create_salon(_e2e_client, token, name=_SALON_NAME_A)
        service_id = _create_service(_e2e_client, token, salon_id, price="1000.00")
        _record_payment(_e2e_client, token, salon_id, service_id, price="1000.00")

        admin_token = _login(_e2e_client, phone=_PHONE_ADMIN_LOCAL)
        resp = _e2e_client.get(
            _SUMMARY_URL, headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert admin_token not in resp.text
        assert service_id not in resp.text
        for forbidden in ("client_id", "reference", "recorded_by", "performed_by"):
            assert forbidden not in resp.text
