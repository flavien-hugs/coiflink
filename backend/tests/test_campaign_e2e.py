"""Tests e2e PostgreSQL des **campagnes/messages aux clients** (`SqlCampaignRepository`, #49).

Comble le seul chemin de persistance de #49 jamais exercé contre une vraie base :
les suites unitaires (domaine), cas d'usage (dépôts *fakes*) et API
(`app.dependency_overrides`) ne touchent **aucun** vrai PostgreSQL — elles ne
peuvent couvrir ni les contraintes réelles de la table `campaigns` (FK
`RESTRICT`, `CHECK` dérivés de `CampaignType`/`CampaignSegment`/`CampaignStatus`),
ni le `COUNT` salon-scopé réellement exécuté par `SqlCampaignRepository`/
`SqlCustomerRepository.count_for_salon` (clause `phone IS NOT NULL`), ni le
round-trip de la migration `0009`.

Scénarios (spec `specs/campagnes-messages-clients.md`) :

- une campagne créée (`POST /salons/{id}/campaigns`) insère **exactement une**
  ligne `campaigns` `status=PENDING`, `sent_at IS NULL`, `channel=SMS` ;
- l'**effectif** (`recipient_count`) est un `COUNT` salon-scopé des fiches
  **joignables** (`phone IS NOT NULL`) du segment ciblé — une fiche walk-in sans
  téléphone n'est **jamais** comptée, même si son genre correspond au segment ;
- les segments `FEMALE`/`MALE`/`OTHER` filtrent en plus par genre **exact** ;
  `ALL` ne filtre que sur la joignabilité ;
- la persistance et l'entrée d'audit `CAMPAIGN_CREATED` sont **atomiques** (même
  transaction) ; le `metadata` d'audit ne porte que `type`/`segment`/
  `recipient_count` — **jamais** le titre, le message ni un téléphone ;
- l'**isolation par salon** tient au niveau SQL : la liste (`GET`) et l'effectif
  d'un salon ne voient jamais les campagnes/fiches d'un autre salon ;
- la réponse HTTP de création ne révèle jamais de destinataire (aucun téléphone,
  aucune liste de fiches) — seul l'effectif (entier) est exposé ;
- les contraintes réelles du schéma (`CHECK` `type`/`segment`/`channel`/`status`,
  FK `RESTRICT` vers `salons`/`users`) sont respectées par l'`INSERT` réel ;
- round-trip de la migration `0009` (`upgrade`/`downgrade`) : la table `campaigns`
  disparaît puis réapparaît avec ses contraintes, sans double-préfixage `op.f()`.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_campaign_e2e.py -v

Sans `DATABASE_URL`, le fichier est **skippé proprement**. Nettoyage : les données
de test sont supprimées avant et après chaque test (plage réservée :
+225088998xxxx). Ordre de nettoyage (FK `RESTRICT`) : `audit_logs` →
`campaigns` → `customer_profiles` → `salon_members` → `salons` → `users` —
`campaigns` et `customer_profiles` **avant** `salons`/`users` (FK `RESTRICT`
sur `salon_id`/`created_by`/`salon_id`).
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

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
_TEST_JWT_SECRET = "test-only-campaign-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des campagnes (distincte des autres
# fichiers e2e : ils peuvent tourner dans la même base sans se marcher dessus).
_E2E_PHONE_PREFIX = "+225088998"
_PHONE_MANAGER_A_LOCAL = "0889980001"
_PHONE_MANAGER_B_LOCAL = "0889980002"
_PASSWORD = "campaign-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-campaigns-a"
_SALON_NAME_B = "e2e-salon-campaigns-b"

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_VALID_BODY: dict = {
    "type": "REMINDER",
    "segment": "ALL",
    "title": "Rappel de rendez-vous",
    "message": "Bonjour, n'oubliez pas votre rendez-vous de demain.",
}


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → campaigns → customer_profiles → salon_members → salons
    → users. `campaigns`/`customer_profiles` **avant** `salons`/`users` : leurs FK
    (`salon_id`/`created_by`) référencent ces deux tables (miroir du nettoyage de
    `test_customer_e2e.py`, avec `campaigns` en plus).
    """
    engine = get_engine()
    salons_of_prefix = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}
    with engine.connect() as conn:
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
            text(f"DELETE FROM campaigns WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM customer_profiles WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
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
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT) ; skip sans `DATABASE_URL`."""
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e des campagnes.")

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


def _register_manager(client: TestClient, *, phone: str) -> str:
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Campagnes", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
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


def _setup_manager_salon(
    client: TestClient, *, phone: str = _PHONE_MANAGER_A_LOCAL, name: str = _SALON_NAME_A
) -> tuple[str, str]:
    """Inscrit un gérant, se connecte, crée son salon. Retourne (token, salon_id)."""
    _register_manager(client, phone=phone)
    token = _login(client, phone=phone)
    salon_id = _create_salon(client, token, name=name)
    return token, salon_id


def _create_customer(
    client: TestClient, token: str, salon_id: str, **body: object
) -> dict:
    body.setdefault("full_name", "Fiche E2E Campagne")
    resp = client.post(
        f"/salons/{salon_id}/customers",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création fiche échouée : {resp.text}"
    return resp.json()


def _create_campaign(
    client: TestClient, token: str, salon_id: str, **body: object
) -> dict:
    payload = {**_VALID_BODY, **body}
    return client.post(
        f"/salons/{salon_id}/campaigns",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def _list_campaigns(client: TestClient, token: str, salon_id: str, **params: object) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/campaigns",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Liste échouée : {resp.text}"
    return resp.json()


# ─── Helpers SQL (lecture directe — assertions contre la source de vérité) ────


def _fetch_campaign_row(campaign_id: str) -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT salon_id, created_by, type, segment, channel, title, "
                    "message, recipient_count, status, sent_at, created_at "
                    "FROM campaigns WHERE id = :cid"
                ),
                {"cid": campaign_id},
            )
            .mappings()
            .one()
        )
        return dict(row)


def _count_campaigns_for_salon(salon_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM campaigns WHERE salon_id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


def _fetch_audit_rows(salon_id: str, action: str) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT actor_user_id, entity_type, entity_id, metadata, created_at "
                    "FROM audit_logs WHERE salon_id = :sid AND action = :action"
                ),
                {"sid": salon_id, "action": action},
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]


def _audit_dump(salon_id: str) -> str:
    """Concatène **toutes** les colonnes d'audit du salon en texte (recherche de PII)."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT action, actor_user_id::text AS actor, entity_type, "
                "entity_id::text AS entity, metadata::text AS meta "
                "FROM audit_logs WHERE salon_id = :sid"
            ),
            {"sid": salon_id},
        ).all()
        return " ".join(" ".join(str(value) for value in row) for row in rows)


