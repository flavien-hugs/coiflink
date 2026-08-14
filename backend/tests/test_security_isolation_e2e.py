"""Isolation inter-salons **de bout en bout sur routes réelles** (#51, §11.2).

Remplace la démonstration sur *mini-app* de `test_rbac_e2e.py` (conservée pour
`require_salon_scope` isolément) par une preuve sur les **routes de production**
montées depuis #15+ : la pile complète (HTTP `TestClient` → gardes → dépôts SQL →
PostgreSQL, **JWT réel** injecté) refuse au gérant A toute donnée du salon B, en
**lecture comme en écriture**, sans aucun oracle d'existence.

Couvre (spec §2/§3/§4) :

- lecture inter-salons → `403` systématique (salon, services, file d'attente
  walk-in, paiements, clients, CA, décompte du jour) ;
- écriture inter-salons → `403` **et aucune ligne écrite** dans le salon B ;
- anti-oracle : corps du `403` sans donnée de B, `detail` **identique** à celui
  d'un rôle insuffisant ;
- filtre `client_id` étranger → **liste vide**, jamais les données de B ;
- `CLIENT` : refusé sur toute route `/salons/{id}/…`, `404` neutre sur un reçu
  tiers/inexistant, lecture « mes reçus » bornée aux siens ;
- `HAIRDRESSER` : lit la file d'attente **de son salon** mais **ne peut pas
  encaisser** (`403`, permission absente même **dans** sa portée) ;
- révocation immédiate (compte suspendu après émission → `403` « Compte désactivé. ») ;
- rotation du refresh à `/auth/refresh` + refus du refresh d'un compte non `ACTIVE`.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_security_isolation_e2e.py -v

Nettoyage FK-safe : plage de téléphones réservée `+225089991xxxx` ;
`audit_logs`/`campaigns` **avant** `salons`/`users`, `cash_journal` avant
`payments`. La table `notifications` a été supprimée par la migration
destructive `0017` avec tout le module Rendez-vous/Notification — plus rien
à nettoyer ici.
"""

from __future__ import annotations

import datetime
import os
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

# Secret de test **local** — jamais un secret réel, jamais en production (§11).
_TEST_JWT_SECRET = "test-only-security-isolation-e2e-jwt-secret-not-for-production"

# Plage de téléphones **réservée** à cette suite (confirmée libre : aucun autre
# `*_e2e.py` n'utilise `+225089991`).
_E2E_PHONE_PREFIX = "+225089991"
_PHONE_A = "0899910001"   # gérant A
_PHONE_B = "0899910002"   # gérant B (salon isolé)
_PHONE_CLIENT = "0899910003"  # client
_PHONE_HAIRDRESSER = "0899910004"  # coiffeur du salon A
_PASSWORD = "security-isolation-e2e-strong-password-2024"

_SERVICE_PRICE = "5000.00"
_SERVICE_DURATION = 30
_VALID_HOURS = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}

_FORBIDDEN_DETAIL = "Accès refusé."


