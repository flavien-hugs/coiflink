"""Tests e2e — **cycle de vie complet de la borne terminal** (US-8.1, #155).

Cette suite couvre les comportements qui traversent les frontières de composants et
ne peuvent pas être vérifiés par les tests unitaires ou les tests de matrice DB-free :

1. **Provisioning** : le gérant crée une borne via `POST /salons/{id}/terminal-devices` ;
   le **code d'activation à 6 chiffres** apparaît une seule fois dans la réponse
   `201` (argon2id réel en base sur un condensat *placeholder*, aucun secret utilisable
   n'existe encore).

2. **Activation** : la borne échange le code contre son secret longue durée via
   `POST /auth/terminal/activate` — secret **généré ici**, renvoyé une seule fois,
   jamais persisté en clair. Un code déjà utilisé, inconnu ou mal saisi échoue.

3. **Authentification borne** : une fois activée, la borne échange `(device_id,
   secret)` contre une paire JWT via `POST /auth/terminal/login` (argon2id +
   JwtTokenService réels, mécanisme **inchangé** par l'activation).
   - La réponse porte le `salon_id` de la borne.
   - Le JWT émis porte le rôle `TERMINAL`.
   - Une borne **non activée** ne peut pas se connecter (son condensat placeholder ne
     correspond à aucun secret connu).

4. **Frontière de permission** (critère d'acceptation de l'issue) : le JWT `TERMINAL` est
   **refusé** sur `CUSTOMER_MANAGE` (`POST /salons/{id}/customers`) et
   `TERMINAL_PROVISION` (`POST /salons/{id}/terminal-devices`, réservée au `MANAGER`).
   C'est l'exercice **e2e** du test RBAC négatif — la matrice DB-free
   (`test_security_authz_matrix.py`) vérifie le décodage + la logique RBAC sans base ;
   ce test exerce la pile complète.

5. **Secret et code non exposés** : `GET /salons/{id}/terminal-devices` ne contient
   jamais de champ `secret`, `activation_code` ni `password_hash`.

6. **Anti-oracle** : device inconnu, mauvais secret et device révoqué renvoient tous
   le **même** `401 Identifiants invalides.` — aucune information sur l'état interne.

7. **Révocation** : `DELETE /salons/{id}/terminal-devices/{device_id}` suspend le compte
   de service ; le `/auth/terminal/login` suivant renvoie **immédiatement** `401` (la
   relecture du statut fait autorité, ADR-0041/ADR-0015).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_terminal_authentication_e2e.py -v

Nettoyage : plage de téléphones réservée `+225080999` pour le compte gérant.
Les bornes terminal utilisent `uuid.hex` comme téléphone sentinelle (inatteignable
par les flux normaux) — elles sont nettoyées via leur appartenance aux salons de
test avant la suppression des salons.

Aucune PII, aucun secret de production. JWT signé avec un secret local de test.
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

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-terminal-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e borne terminal.
# Le `full_name` du device est `uuid.hex` (sentinelle), donc le nettoyage cible
# les salons dont le gérant a un numéro dans ce préfixe.
_E2E_PHONE_PREFIX = "+225080999"
_PHONE_MANAGER_LOCAL = "0809990001"
_PASSWORD = "terminal-e2e-strong-password-2024"
_INVALID_CREDENTIALS_DETAIL = "Identifiants invalides."


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre FK-safe.

    Les bornes terminal ont `users.phone = uuid.hex` (sentinelle) — elles ne sont
    **pas** atteignables par `phone LIKE :prefix`. Elles sont nettoyées en deux
    temps : d'abord collecte des IDs via `salon_members` (avant suppression),
    ensuite suppression des `users` terminal une fois les FK levées.

    Ordre FK : audit_logs → salon_members (libère users + salons) → users terminal
    → salons → users gérant.
    """
    engine = get_engine()
    salons_subq = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    users_subq = "SELECT id FROM users WHERE phone LIKE :prefix"
    with engine.connect() as conn:
        params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}

        # Collecte des IDs de bornes terminal avant de supprimer `salon_members`.
        terminal_rows = conn.execute(
            text(
                f"SELECT user_id FROM salon_members "
                f"WHERE salon_id IN ({salons_subq}) AND role = 'TERMINAL'"
            ),
            params,
        ).fetchall()
        terminal_user_ids = [row[0] for row in terminal_rows]

        # 1. Journaux d'audit (FK : salon_id → salons, actor_user_id → users).
        conn.execute(
            text(
                f"DELETE FROM audit_logs WHERE salon_id IN ({salons_subq}) "
                f"OR actor_user_id IN ({users_subq})"
            ),
            params,
        )
        # Audit des bornes (actor = terminal_user_id, salon figé par le FK salon_id).
        for kuid in terminal_user_ids:
            conn.execute(
                text("DELETE FROM audit_logs WHERE actor_user_id = :uid"),
                {"uid": kuid},
            )

        # 2. Membres de salon (FK : user_id → users, salon_id → salons).
        #    Supprime **tous** les membres (humains et bornes) des salons de test.
        conn.execute(
            text(
                f"DELETE FROM salon_members WHERE salon_id IN ({salons_subq}) "
                f"OR user_id IN ({users_subq})"
            ),
            params,
        )

        # 3. Comptes de service terminal (plus de salon_members → users FK maintenant).
        for kuid in terminal_user_ids:
            conn.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": kuid},
            )

        # 4. Salons (plus de FK salon_members → salons).
        conn.execute(
            text(f"DELETE FROM salons WHERE owner_id IN ({users_subq})"),
            params,
        )

        # 5. Comptes gérant.
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)

        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT réels).

    - Injecte des services de test locaux sur `app.state`.
    - Supprime les données de test (plage +225080999) avant et après chaque test.
    - Skip proprement si `DATABASE_URL` est absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e borne terminal (#155).")

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)
    orig_terminal_rate_limiter = getattr(main_app.state, "terminal_login_rate_limiter", None)

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
    # Limiteur terminal dédié aux tests — même paramétrage mais instance isolée.
    main_app.state.terminal_login_rate_limiter = InMemoryLoginRateLimiter(
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
        main_app.state.terminal_login_rate_limiter = orig_terminal_rate_limiter


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _register_manager(client: TestClient) -> str:
    """Inscrit un gérant et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={
            "full_name": "Gérant Terminal E2E",
            "phone": _PHONE_MANAGER_LOCAL,
            "password": _PASSWORD,
        },
    )
    assert resp.status_code == 201, f"Inscription échouée : {resp.text}"
    return resp.json()["id"]


def _login_manager(client: TestClient) -> str:
    """Connecte le gérant et retourne son access_token."""
    resp = client.post(
        "/auth/login",
        json={"identifier": _PHONE_MANAGER_LOCAL, "password": _PASSWORD},
    )
    assert resp.status_code == 200, f"Connexion gérant échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, manager_token: str) -> str:
    """Crée un salon de test et retourne son UUID."""
    resp = client.post(
        "/salons",
        json={"name": "terminal-e2e-salon", "phone": "0100000000"},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Création de salon échouée : {resp.text}"
    return resp.json()["id"]


def _provision_device(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    label: str = "Borne entrée E2E",
) -> dict:
    """Provisionne une borne et retourne le corps `201` (inclut `activation_code`,
    jamais de secret utilisable directement — voir `_activate_device`)."""
    resp = client.post(
        f"/salons/{salon_id}/terminal-devices",
        json={"label": label},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Provisioning échoué : {resp.text}"
    return resp.json()


def _activate_device(client: TestClient, activation_code: str) -> dict:
    """Active une borne via son code et retourne le corps `200` (`device_id`, `secret`)."""
    resp = client.post("/auth/terminal/activate", json={"code": activation_code})
    assert resp.status_code == 200, f"Activation échouée : {resp.text}"
    return resp.json()


def _provision_and_activate(
    client: TestClient,
    manager_token: str,
    salon_id: str,
    *,
    label: str = "Borne entrée E2E",
) -> dict:
    """Provisionne **et** active une borne ; retourne le corps du provisioning fusionné
    avec le `secret` réel (issu de l'activation) — mêmes clés que l'ancien flux à secret
    direct, pour que les appelants existants (`device["id"]`/`device["secret"]`) n'aient
    rien à changer d'autre que ce helper.
    """
    provisioned = _provision_device(client, manager_token, salon_id, label=label)
    activated = _activate_device(client, provisioned["activation_code"])
    assert activated["device_id"] == provisioned["id"], (
        "L'activation doit résoudre la même borne que celle provisionnée."
    )
    return {**provisioned, "secret": activated["secret"]}


def _terminal_login(client: TestClient, device_id: str, secret: str) -> dict:
    """Authentifie une borne et retourne le corps de la réponse."""
    return client.post(
        "/auth/terminal/login",
        json={"device_id": device_id, "secret": secret},
    )


# ─── Tests e2e (PostgreSQL requis) ────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestTerminalProvisioningE2E:
    """Provisioning d'une borne par un gérant (pile HTTP + SQL + argon2 réels)."""

    def test_provision_returns_201(self, _e2e_client: TestClient) -> None:
        """Provisionner une borne → 201."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        resp = _e2e_client.post(
            f"/salons/{salon_id}/terminal-devices",
            json={"label": "Borne A"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    def test_provision_response_contains_activation_code(
        self, _e2e_client: TestClient
    ) -> None:
        """La réponse `201` porte le code d'activation — une seule fois, jamais de secret."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        body = _provision_device(_e2e_client, token, salon_id)
        assert "activation_code" in body
        assert body["activation_code"]
        assert "secret" not in body, (
            "Le secret réel n'existe qu'à l'activation, jamais au provisioning."
        )

    def test_provision_response_activation_code_is_six_digits(
        self, _e2e_client: TestClient
    ) -> None:
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        body = _provision_device(_e2e_client, token, salon_id)
        assert len(body["activation_code"]) == 6
        assert body["activation_code"].isdigit()

    def test_provision_response_contains_device_id(self, _e2e_client: TestClient) -> None:
        """La réponse `201` porte un `id` UUID (identifiant de la borne)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        body = _provision_device(_e2e_client, token, salon_id)
        assert "id" in body
        # Valide que c'est bien un UUID bien formé.
        uuid.UUID(body["id"])

    def test_provision_response_salon_id_matches(self, _e2e_client: TestClient) -> None:
        """Le `salon_id` de la borne correspond à celui de la requête."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        body = _provision_device(_e2e_client, token, salon_id)
        assert body["salon_id"] == salon_id

    def test_provision_response_status_is_active(self, _e2e_client: TestClient) -> None:
        """Une borne fraîchement provisionnée a `status = ACTIVE`."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        body = _provision_device(_e2e_client, token, salon_id)
        assert body["status"] == "ACTIVE"

    def test_provision_without_token_returns_401(self, _e2e_client: TestClient) -> None:
        """Provisioning sans jeton → 401 (deny-by-default sur la pile réelle)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        resp = _e2e_client.post(
            f"/salons/{salon_id}/terminal-devices", json={"label": "Borne X"}
        )
        assert resp.status_code == 401

    def test_list_devices_does_not_expose_secret(self, _e2e_client: TestClient) -> None:
        """GET /terminal-devices ne contient **jamais** de champ `secret` (§11.3).

        Le secret n'est communiqué qu'à la réponse `201` du provisioning : toute
        requête de liste renvoie `TerminalDeviceResponse` sans ce champ.
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _provision_device(_e2e_client, token, salon_id)

        resp = _e2e_client.get(
            f"/salons/{salon_id}/terminal-devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        devices = resp.json()
        assert len(devices) >= 1
        for device in devices:
            assert "secret" not in device, (
                "Le secret ne doit jamais apparaître dans GET /terminal-devices (§11.3)."
            )
            assert "activation_code" not in device, (
                "Le code d'activation ne doit jamais apparaître dans GET /terminal-devices (§11.3)."
            )
            assert "password_hash" not in device

    def test_list_devices_does_not_expose_password_hash(
        self, _e2e_client: TestClient
    ) -> None:
        """Aucun condensat argon2 n'est exposé dans la liste."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _provision_device(_e2e_client, token, salon_id)

        resp = _e2e_client.get(
            f"/salons/{salon_id}/terminal-devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        body_str = resp.text
        assert "password_hash" not in body_str
        assert "password" not in body_str


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestTerminalLoginE2E:
    """Authentification borne via `POST /auth/terminal/login` (argon2id + JWT réels)."""

    def test_terminal_login_returns_200(self, _e2e_client: TestClient) -> None:
        """Credential valide → 200."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        resp = _terminal_login(_e2e_client, device["id"], device["secret"])
        assert resp.status_code == 200

    def test_terminal_login_response_contains_access_token(
        self, _e2e_client: TestClient
    ) -> None:
        """La réponse porte un `access_token` non vide."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        resp = _terminal_login(_e2e_client, device["id"], device["secret"])
        body = resp.json()
        assert "access_token" in body
        assert body["access_token"]

    def test_terminal_login_response_contains_salon_id(
        self, _e2e_client: TestClient
    ) -> None:
        """Le `salon_id` de la réponse de login correspond à celui de la borne.

        Mécanisme du jalon M7 : un APK unique pour toutes les bornes, la borne
        apprend son salon au provisioning (ADR-0041).
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        resp = _terminal_login(_e2e_client, device["id"], device["secret"])
        assert resp.json().get("salon_id") == salon_id

    def test_terminal_access_token_authenticates_as_terminal_role(
        self, _e2e_client: TestClient
    ) -> None:
        """Le jeton d'accès émis est relisible et porte le rôle `TERMINAL`.

        On vérifie indirectement via `GET /auth/me` : si le rôle relu en base
        est `TERMINAL`, la garde `get_current_principal` a correctement résolu le
        compte de service.
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        terminal_resp = _terminal_login(_e2e_client, device["id"], device["secret"])
        terminal_token = terminal_resp.json()["access_token"]

        me_resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {terminal_token}"}
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["role"] == "TERMINAL"

    def test_terminal_access_token_has_correct_device_id(
        self, _e2e_client: TestClient
    ) -> None:
        """Le `id` retourné par `GET /auth/me` est l'UUID du device (pas d'un humain)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        terminal_resp = _terminal_login(_e2e_client, device["id"], device["secret"])
        terminal_token = terminal_resp.json()["access_token"]

        me_resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {terminal_token}"}
        )
        assert me_resp.json()["id"] == device["id"]


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestTerminalPermissionBoundaryE2E:
    """Le JWT `TERMINAL` est **refusé** sur les routes qu'il ne peut pas utiliser.

    Critère d'acceptation de l'issue #155 : la borne ne peut obtenir ni
    `CUSTOMER_MANAGE` ni `TERMINAL_PROVISION`. Ces tests exercent la **pile
    complète** (vrai JWT → garde → dépôt SQL réel) — non duplicata de la matrice
    DB-free qui teste uniquement le décodage et la logique RBAC sans base.
    """

    def _get_terminal_token(
        self, client: TestClient, salon_id: str, manager_token: str
    ) -> str:
        device = _provision_and_activate(client, manager_token, salon_id)
        resp = _terminal_login(client, device["id"], device["secret"])
        return resp.json()["access_token"]

    def test_terminal_cannot_manage_customers(self, _e2e_client: TestClient) -> None:
        """`POST /salons/{id}/customers` avec JWT TERMINAL → `403 Accès refusé.`

        Le rôle `TERMINAL` ne détient pas `CUSTOMER_MANAGE` (fiche complète, notes
        privées) — il ne dispose que de `CUSTOMER_LOOKUP_TERMINAL` (recherche restreinte).
        ADR-0041, critère d'acceptation #155.
        """
        _register_manager(_e2e_client)
        manager_token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, manager_token)
        terminal_token = self._get_terminal_token(_e2e_client, salon_id, manager_token)

        resp = _e2e_client.post(
            f"/salons/{salon_id}/customers",
            json={"full_name": "Awa Koné", "phone": "0700000001"},
            headers={"Authorization": f"Bearer {terminal_token}"},
        )
        assert resp.status_code == 403, (
            "TERMINAL ne doit pas pouvoir créer une fiche client complète (CUSTOMER_MANAGE)."
        )
        assert resp.json().get("detail") == "Accès refusé."

    def test_terminal_cannot_provision_devices(self, _e2e_client: TestClient) -> None:
        """`POST /salons/{id}/terminal-devices` avec JWT TERMINAL → `403 Accès refusé.`

        Une borne ne peut pas provisionner d'autres bornes : `TERMINAL_PROVISION` est
        réservé au `MANAGER`. ADR-0041 (moindre privilège).
        """
        _register_manager(_e2e_client)
        manager_token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, manager_token)
        terminal_token = self._get_terminal_token(_e2e_client, salon_id, manager_token)

        resp = _e2e_client.post(
            f"/salons/{salon_id}/terminal-devices",
            json={"label": "Borne fantôme"},
            headers={"Authorization": f"Bearer {terminal_token}"},
        )
        assert resp.status_code == 403, (
            "TERMINAL ne doit pas pouvoir provisionner de nouvelles bornes (TERMINAL_PROVISION)."
        )
        assert resp.json().get("detail") == "Accès refusé."


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestTerminalRevocationE2E:
    """Révocation d'une borne : effet immédiat sur `/auth/terminal/login` (ADR-0041/0015)."""

    def test_revocation_returns_200(self, _e2e_client: TestClient) -> None:
        """DELETE /terminal-devices/{id} → 200 avec device révoqué."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        resp = _e2e_client.delete(
            f"/salons/{salon_id}/terminal-devices/{device['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_revocation_sets_status_suspended(self, _e2e_client: TestClient) -> None:
        """La révocation pose `status = SUSPENDED` (suspension logique, §11.4)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        resp = _e2e_client.delete(
            f"/salons/{salon_id}/terminal-devices/{device['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["status"] == "SUSPENDED"

    def test_revoked_device_cannot_login(self, _e2e_client: TestClient) -> None:
        """Une borne révoquée → `401` **immédiat** au login suivant.

        C'est le cœur du critère « ce qui est long est révocable » (ADR-0041) :
        la relecture du statut (`get_current_principal`) coupe l'accès dès la
        requête suivante, même si aucun JWT existant n'a expiré.
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        # Vérifie que la borne peut se connecter avant révocation.
        pre_revoke = _terminal_login(_e2e_client, device["id"], device["secret"])
        assert pre_revoke.status_code == 200

        # Révocation.
        _e2e_client.delete(
            f"/salons/{salon_id}/terminal-devices/{device['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Après révocation, le login doit échouer avec le même 401 générique.
        post_revoke = _terminal_login(_e2e_client, device["id"], device["secret"])
        assert post_revoke.status_code == 401
        assert post_revoke.json().get("detail") == _INVALID_CREDENTIALS_DETAIL


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestTerminalAntiOracleE2E:
    """Anti-oracle : même `401` générique pour tout échec d'authentification borne.

    Critère ADR-0041/ADR-0026 : device inconnu, mauvais secret et device révoqué
    renvoient le **même** message sans divulguer l'existence ni l'état du device.
    """

    def test_unknown_device_returns_401(self, _e2e_client: TestClient) -> None:
        """Device non provisionné → `401 Identifiants invalides.`"""
        resp = _terminal_login(_e2e_client, str(uuid.uuid4()), "fake-secret-not-provisioned")
        assert resp.status_code == 401
        assert resp.json().get("detail") == _INVALID_CREDENTIALS_DETAIL

    def test_wrong_secret_returns_401(self, _e2e_client: TestClient) -> None:
        """Mauvais secret → `401 Identifiants invalides.`"""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        resp = _terminal_login(_e2e_client, device["id"], "wrong-secret-0000")
        assert resp.status_code == 401
        assert resp.json().get("detail") == _INVALID_CREDENTIALS_DETAIL

    def test_revoked_device_returns_same_401_as_unknown(
        self, _e2e_client: TestClient
    ) -> None:
        """Device révoqué → **même** `401` que device inconnu (anti-oracle sur l'état).

        ADR-0026 exige l'indiscernabilité : ni l'existence ni le statut d'une borne
        ne doit être divulgué par le message d'erreur.
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        _e2e_client.delete(
            f"/salons/{salon_id}/terminal-devices/{device['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

        revoked_resp = _terminal_login(_e2e_client, device["id"], device["secret"])
        unknown_resp = _terminal_login(_e2e_client, str(uuid.uuid4()), "fake-secret")

        assert revoked_resp.status_code == 401
        assert unknown_resp.status_code == 401
        assert revoked_resp.json().get("detail") == unknown_resp.json().get("detail"), (
            "Le message d'erreur doit être identique pour un device révoqué et "
            "un device inconnu (anti-oracle sur l'état, ADR-0026)."
        )

    def test_wrong_secret_returns_same_detail_as_unknown_device(
        self, _e2e_client: TestClient
    ) -> None:
        """Mauvais secret → **même** `detail` que device inconnu (anti-oracle)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_and_activate(_e2e_client, token, salon_id)

        wrong_secret_resp = _terminal_login(_e2e_client, device["id"], "wrong-secret")
        unknown_resp = _terminal_login(_e2e_client, str(uuid.uuid4()), "fake-secret")

        assert wrong_secret_resp.json().get("detail") == unknown_resp.json().get("detail")

    def test_non_uuid_device_id_returns_401(self, _e2e_client: TestClient) -> None:
        """Un `device_id` non-UUID → `401` générique (pas de 422 qui divulguerait le rejet).

        La validation Pydantic rejette les `device_id` trop courts ou trop longs
        (bounds `min_length=1, max_length=64`), mais un UUID malformé dans les
        bornes de longueur doit produire un `401` générique côté cas d'usage.
        """
        resp = _terminal_login(_e2e_client, "not-a-uuid-at-all-x", "some-secret")
        # Le cas d'usage convertit en UUID ; en cas d'échec, 401 générique (pas 422).
        assert resp.status_code == 401
        assert resp.json().get("detail") == _INVALID_CREDENTIALS_DETAIL


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestActivateTerminalDeviceE2E:
    """Activation d'une borne par code à 6 chiffres (US-8.1, #155 — provisioning silencieux).

    Pile complète (HTTP + SQL + argon2 réels) : le provisioning ne pose qu'un
    condensat placeholder, l'activation génère et écrit le secret réel.
    """

    def test_full_round_trip_provision_activate_login(
        self, _e2e_client: TestClient
    ) -> None:
        """Provision → active → login réussit de bout en bout."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)

        provisioned = _provision_device(_e2e_client, token, salon_id)
        activated = _activate_device(_e2e_client, provisioned["activation_code"])
        login_resp = _terminal_login(_e2e_client, activated["device_id"], activated["secret"])

        assert login_resp.status_code == 200
        assert login_resp.json()["salon_id"] == salon_id

    def test_activation_response_device_id_matches_provisioned_device(
        self, _e2e_client: TestClient
    ) -> None:
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        provisioned = _provision_device(_e2e_client, token, salon_id)

        activated = _activate_device(_e2e_client, provisioned["activation_code"])
        assert activated["device_id"] == provisioned["id"]

    def test_unactivated_device_cannot_login(self, _e2e_client: TestClient) -> None:
        """Une borne provisionnée mais **non activée** ne peut pas se connecter.

        Le condensat posé au provisioning est un placeholder jetable : aucun secret
        ne le vérifie, donc `/auth/terminal/login` échoue déterministiquement — même
        401 générique que tout autre échec (anti-oracle).
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        provisioned = _provision_device(_e2e_client, token, salon_id)

        # Aucun secret connu à ce stade : tenter n'importe quelle valeur doit échouer.
        resp = _terminal_login(_e2e_client, provisioned["id"], "any-guessed-secret")
        assert resp.status_code == 401
        assert resp.json().get("detail") == _INVALID_CREDENTIALS_DETAIL

    def test_reusing_activation_code_fails(self, _e2e_client: TestClient) -> None:
        """Un code déjà consommé ne peut plus être échangé (usage unique, §11.3)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        provisioned = _provision_device(_e2e_client, token, salon_id)

        first = _e2e_client.post(
            "/auth/terminal/activate", json={"code": provisioned["activation_code"]}
        )
        assert first.status_code == 200

        second = _e2e_client.post(
            "/auth/terminal/activate", json={"code": provisioned["activation_code"]}
        )
        assert second.status_code == 400

    def test_unknown_activation_code_returns_400(self, _e2e_client: TestClient) -> None:
        resp = _e2e_client.post("/auth/terminal/activate", json={"code": "000000"})
        assert resp.status_code == 400

    def test_activating_with_previous_secret_after_reactivation_fails(
        self, _e2e_client: TestClient
    ) -> None:
        """Le secret émis à l'activation n'est **jamais** relisible ni réémis :

        un deuxième appel avec le même code (déjà consommé) ne renvoie jamais un
        secret, quelle que soit la tentative — cohérent avec `test_reusing_activation_code_fails`,
        vérifié ici via l'absence de `secret` dans une réponse `400`.
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        provisioned = _provision_device(_e2e_client, token, salon_id)
        _activate_device(_e2e_client, provisioned["activation_code"])

        second = _e2e_client.post(
            "/auth/terminal/activate", json={"code": provisioned["activation_code"]}
        )
        assert "secret" not in second.json()