def _table_present() -> bool:
    engine = get_engine()
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'campaigns'"
                )
            ).scalar_one()
            > 0
        )


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoque le **CLI Alembic** (sous-processus) depuis `backend/`, comme en CI."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )


# ─── A. Émission/trace atomique d'une campagne ───────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCampaignCreationE2E:
    """`POST /salons/{id}/campaigns` insère réellement une ligne `campaigns`."""

    def test_creates_exactly_one_pending_row(self, _e2e_client: TestClient) -> None:
        token, salon = _setup_manager_salon(_e2e_client)
        resp = _create_campaign(_e2e_client, token, salon)
        assert resp.status_code == 201, resp.text
        campaign_id = resp.json()["id"]

        row = _fetch_campaign_row(campaign_id)
        assert row["status"] == "PENDING"
        assert row["sent_at"] is None
        assert row["channel"] == "SMS"
        assert str(row["salon_id"]) == salon
        assert _count_campaigns_for_salon(salon) == 1

    def test_created_by_is_the_authenticated_manager(self, _e2e_client: TestClient) -> None:
        token, salon = _setup_manager_salon(_e2e_client)
        resp = _create_campaign(_e2e_client, token, salon)
        assert resp.status_code == 201, resp.text
        campaign_id = resp.json()["id"]

        rows = _fetch_audit_rows(salon, "CAMPAIGN_CREATED")
        assert len(rows) == 1
        row = _fetch_campaign_row(campaign_id)
        assert str(row["created_by"]) == str(rows[0]["actor_user_id"])

    def test_title_and_message_persisted_verbatim(self, _e2e_client: TestClient) -> None:
        token, salon = _setup_manager_salon(_e2e_client)
        resp = _create_campaign(
            _e2e_client,
            token,
            salon,
            title="Fermeture exceptionnelle",
            message="Le salon sera fermé le 15 août.",
            type="EXCEPTIONAL_CLOSURE",
        )
        assert resp.status_code == 201, resp.text
        row = _fetch_campaign_row(resp.json()["id"])
        assert row["title"] == "Fermeture exceptionnelle"
        assert row["message"] == "Le salon sera fermé le 15 août."
        assert row["type"] == "EXCEPTIONAL_CLOSURE"

    def test_response_never_exposes_recipient_content(self, _e2e_client: TestClient) -> None:
        """La réponse expose un effectif (entier), jamais une liste ou un téléphone."""
        token, salon = _setup_manager_salon(_e2e_client)
        _create_customer(_e2e_client, token, salon, phone="0700000001")
        resp = _create_campaign(_e2e_client, token, salon)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert isinstance(data["recipient_count"], int)
        assert "recipients" not in data
        assert "phone" not in resp.text
        assert "+2250700000001" not in resp.text


