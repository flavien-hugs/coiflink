"""Journalisation des **accès sensibles** §11.3/§11.4 — présence + non-fuite (#51).

Prouve, sur la pile réelle (HTTP → cas d'usage → dépôts SQL → PostgreSQL), que :

1. **Présence** — les actions sensibles **câblées** aujourd'hui écrivent bien une
   entrée `audit_logs` (par `action` + `entity_id` + `actor_user_id`) : création de
   fiche client (`CUSTOMER_CREATED`), mise à jour de note (`CUSTOMER_NOTE_UPDATED`),
   modification de prestation (`SERVICE_UPDATED`), modification de salon
   (`SALON_UPDATED`), enregistrement de paiement (`PAYMENT_RECORDED`).
2. **Atomicité** — une action métier qui **échoue** (paiement au montant incohérent
   → `422`) ne laisse **aucune** entrée d'audit (même unité de travail, ADR-0019).
3. **Non-fuite (cœur du critère §11.3)** — en balayant **toutes** les lignes
   `audit_logs` produites par l'acteur de test, aucune ne contient de secret ni de
   PII des entités de test : ni le nom/le téléphone du client, ni le contenu de la
   note, ni le montant du paiement. `metadata` ne porte que des **noms de champs**.

Périmètre (spec *Non-Goals*) : on **teste l'existant**. Les actions §11.4 **non
encore câblées** (`Connexion`, `Création rendez-vous`, `Création employé`,
`Désactivation salon`) ne sont **pas** assertées présentes — elles relèvent d'une
issue de durcissement dédiée (gap documenté dans la note de PR).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_security_audit_e2e.py -v

Nettoyage FK-safe : plage de téléphones réservée `+225089993xxxx`.
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
_TEST_JWT_SECRET = "test-only-security-audit-e2e-jwt-secret-not-for-production"

_E2E_PHONE_PREFIX = "+225089993"
_PHONE_MANAGER = "0899930001"
_PHONE_CLIENT = "0899930002"
_PASSWORD = "security-audit-e2e-strong-password-2024"

_SERVICE_PRICE = "5000.00"
_SERVICE_DURATION = 30
_VALID_HOURS = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}

# Sentinelles **PII/secret** distinctives : elles ne doivent apparaître dans
# **aucune** ligne d'audit (nom/téléphone client, note, nouveau nom de salon).
_CUST_NAME = "Zephyrine-SECRETNAME-QX"
_CUST_PHONE_LOCAL = "0899930009"
_CUST_NOTE = "Allergie-SECRETNOTE-au-reactif-QX"
_CUST_NOTE_UPDATED = "Prefere-SECRETNOTE2-le-samedi-QX"
_SALON_RENAME = "Salon-SECRETRENAME-QX"


# ─── Nettoyage FK-safe ────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
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
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e d'audit.")

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)

    main_app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    main_app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=50,
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


def _login(client: TestClient, *, phone: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée ({phone}) : {resp.text}"
    return resp.json()["access_token"]


# ─── Helpers SQL (lecture directe du journal) ─────────────────────────────────


def _count_audit(action: str, entity_id: str, actor_user_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT COUNT(*) FROM audit_logs "
                "WHERE action = :a AND entity_id = :e AND actor_user_id = :u"
            ),
            {"a": action, "e": entity_id, "u": actor_user_id},
        ).scalar_one()


def _count_audit_for_salon(salon_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM audit_logs WHERE salon_id = :s"),
            {"s": salon_id},
        ).scalar_one()


def _audit_rows_text(actor_user_id: str) -> list[str]:
    """Sérialise **toutes** les lignes d'audit d'un acteur (colonnes incluant `metadata`)."""

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT action, entity_type, entity_id, salon_id, actor_user_id, "
                "metadata::text AS meta FROM audit_logs WHERE actor_user_id = :u"
            ),
            {"u": actor_user_id},
        ).mappings().all()
    return [
        " | ".join(str(row[col]) for col in ("action", "entity_type", "entity_id", "salon_id", "actor_user_id", "meta"))
        for row in rows
    ]


# ─── Décor ────────────────────────────────────────────────────────────────────


@dataclass
class _Ctx:
    salon_id: str
    owner_id: str
    manager_token: str
    service_id: str
    client_id: str
    client_token: str


@pytest.fixture()
def _ctx(_e2e_client: TestClient) -> _Ctx:
    """Gérant + salon réservable + prestation ; un client pour la réservation/paiement."""

    client = _e2e_client
    owner_id = _register(client, "/auth/register/manager", phone=_PHONE_MANAGER, full_name="Gérant Audit")
    manager_token = _login(client, phone=_PHONE_MANAGER)
    auth = _auth(manager_token)

    resp = client.post("/salons", json={"name": "e2e-audit-salon"}, headers=auth)
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    salon_id = resp.json()["id"]

    resp = client.put(f"/salons/{salon_id}/opening-hours", json=_VALID_HOURS, headers=auth)
    assert resp.status_code == 200, f"Horaires refusés : {resp.text}"

    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": "Coupe Audit", "price": _SERVICE_PRICE, "duration_minutes": _SERVICE_DURATION},
        headers=auth,
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    service_id = resp.json()["id"]

    client_id = _register(client, "/auth/register", phone=_PHONE_CLIENT, full_name="Client Audit")
    client_token = _login(client, phone=_PHONE_CLIENT)

    return _Ctx(
        salon_id=salon_id,
        owner_id=owner_id,
        manager_token=manager_token,
        service_id=service_id,
        client_id=client_id,
        client_token=client_token,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestSensitiveAuditE2E:
    """Présence des entrées d'audit sensibles + invariant de non-fuite (§11.3/§11.4)."""

    def test_sensitive_actions_are_logged_and_leak_free(
        self, _e2e_client: TestClient, _ctx: _Ctx
    ) -> None:
        """Chaque action sensible câblée écrit une entrée neutre ; aucune PII/secret au journal."""

        client = _e2e_client
        auth = _auth(_ctx.manager_token)

        # 1. Création de fiche client (PII : nom + téléphone + note) → CUSTOMER_CREATED.
        resp = client.post(
            f"/salons/{_ctx.salon_id}/customers",
            json={"full_name": _CUST_NAME, "phone": _CUST_PHONE_LOCAL, "notes": _CUST_NOTE},
            headers=auth,
        )
        assert resp.status_code == 201, f"Création fiche échouée : {resp.text}"
        customer_id = resp.json()["id"]

        # 2. Mise à jour de la note (donnée sensible) → CUSTOMER_NOTE_UPDATED.
        resp = client.put(
            f"/salons/{_ctx.salon_id}/customers/{customer_id}/notes",
            json={"notes": _CUST_NOTE_UPDATED},
            headers=auth,
        )
        assert resp.status_code == 200, f"Mise à jour note échouée : {resp.text}"

        # 3. Encaissement d'une prestation → PAYMENT_RECORDED. Encaissé **avant** toute
        #    modification de prestation, pour que le montant attendu reste `_SERVICE_PRICE`.
        payment = client.post(
            f"/salons/{_ctx.salon_id}/payments",
            json={
                "amount": _SERVICE_PRICE,
                "payment_method": "CASH",
                "service_id": _ctx.service_id,
                "client_id": _ctx.client_id,
            },
            headers=auth,
        )
        assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
        payment_id = payment.json()["id"]

        # 4. Modification de prestation → SERVICE_UPDATED.
        resp = client.put(
            f"/salons/{_ctx.salon_id}/services/{_ctx.service_id}",
            json={"name": "Coupe Audit v2", "price": "6000.00", "duration_minutes": 45},
            headers=auth,
        )
        assert resp.status_code == 200, f"Modification prestation échouée : {resp.text}"

        # 5. Modification de salon (nouveau nom = sentinelle) → SALON_UPDATED.
        resp = client.put(
            f"/salons/{_ctx.salon_id}",
            json={"name": _SALON_RENAME, "description": None, "phone": None},
            headers=auth,
        )
        assert resp.status_code == 200, f"Modification salon échouée : {resp.text}"

        # ── Présence : chaque action a **au moins une** entrée (action+entité+acteur).
        assert _count_audit("CUSTOMER_CREATED", customer_id, _ctx.owner_id) >= 1
        assert _count_audit("CUSTOMER_NOTE_UPDATED", customer_id, _ctx.owner_id) >= 1
        assert _count_audit("SERVICE_UPDATED", _ctx.service_id, _ctx.owner_id) >= 1
        assert _count_audit("SALON_UPDATED", _ctx.salon_id, _ctx.owner_id) >= 1
        assert _count_audit("PAYMENT_RECORDED", payment_id, _ctx.owner_id) >= 1

        # ── Non-fuite : aucune ligne d'audit ne contient de PII ni de secret de test.
        blob = "\n".join(_audit_rows_text(_ctx.owner_id))
        assert blob, "Aucune ligne d'audit produite — le parcours a-t-il bien tourné ?"
        for leaked in (
            _CUST_NAME,
            _CUST_PHONE_LOCAL,
            "+225" + _CUST_PHONE_LOCAL[1:],  # forme E.164 normalisée
            _CUST_NOTE,
            _CUST_NOTE_UPDATED,
            _SALON_RENAME,
            _SERVICE_PRICE,
            "6000.00",
        ):
            assert leaked not in blob, (
                f"Une PII/secret a fuité dans audit_logs (invariant §11.3 rompu) : {leaked!r}"
            )

    def test_failed_payment_writes_no_audit_entry(
        self, _e2e_client: TestClient, _ctx: _Ctx
    ) -> None:
        """Un paiement au **montant incohérent** (`422`) ne laisse **aucune** entrée d'audit (atomicité)."""

        client = _e2e_client

        before = _count_audit_for_salon(_ctx.salon_id)
        incoherent = client.post(
            f"/salons/{_ctx.salon_id}/payments",
            json={
                "amount": "4999.00",  # ≠ prix courant de la prestation
                "payment_method": "CASH",
                "service_id": _ctx.service_id,
                "client_id": _ctx.client_id,
            },
            headers=_auth(_ctx.manager_token),
        )
        assert incoherent.status_code == 422, f"Montant incohérent attendu 422 : {incoherent.text}"
        assert _count_audit_for_salon(_ctx.salon_id) == before, (
            "Une entrée d'audit a été écrite pour un paiement échoué (atomicité rompue)."
        )
