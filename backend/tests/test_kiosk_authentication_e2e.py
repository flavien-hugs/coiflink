"""Tests e2e — **cycle de vie complet de la borne kiosque** (US-8.1, #155).

Cette suite couvre les comportements qui traversent les frontières de composants et
ne peuvent pas être vérifiés par les tests unitaires ou les tests de matrice DB-free :

1. **Provisioning** : le gérant crée une borne via `POST /salons/{id}/kiosk-devices` ;
   le secret apparaît **une seule fois** dans la réponse `201` (argon2id réel en
   base, credential en clair non persisté).

2. **Authentification borne** : la borne échange `(device_id, secret)` contre une
   paire JWT via `POST /auth/kiosk/login` (argon2id + JwtTokenService réels).
   - La réponse porte le `salon_id` de la borne.
   - Le JWT émis porte le rôle `KIOSK`.

3. **Frontière de permission** (critère d'acceptation de l'issue) : le JWT `KIOSK` est
   **refusé** sur `CUSTOMER_MANAGE` (`POST /salons/{id}/customers`) et
   `APPOINTMENT_BOOK` (`POST /salons/{id}/appointments`). C'est l'exercice **e2e**
   du test RBAC négatif — la matrice DB-free (`test_security_authz_matrix.py`) vérifie
   le décodage + la logique RBAC sans base ; ce test exerce la pile complète.

4. **Secret non exposé** : `GET /salons/{id}/kiosk-devices` ne contient jamais de
   champ `secret` ni `password_hash`.

5. **Anti-oracle** : device inconnu, mauvais secret et device révoqué renvoient tous
   le **même** `401 Identifiants invalides.` — aucune information sur l'état interne.

6. **Révocation** : `DELETE /salons/{id}/kiosk-devices/{device_id}` suspend le compte
   de service ; le `/auth/kiosk/login` suivant renvoie **immédiatement** `401` (la
   relecture du statut fait autorité, ADR-0041/ADR-0015).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_kiosk_authentication_e2e.py -v

Nettoyage : plage de téléphones réservée `+225080999` pour le compte gérant.
Les bornes kiosque utilisent `uuid.hex` comme téléphone sentinelle (inatteignable
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
_TEST_JWT_SECRET = "test-only-kiosk-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e borne kiosque.
# Le `full_name` du device est `uuid.hex` (sentinelle), donc le nettoyage cible
# les salons dont le gérant a un numéro dans ce préfixe.
_E2E_PHONE_PREFIX = "+225080999"
_PHONE_MANAGER_LOCAL = "0809990001"
_PASSWORD = "kiosk-e2e-strong-password-2024"
_INVALID_CREDENTIALS_DETAIL = "Identifiants invalides."


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre FK-safe.

    Les bornes kiosque ont `users.phone = uuid.hex` (sentinelle) — elles ne sont
    **pas** atteignables par `phone LIKE :prefix`. Elles sont nettoyées en deux
    temps : d'abord collecte des IDs via `salon_members` (avant suppression),
    ensuite suppression des `users` kiosque une fois les FK levées.

    Ordre FK : audit_logs → salon_members (libère users + salons) → users kiosque
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

        # Collecte des IDs de bornes kiosque avant de supprimer `salon_members`.
        kiosk_rows = conn.execute(
            text(
                f"SELECT user_id FROM salon_members "
                f"WHERE salon_id IN ({salons_subq}) AND role = 'KIOSK'"
            ),
            params,
        ).fetchall()
        kiosk_user_ids = [row[0] for row in kiosk_rows]

        # 1. Journaux d'audit (FK : salon_id → salons, actor_user_id → users).
        conn.execute(
            text(
                f"DELETE FROM audit_logs WHERE salon_id IN ({salons_subq}) "
                f"OR actor_user_id IN ({users_subq})"
            ),
            params,
        )
        # Audit des bornes (actor = kiosk_user_id, salon figé par le FK salon_id).
        for kuid in kiosk_user_ids:
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

        # 3. Comptes de service kiosque (plus de salon_members → users FK maintenant).
        for kuid in kiosk_user_ids:
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
        pytest.skip("DATABASE_URL requis pour les tests e2e borne kiosque (#155).")

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)
    orig_kiosk_rate_limiter = getattr(main_app.state, "kiosk_login_rate_limiter", None)

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
    # Limiteur kiosque dédié aux tests — même paramétrage mais instance isolée.
    main_app.state.kiosk_login_rate_limiter = InMemoryLoginRateLimiter(
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
        main_app.state.kiosk_login_rate_limiter = orig_kiosk_rate_limiter


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _register_manager(client: TestClient) -> str:
    """Inscrit un gérant et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={
            "full_name": "Gérant Kiosk E2E",
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
        json={"name": "kiosk-e2e-salon", "phone": "0100000000"},
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
    """Provisionne une borne et retourne le corps `201` (inclut `secret`)."""
    resp = client.post(
        f"/salons/{salon_id}/kiosk-devices",
        json={"label": label},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 201, f"Provisioning échoué : {resp.text}"
    return resp.json()


def _kiosk_login(client: TestClient, device_id: str, secret: str) -> dict:
    """Authentifie une borne et retourne le corps de la réponse."""
    return client.post(
        "/auth/kiosk/login",
        json={"device_id": device_id, "secret": secret},
    )


# ─── Tests e2e (PostgreSQL requis) ────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestKioskProvisioningE2E:
    """Provisioning d'une borne par un gérant (pile HTTP + SQL + argon2 réels)."""

    def test_provision_returns_201(self, _e2e_client: TestClient) -> None:
        """Provisionner une borne → 201."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        resp = _e2e_client.post(
            f"/salons/{salon_id}/kiosk-devices",
            json={"label": "Borne A"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    def test_provision_response_contains_secret(self, _e2e_client: TestClient) -> None:
        """La réponse `201` porte le `secret` en clair — une seule fois."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        body = _provision_device(_e2e_client, token, salon_id)
        assert "secret" in body
        assert body["secret"]

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
            f"/salons/{salon_id}/kiosk-devices", json={"label": "Borne X"}
        )
        assert resp.status_code == 401

    def test_list_devices_does_not_expose_secret(self, _e2e_client: TestClient) -> None:
        """GET /kiosk-devices ne contient **jamais** de champ `secret` (§11.3).

        Le secret n'est communiqué qu'à la réponse `201` du provisioning : toute
        requête de liste renvoie `KioskDeviceResponse` sans ce champ.
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        _provision_device(_e2e_client, token, salon_id)

        resp = _e2e_client.get(
            f"/salons/{salon_id}/kiosk-devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        devices = resp.json()
        assert len(devices) >= 1
        for device in devices:
            assert "secret" not in device, (
                "Le secret ne doit jamais apparaître dans GET /kiosk-devices (§11.3)."
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
            f"/salons/{salon_id}/kiosk-devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        body_str = resp.text
        assert "password_hash" not in body_str
        assert "password" not in body_str


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestKioskLoginE2E:
    """Authentification borne via `POST /auth/kiosk/login` (argon2id + JWT réels)."""

    def test_kiosk_login_returns_200(self, _e2e_client: TestClient) -> None:
        """Credential valide → 200."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        resp = _kiosk_login(_e2e_client, device["id"], device["secret"])
        assert resp.status_code == 200

    def test_kiosk_login_response_contains_access_token(
        self, _e2e_client: TestClient
    ) -> None:
        """La réponse porte un `access_token` non vide."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        resp = _kiosk_login(_e2e_client, device["id"], device["secret"])
        body = resp.json()
        assert "access_token" in body
        assert body["access_token"]

    def test_kiosk_login_response_contains_salon_id(
        self, _e2e_client: TestClient
    ) -> None:
        """Le `salon_id` de la réponse de login correspond à celui de la borne.

        Mécanisme du jalon M7 : un APK unique pour toutes les bornes, la borne
        apprend son salon au provisioning (ADR-0041).
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        resp = _kiosk_login(_e2e_client, device["id"], device["secret"])
        assert resp.json().get("salon_id") == salon_id

    def test_kiosk_access_token_authenticates_as_kiosk_role(
        self, _e2e_client: TestClient
    ) -> None:
        """Le jeton d'accès émis est relisible et porte le rôle `KIOSK`.

        On vérifie indirectement via `GET /auth/me` : si le rôle relu en base
        est `KIOSK`, la garde `get_current_principal` a correctement résolu le
        compte de service.
        """
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        kiosk_resp = _kiosk_login(_e2e_client, device["id"], device["secret"])
        kiosk_token = kiosk_resp.json()["access_token"]

        me_resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {kiosk_token}"}
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["role"] == "KIOSK"

    def test_kiosk_access_token_has_correct_device_id(
        self, _e2e_client: TestClient
    ) -> None:
        """Le `id` retourné par `GET /auth/me` est l'UUID du device (pas d'un humain)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        kiosk_resp = _kiosk_login(_e2e_client, device["id"], device["secret"])
        kiosk_token = kiosk_resp.json()["access_token"]

        me_resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {kiosk_token}"}
        )
        assert me_resp.json()["id"] == device["id"]


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestKioskPermissionBoundaryE2E:
    """Le JWT `KIOSK` est **refusé** sur les routes qu'il ne peut pas utiliser.

    Critère d'acceptation de l'issue #155 : la borne ne peut obtenir ni
    `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK` complets. Ces tests exercent la **pile
    complète** (vrai JWT → garde → dépôt SQL réel) — non duplicata de la matrice
    DB-free qui teste uniquement le décodage et la logique RBAC sans base.
    """

    def _get_kiosk_token(
        self, client: TestClient, salon_id: str, manager_token: str
    ) -> str:
        device = _provision_device(client, manager_token, salon_id)
        resp = _kiosk_login(client, device["id"], device["secret"])
        return resp.json()["access_token"]

    def test_kiosk_cannot_manage_customers(self, _e2e_client: TestClient) -> None:
        """`POST /salons/{id}/customers` avec JWT KIOSK → `403 Accès refusé.`

        Le rôle `KIOSK` ne détient pas `CUSTOMER_MANAGE` (fiche complète, notes
        privées) — il ne dispose que de `CUSTOMER_LOOKUP_KIOSK` (recherche restreinte).
        ADR-0041, critère d'acceptation #155.
        """
        _register_manager(_e2e_client)
        manager_token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, manager_token)
        kiosk_token = self._get_kiosk_token(_e2e_client, salon_id, manager_token)

        resp = _e2e_client.post(
            f"/salons/{salon_id}/customers",
            json={"full_name": "Awa Koné", "phone": "0700000001"},
            headers={"Authorization": f"Bearer {kiosk_token}"},
        )
        assert resp.status_code == 403, (
            "KIOSK ne doit pas pouvoir créer une fiche client complète (CUSTOMER_MANAGE)."
        )
        assert resp.json().get("detail") == "Accès refusé."

    def test_kiosk_cannot_book_appointment(self, _e2e_client: TestClient) -> None:
        """`POST /salons/{id}/appointments` avec JWT KIOSK → `403 Accès refusé.`

        Le rôle `KIOSK` ne détient pas `APPOINTMENT_BOOK` (réservation au nom d'un
        compte client). ADR-0041, critère d'acceptation #155.
        """
        _register_manager(_e2e_client)
        manager_token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, manager_token)
        kiosk_token = self._get_kiosk_token(_e2e_client, salon_id, manager_token)

        resp = _e2e_client.post(
            f"/salons/{salon_id}/appointments",
            json={
                "date": "2026-12-01",
                "start_time": "09:00",
                "service_ids": [str(uuid.uuid4())],
            },
            headers={"Authorization": f"Bearer {kiosk_token}"},
        )
        assert resp.status_code == 403, (
            "KIOSK ne doit pas pouvoir réserver un rendez-vous (APPOINTMENT_BOOK)."
        )
        assert resp.json().get("detail") == "Accès refusé."

    def test_kiosk_cannot_provision_devices(self, _e2e_client: TestClient) -> None:
        """`POST /salons/{id}/kiosk-devices` avec JWT KIOSK → `403 Accès refusé.`

        Une borne ne peut pas provisionner d'autres bornes : `KIOSK_PROVISION` est
        réservé au `MANAGER`. ADR-0041 (moindre privilège).
        """
        _register_manager(_e2e_client)
        manager_token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, manager_token)
        kiosk_token = self._get_kiosk_token(_e2e_client, salon_id, manager_token)

        resp = _e2e_client.post(
            f"/salons/{salon_id}/kiosk-devices",
            json={"label": "Borne fantôme"},
            headers={"Authorization": f"Bearer {kiosk_token}"},
        )
        assert resp.status_code == 403, (
            "KIOSK ne doit pas pouvoir provisionner de nouvelles bornes (KIOSK_PROVISION)."
        )
        assert resp.json().get("detail") == "Accès refusé."


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestKioskRevocationE2E:
    """Révocation d'une borne : effet immédiat sur `/auth/kiosk/login` (ADR-0041/0015)."""

    def test_revocation_returns_200(self, _e2e_client: TestClient) -> None:
        """DELETE /kiosk-devices/{id} → 200 avec device révoqué."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        resp = _e2e_client.delete(
            f"/salons/{salon_id}/kiosk-devices/{device['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_revocation_sets_status_suspended(self, _e2e_client: TestClient) -> None:
        """La révocation pose `status = SUSPENDED` (suspension logique, §11.4)."""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        resp = _e2e_client.delete(
            f"/salons/{salon_id}/kiosk-devices/{device['id']}",
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
        device = _provision_device(_e2e_client, token, salon_id)

        # Vérifie que la borne peut se connecter avant révocation.
        pre_revoke = _kiosk_login(_e2e_client, device["id"], device["secret"])
        assert pre_revoke.status_code == 200

        # Révocation.
        _e2e_client.delete(
            f"/salons/{salon_id}/kiosk-devices/{device['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Après révocation, le login doit échouer avec le même 401 générique.
        post_revoke = _kiosk_login(_e2e_client, device["id"], device["secret"])
        assert post_revoke.status_code == 401
        assert post_revoke.json().get("detail") == _INVALID_CREDENTIALS_DETAIL


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestKioskAntiOracleE2E:
    """Anti-oracle : même `401` générique pour tout échec d'authentification borne.

    Critère ADR-0041/ADR-0026 : device inconnu, mauvais secret et device révoqué
    renvoient le **même** message sans divulguer l'existence ni l'état du device.
    """

    def test_unknown_device_returns_401(self, _e2e_client: TestClient) -> None:
        """Device non provisionné → `401 Identifiants invalides.`"""
        resp = _kiosk_login(_e2e_client, str(uuid.uuid4()), "fake-secret-not-provisioned")
        assert resp.status_code == 401
        assert resp.json().get("detail") == _INVALID_CREDENTIALS_DETAIL

    def test_wrong_secret_returns_401(self, _e2e_client: TestClient) -> None:
        """Mauvais secret → `401 Identifiants invalides.`"""
        _register_manager(_e2e_client)
        token = _login_manager(_e2e_client)
        salon_id = _create_salon(_e2e_client, token)
        device = _provision_device(_e2e_client, token, salon_id)

        resp = _kiosk_login(_e2e_client, device["id"], "wrong-secret-0000")
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
        device = _provision_device(_e2e_client, token, salon_id)

        _e2e_client.delete(
            f"/salons/{salon_id}/kiosk-devices/{device['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

        revoked_resp = _kiosk_login(_e2e_client, device["id"], device["secret"])
        unknown_resp = _kiosk_login(_e2e_client, str(uuid.uuid4()), "fake-secret")

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
        device = _provision_device(_e2e_client, token, salon_id)

        wrong_secret_resp = _kiosk_login(_e2e_client, device["id"], "wrong-secret")
        unknown_resp = _kiosk_login(_e2e_client, str(uuid.uuid4()), "fake-secret")

        assert wrong_secret_resp.json().get("detail") == unknown_resp.json().get("detail")

    def test_non_uuid_device_id_returns_401(self, _e2e_client: TestClient) -> None:
        """Un `device_id` non-UUID → `401` générique (pas de 422 qui divulguerait le rejet).

        La validation Pydantic rejette les `device_id` trop courts ou trop longs
        (bounds `min_length=1, max_length=64`), mais un UUID malformé dans les
        bornes de longueur doit produire un `401` générique côté cas d'usage.
        """
        resp = _kiosk_login(_e2e_client, "not-a-uuid-at-all-x", "some-secret")
        # Le cas d'usage convertit en UUID ; en cas d'échec, 401 générique (pas 422).
        assert resp.status_code == 401
        assert resp.json().get("detail") == _INVALID_CREDENTIALS_DETAIL