# ─── B. Effectif — COUNT salon-scopé, joignabilité SMS ───────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCampaignRecipientCountE2E:
    """`recipient_count` est un `COUNT` réel des fiches joignables (`phone IS NOT NULL`)."""

    def test_all_segment_counts_only_reachable_customers(
        self, _e2e_client: TestClient
    ) -> None:
        """Segment `ALL` : compte les fiches **avec** téléphone, exclut les walk-in sans numéro."""
        token, salon = _setup_manager_salon(_e2e_client)
        _create_customer(_e2e_client, token, salon, phone="0700000001")
        _create_customer(_e2e_client, token, salon, phone="0700000002")
        # Fiche walk-in sans téléphone : non joignable, jamais comptée.
        _create_customer(_e2e_client, token, salon)

        resp = _create_campaign(_e2e_client, token, salon, segment="ALL")
        assert resp.status_code == 201, resp.text
        assert resp.json()["recipient_count"] == 2

    def test_gender_segment_filters_by_gender_and_phone(
        self, _e2e_client: TestClient
    ) -> None:
        """Segment `FEMALE` : uniquement les fiches `gender=FEMALE` **et** joignables."""
        token, salon = _setup_manager_salon(_e2e_client)
        _create_customer(_e2e_client, token, salon, phone="0700000001", gender="FEMALE")
        # Femme sans téléphone : non joignable, exclue.
        _create_customer(_e2e_client, token, salon, gender="FEMALE")
        # Homme joignable : hors segment, exclu.
        _create_customer(_e2e_client, token, salon, phone="0700000002", gender="MALE")

        resp = _create_campaign(_e2e_client, token, salon, segment="FEMALE")
        assert resp.status_code == 201, resp.text
        assert resp.json()["recipient_count"] == 1

    def test_no_reachable_customer_yields_zero_recipient_count(
        self, _e2e_client: TestClient
    ) -> None:
        """Aucune fiche joignable dans le segment → effectif `0` (la campagne est quand même créée)."""
        token, salon = _setup_manager_salon(_e2e_client)
        _create_customer(_e2e_client, token, salon)  # walk-in, sans téléphone

        resp = _create_campaign(_e2e_client, token, salon, segment="ALL")
        assert resp.status_code == 201, resp.text
        assert resp.json()["recipient_count"] == 0
        assert _fetch_campaign_row(resp.json()["id"])["status"] == "PENDING"

    def test_recipient_count_never_double_counts_other_salon(
        self, _e2e_client: TestClient
    ) -> None:
        """Une fiche joignable d'un **autre** salon n'entre jamais dans l'effectif."""
        token_a, salon_a = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_MANAGER_B_LOCAL, name=_SALON_NAME_B
        )
        _create_customer(_e2e_client, token_b, salon_b, phone="0700000009")

        resp = _create_campaign(_e2e_client, token_a, salon_a, segment="ALL")
        assert resp.status_code == 201, resp.text
        assert resp.json()["recipient_count"] == 0


# ─── C. Isolation par salon (§11.2) ───────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCampaignIsolationE2E:
    """La liste et l'effectif d'un salon ne voient jamais les données d'un autre."""

    def test_list_never_returns_other_salon_campaigns(
        self, _e2e_client: TestClient
    ) -> None:
        token_a, salon_a = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_MANAGER_B_LOCAL, name=_SALON_NAME_B
        )
        _create_campaign(_e2e_client, token_a, salon_a)
        _create_campaign(_e2e_client, token_b, salon_b)

        page = _list_campaigns(_e2e_client, token_a, salon_a)
        assert page["total"] == 1
        assert len(page["items"]) == 1
        assert page["items"][0]["salon_id"] == salon_a

    def test_out_of_scope_salon_returns_403(self, _e2e_client: TestClient) -> None:
        token_a, _ = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_MANAGER_B_LOCAL, name=_SALON_NAME_B
        )
        resp = _create_campaign(_e2e_client, token_a, salon_b)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Accès refusé."

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        _, salon = _setup_manager_salon(_e2e_client)
        resp = _e2e_client.get(f"/salons/{salon}/campaigns")
        assert resp.status_code == 401
        assert _count_campaigns_for_salon(salon) == 0