# ─── Nettoyage FK-safe ────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`)."""

    engine = get_engine()
    salons_of_prefix = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    users_of_prefix = "SELECT id FROM users WHERE phone LIKE :prefix"
    with engine.connect() as conn:
        params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}
        conn.execute(
            text(
                f"DELETE FROM audit_logs WHERE salon_id IN ({salons_of_prefix}) "
                f"OR actor_user_id IN ({users_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM campaigns WHERE salon_id IN ({salons_of_prefix}) "
                f"OR created_by IN ({users_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM cash_journal WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(f"DELETE FROM payments WHERE salon_id IN ({salons_of_prefix})"), params
        )
        conn.execute(
            text(f"DELETE FROM services WHERE salon_id IN ({salons_of_prefix})"), params
        )
        conn.execute(
            text(
                f"DELETE FROM customer_profiles WHERE salon_id IN ({salons_of_prefix}) "
                f"OR user_id IN ({users_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM salon_members WHERE salon_id IN ({salons_of_prefix}) "
                f"OR user_id IN ({users_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM salon_photos WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text("DELETE FROM salons WHERE owner_id IN (" + users_of_prefix + ")"),
            params,
        )
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        conn.commit()


# ─── Fixture pile complète ────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT réel de test)."""

    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e d'isolation.")

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)

    main_app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    main_app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=50,  # large : cette suite n'exerce pas le brute-force
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


# ─── Helpers HTTP ─────────────────────────────────────────────────────────────


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(client: TestClient, path: str, *, phone: str, full_name: str) -> str:
    resp = client.post(
        path, json={"full_name": full_name, "phone": phone, "password": _PASSWORD}
    )
    assert resp.status_code == 201, f"Inscription échouée ({phone}) : {resp.text}"
    return resp.json()["id"]


def _login_pair(client: TestClient, *, phone: str) -> dict:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée ({phone}) : {resp.text}"
    return resp.json()


def _create_bookable_salon(client: TestClient, token: str, *, name: str) -> tuple[str, str]:
    """Crée un salon réservable (horaires valides + prestation active) → (salon_id, service_id)."""

    auth = _auth(token)
    resp = client.post("/salons", json={"name": name}, headers=auth)
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    salon_id = resp.json()["id"]

    resp = client.put(
        f"/salons/{salon_id}/opening-hours", json=_VALID_HOURS, headers=auth
    )
    assert resp.status_code == 200, f"Horaires refusés : {resp.text}"

    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": "Coupe", "price": _SERVICE_PRICE, "duration_minutes": _SERVICE_DURATION},
        headers=auth,
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return salon_id, resp.json()["id"]


def _create_customer(client: TestClient, token: str, salon_id: str, *, full_name: str) -> str:
    resp = client.post(
        f"/salons/{salon_id}/customers",
        json={"full_name": full_name},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"Création fiche client échouée : {resp.text}"
    return resp.json()["id"]


def _pay_for_service(client: TestClient, journey: "_Iso", *, client_id: str) -> str:
    """Encaisse (gérant A) la prestation du salon A pour `client_id`.

    Retourne le `payment_id`. Sert à peupler le salon A pour le test du filtre
    `client_id` étranger (aucune donnée de B ne doit jamais fuiter par ce filtre).
    """

    payment = client.post(
        f"/salons/{journey.salon_a}/payments",
        json={
            "amount": _SERVICE_PRICE,
            "payment_method": "CASH",
            "service_id": journey.service_a,
            "client_id": client_id,
        },
        headers=_auth(journey.token_a),
    )
    assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
    return payment.json()["id"]


# ─── Décor partagé ────────────────────────────────────────────────────────────


@dataclass
class _Iso:
    salon_a: str
    owner_a: str
    token_a: str
    refresh_a: str
    service_a: str
    customer_a: str
    salon_b: str
    owner_b: str
    service_b: str
    customer_b: str
    client_id: str
    client_token: str
    hairdresser_id: str
    hairdresser_token: str


@pytest.fixture()
def _iso(_e2e_client: TestClient) -> _Iso:
    """Deux gérants (salons réservables + une fiche client chacun), un client, un coiffeur du salon A."""

    client = _e2e_client

    owner_a = _register(client, "/auth/register/manager", phone=_PHONE_A, full_name="Gérant A")
    pair_a = _login_pair(client, phone=_PHONE_A)
    token_a = pair_a["access_token"]
    salon_a, service_a = _create_bookable_salon(client, token_a, name="e2e-iso-salon-A")
    customer_a = _create_customer(client, token_a, salon_a, full_name="Client Fiche A")

    owner_b = _register(client, "/auth/register/manager", phone=_PHONE_B, full_name="Gérant B")
    token_b = _login_pair(client, phone=_PHONE_B)["access_token"]
    salon_b, service_b = _create_bookable_salon(client, token_b, name="e2e-iso-salon-B")
    customer_b = _create_customer(client, token_b, salon_b, full_name="Client Fiche B")

    client_id = _register(client, "/auth/register", phone=_PHONE_CLIENT, full_name="Client E2E")
    client_token = _login_pair(client, phone=_PHONE_CLIENT)["access_token"]

    # Coiffeur rattaché au salon A (portée = salon A) via l'endpoint gérant.
    resp = client.post(
        f"/salons/{salon_a}/employees",
        json={"full_name": "Coiffeur A", "phone": _PHONE_HAIRDRESSER, "password": _PASSWORD},
        headers=_auth(token_a),
    )
    assert resp.status_code == 201, f"Création coiffeur échouée : {resp.text}"
    hairdresser_id = resp.json()["id"]
    hairdresser_token = _login_pair(client, phone=_PHONE_HAIRDRESSER)["access_token"]

    return _Iso(
        salon_a=salon_a,
        owner_a=owner_a,
        token_a=token_a,
        refresh_a=pair_a["refresh_token"],
        service_a=service_a,
        customer_a=customer_a,
        salon_b=salon_b,
        owner_b=owner_b,
        service_b=service_b,
        customer_b=customer_b,
        client_id=client_id,
        client_token=client_token,
        hairdresser_id=hairdresser_id,
        hairdresser_token=hairdresser_token,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCrossSalonIsolationE2E:
    """Gérant A ne touche **jamais** le salon B (routes réelles, pile complète)."""

    def test_cross_salon_reads_return_403(self, _e2e_client: TestClient, _iso: _Iso) -> None:
        """Toute **lecture** du salon B avec le jeton de A → `403`."""

        client = _e2e_client
        b = _iso.salon_b
        read_targets = [
            client.get(f"/salons/{b}", headers=_auth(_iso.token_a)),
            client.get(f"/salons/{b}/services", headers=_auth(_iso.token_a)),
            client.get(f"/salons/{b}/queue/tickets", headers=_auth(_iso.token_a)),
            client.get(f"/salons/{b}/payments", headers=_auth(_iso.token_a)),
            client.get(f"/salons/{b}/customers", headers=_auth(_iso.token_a)),
            client.get(f"/salons/{b}/revenue/summary", headers=_auth(_iso.token_a)),
        ]
        for resp in read_targets:
            assert resp.status_code == 403, f"Lecture inter-salons non refusée : {resp.request.url}"
            assert resp.json()["detail"] == _FORBIDDEN_DETAIL

    def test_cross_salon_writes_return_403_and_write_nothing(
        self, _e2e_client: TestClient, _iso: _Iso
    ) -> None:
        """Toute **écriture** dans le salon B avec le jeton de A → `403` **sans écriture**."""

        client = _e2e_client
        b = _iso.salon_b

        writes = [
            client.post(
                f"/salons/{b}/services",
                json={"name": "Intrusion", "price": "9999.00", "duration_minutes": 30},
                headers=_auth(_iso.token_a),
            ),
            client.post(
                f"/salons/{b}/customers",
                json={"full_name": "Fiche Intrusion"},
                headers=_auth(_iso.token_a),
            ),
            client.post(
                f"/salons/{b}/payments",
                json={"amount": "1.00", "payment_method": "CASH", "client_id": _iso.client_id},
                headers=_auth(_iso.token_a),
            ),
        ]
        for resp in writes:
            assert resp.status_code == 403, f"Écriture inter-salons non refusée : {resp.request.url}"

        # Le salon B est **inchangé** : le gérant B ne voit toujours qu'une prestation
        # et une fiche (celles du décor), aucune ligne parasite écrite par A.
        token_b = _login_pair(client, phone=_PHONE_B)["access_token"]
        services_b = client.get(f"/salons/{b}/services", headers=_auth(token_b)).json()
        customers_b = client.get(f"/salons/{b}/customers", headers=_auth(token_b)).json()
        assert len(services_b) == 1, f"Le salon B a été modifié : {services_b}"
        assert customers_b["total"] == 1, f"Une fiche parasite a été écrite dans B : {customers_b}"

    def test_cross_salon_403_is_generic_and_anti_oracle(
        self, _e2e_client: TestClient, _iso: _Iso
    ) -> None:
        """Le `403` inter-salons ne fuit aucune donnée de B et a le **même** message qu'un rôle insuffisant."""

        client = _e2e_client
        cross = client.get(f"/salons/{_iso.salon_b}", headers=_auth(_iso.token_a))
        assert cross.status_code == 403
        body = cross.text
        assert _iso.salon_b not in body, "Le corps du 403 révèle l'id du salon B (oracle)."
        assert _iso.owner_b not in body, "Le corps du 403 révèle l'id du gérant B (oracle)."

        # Rôle insuffisant : un client (sans portée salon) sur le salon A → 403 aussi.
        insufficient = client.get(f"/salons/{_iso.salon_a}", headers=_auth(_iso.client_token))
        assert insufficient.status_code == 403
        # Message **identique** : l'accès inter-salons est indiscernable d'un rôle insuffisant.
        assert cross.json()["detail"] == insufficient.json()["detail"] == _FORBIDDEN_DETAIL

    def test_foreign_client_id_filter_returns_empty(
        self, _e2e_client: TestClient, _iso: _Iso
    ) -> None:
        """Filtrer les paiements de A par un `client_id` étranger → **liste vide** (jamais B)."""

        client = _e2e_client
        # Un paiement réel dans le salon A, pour le client E2E.
        payment_id = _pay_for_service(client, _iso, client_id=_iso.client_id)

        # Filtre par le vrai client → le paiement apparaît (contrôle positif).
        own = client.get(
            f"/salons/{_iso.salon_a}/payments",
            params={"client_id": _iso.client_id},
            headers=_auth(_iso.token_a),
        ).json()
        assert any(item["id"] == payment_id for item in own["items"])

        # Filtre par une entité de B (le gérant B) → **aucune** ligne (isolation §11.2).
        foreign = client.get(
            f"/salons/{_iso.salon_a}/payments",
            params={"client_id": _iso.owner_b},
            headers=_auth(_iso.token_a),
        ).json()
        assert foreign["items"] == [], f"Le filtre client_id étranger a fuité des données : {foreign}"

    def test_client_role_is_isolated(self, _e2e_client: TestClient, _iso: _Iso) -> None:
        """Un `CLIENT` : refusé sur les routes salon, `404` neutre sur un reçu inconnu, historique borné."""

        client = _e2e_client
        auth = _auth(_iso.client_token)

        # Aucune portée salon pour un client → 403 sur une route de gestion salon.
        forbidden = client.get(f"/salons/{_iso.salon_a}/customers", headers=auth)
        assert forbidden.status_code == 403

        # Reçu inexistant → 404 **neutre** (aucun oracle d'existence).
        import uuid

        missing = client.get(f"/me/receipts/{uuid.uuid4()}", headers=auth)
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Reçu introuvable."

        # « Mes reçus » : route d'appartenance, bornée au client (par construction, vide ici).
        receipts = client.get("/me/receipts", headers=auth)
        assert receipts.status_code == 200
        assert receipts.json()["items"] == []

    def test_hairdresser_reads_queue_but_cannot_record_payment(
        self, _e2e_client: TestClient, _iso: _Iso
    ) -> None:
        """Le coiffeur lit la file d'attente **de son salon** mais n'encaisse pas (`403`, permission absente **dans** sa portée)."""

        client = _e2e_client

        # File d'attente **de son salon** (QUEUE_TICKET_READ_SALON) → 200 (même liste vide).
        queue = client.get(
            f"/salons/{_iso.salon_a}/queue/tickets",
            headers=_auth(_iso.hairdresser_token),
        )
        assert queue.status_code == 200
        assert isinstance(queue.json()["items"], list)

        # Encaissement dans **son** salon → 403 : le coiffeur a la portée mais **pas**
        # la permission `PAYMENT_RECORD` (la portée seule n'ouvre aucun droit).
        payment = client.post(
            f"/salons/{_iso.salon_a}/payments",
            json={"amount": _SERVICE_PRICE, "payment_method": "CASH", "client_id": _iso.client_id},
            headers=_auth(_iso.hairdresser_token),
        )
        assert payment.status_code == 403
        assert payment.json()["detail"] == _FORBIDDEN_DETAIL


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestSessionRevocationAndRefreshE2E:
    """La relecture en base fait autorité (révocation immédiate) ; le refresh tourne."""

    def _suspend(self, user_id: str) -> None:
        with get_engine().connect() as conn:
            conn.execute(
                text("UPDATE users SET status = 'SUSPENDED' WHERE id = :uid"),
                {"uid": user_id},
            )
            conn.commit()

    def test_suspended_after_issue_returns_403(self, _e2e_client: TestClient, _iso: _Iso) -> None:
        """Compte suspendu **après** émission → requête suivante `403` « Compte désactivé. »."""

        client = _e2e_client
        before = client.get("/auth/me", headers=_auth(_iso.token_a))
        assert before.status_code == 200

        self._suspend(_iso.owner_a)

        after = client.get("/auth/me", headers=_auth(_iso.token_a))
        assert after.status_code == 403
        assert after.json()["detail"] == "Compte désactivé."

    def test_refresh_rotates_both_tokens(self, _e2e_client: TestClient, _iso: _Iso) -> None:
        """`POST /auth/refresh` émet une **nouvelle** paire (access **et** refresh changent)."""

        client = _e2e_client
        resp = client.post("/auth/refresh", json={"refresh_token": _iso.refresh_a})
        assert resp.status_code == 200, f"Rafraîchissement échoué : {resp.text}"
        rotated = resp.json()
        assert rotated["access_token"] != _iso.token_a
        assert rotated["refresh_token"] != _iso.refresh_a

    def test_refresh_refused_for_suspended_account(
        self, _e2e_client: TestClient, _iso: _Iso
    ) -> None:
        """Un refresh valide d'un compte devenu non `ACTIVE` est **refusé** (`401`)."""

        client = _e2e_client
        self._suspend(_iso.owner_a)
        resp = client.post("/auth/refresh", json={"refresh_token": _iso.refresh_a})
        assert resp.status_code == 401