# ─── D. Audit — atomicité, non-fuite de PII (§11.3/§11.4) ────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCampaignAuditE2E:
    """`CAMPAIGN_CREATED` : une entrée neutre, atomique avec la campagne."""

    def test_audit_entry_created_atomically(self, _e2e_client: TestClient) -> None:
        token, salon = _setup_manager_salon(_e2e_client)
        resp = _create_campaign(_e2e_client, token, salon)
        assert resp.status_code == 201, resp.text
        campaign_id = resp.json()["id"]

        rows = _fetch_audit_rows(salon, "CAMPAIGN_CREATED")
        assert len(rows) == 1
        assert str(rows[0]["entity_id"]) == campaign_id
        assert rows[0]["entity_type"] == "campaign"

    def test_audit_metadata_contains_only_type_segment_and_count(
        self, _e2e_client: TestClient
    ) -> None:
        token, salon = _setup_manager_salon(_e2e_client)
        _create_customer(_e2e_client, token, salon, phone="0700000001", gender="FEMALE")
        resp = _create_campaign(
            _e2e_client,
            token,
            salon,
            segment="FEMALE",
            title="Titre secret confidentiel",
            message="Corps du message secret confidentiel ABC123",
        )
        assert resp.status_code == 201, resp.text

        rows = _fetch_audit_rows(salon, "CAMPAIGN_CREATED")
        metadata = rows[0]["metadata"]
        assert set(metadata.keys()) == {"type", "segment", "recipient_count"}
        assert metadata["segment"] == "FEMALE"
        assert metadata["recipient_count"] == 1
        # Ni le titre ni le corps ne fuient dans AUCUNE colonne d'audit.
        assert "Titre secret confidentiel" not in _audit_dump(salon)
        assert "Corps du message secret confidentiel ABC123" not in _audit_dump(salon)

    def test_invalid_payload_persists_neither_campaign_nor_audit(
        self, _e2e_client: TestClient
    ) -> None:
        """Une validation domaine échouée (titre vide) ne laisse **aucune** trace."""
        token, salon = _setup_manager_salon(_e2e_client)
        resp = _create_campaign(_e2e_client, token, salon, title="   ")
        assert resp.status_code == 422, resp.text

        assert _count_campaigns_for_salon(salon) == 0
        assert _fetch_audit_rows(salon, "CAMPAIGN_CREATED") == []


# ─── E. Contraintes réelles du schéma (`CHECK`/FK) ───────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCampaignSchemaConstraintsE2E:
    """Les valeurs persistées respectent réellement les `CHECK`/FK de `campaigns`."""

    def test_all_campaign_types_are_accepted(self, _e2e_client: TestClient) -> None:
        token, salon = _setup_manager_salon(_e2e_client)
        for campaign_type in ("REMINDER", "PROMOTION", "EXCEPTIONAL_CLOSURE"):
            resp = _create_campaign(_e2e_client, token, salon, type=campaign_type)
            assert resp.status_code == 201, resp.text
            assert _fetch_campaign_row(resp.json()["id"])["type"] == campaign_type

    def test_all_campaign_segments_are_accepted(self, _e2e_client: TestClient) -> None:
        token, salon = _setup_manager_salon(_e2e_client)
        for segment in ("ALL", "FEMALE", "MALE", "OTHER"):
            resp = _create_campaign(_e2e_client, token, salon, segment=segment)
            assert resp.status_code == 201, resp.text
            assert _fetch_campaign_row(resp.json()["id"])["segment"] == segment


# ─── F. Round-trip de la migration 0009 ───────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestMigration0009RoundTripE2E:
    """`downgrade`/`upgrade` de la seule révision `0009` (table `campaigns`).

    `0009` est la tête de révision : `downgrade 0008` ne réverse qu'elle,
    `upgrade head` la ré-applique. Restaure `head` en `finally` pour ne laisser
    aucun effet de bord aux autres fichiers e2e du job.
    """

    def test_round_trip_recreates_campaigns_table(self) -> None:
        assert _table_present()

        try:
            down = _run_alembic("downgrade", "0008")
            assert down.returncode == 0, f"downgrade 0008 échoué : {down.stderr}"
            assert not _table_present()

            up = _run_alembic("upgrade", "head")
            assert up.returncode == 0, f"upgrade head échoué : {up.stderr}"
            assert _table_present()
        finally:
            restore = _run_alembic("upgrade", "head")
            assert restore.returncode == 0, f"restauration head échouée : {restore.stderr}"
