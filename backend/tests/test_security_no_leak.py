"""Invariants transverses de **non-divulgation** (#51, §11.1/§11.3).

Deux familles d'invariants, statiques et DB-free (gate ADW) :

1. **Liste blanche `PUBLIC_ROUTE_PATHS`** figée en régression : ouvrir une route à
   Internet est une décision de sécurité revue (ADR-0015). Toute route financière
   (`/me/receipts*`, `*/payments`), toute donnée personnelle (`*/customers`) et
   toute route de supervision (`/admin/*`) doit rester **hors** de la liste. Le
   test échoue si un chemin est ajouté sans mettre à jour l'ensemble attendu.
2. **Schémas de réponse d'auth sans secret** : `UserResponse` / `TokenResponse`
   n'exposent jamais `password`, `password_hash` ni la clé de signature `JWT_SECRET`.

L'invariant append-only de la caisse (§8.2 — aucun verbe destructif sur
`/payments` ou `/cash-journal`) et l'invariant deny-by-default
(`unprotected_routes(app) == []`) sont déjà couverts par `test_security_guards.py`
(`test_no_destructive_routes_for_payments_or_cash_journal`,
`test_no_unprotected_routes`) : on ne les duplique pas, on s'y adosse.
"""

from __future__ import annotations

import pytest

from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    is_public_path,
    iter_api_routes,
)
from coiflink_api.main import app as main_app

# Ensemble **attendu** des chemins publics (deny-by-default : tout le reste est fermé).
# Modifier cet ensemble est une décision de sécurité — le test de régression l'impose.
_EXPECTED_PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/auth/register",
        "/auth/register/manager",
        "/auth/login",
        "/auth/refresh",
        # Authentification d'une borne terminal (#155, US-8.1) — endpoint d'auth,
        # rate-limité, `401` générique constant (ADR-0041). Le provisioning des
        # bornes (`/salons/{id}/terminal-devices`) reste protégé, jamais public.
        "/auth/terminal/login",
        # Activation d'une borne (#155, US-8.1) — endpoint d'**échange** : une borne
        # non activée n'a aucun credential à présenter. Code à usage unique, rate-limité
        # par IP, `400` générique constant (ADR-0041). Le provisioning des bornes
        # (`/salons/{id}/terminal-devices`) reste protégé, jamais public.
        "/auth/terminal/activate",
        "/auth/password/reset/request",
        "/auth/password/reset/confirm",
        "/catalog/salons",
        "/catalog/salons/{salon_id}",
        "/catalog/salons/{salon_id}/availability",
    }
)

# Familles de chemins qui ne doivent **jamais** être publiques (finances / PII / admin).
_NEVER_PUBLIC_SUBSTRINGS = ("/payments", "/customers", "/admin", "/me/receipts", "/cash-journal")


# --------------------------------------------------------------------------- #
# 1. PUBLIC_ROUTE_PATHS — régression + invariants de familles sensibles.
# --------------------------------------------------------------------------- #
def test_public_route_paths_matches_expected_set() -> None:
    """La liste blanche est **exactement** l'ensemble attendu (régression stricte)."""

    assert set(PUBLIC_ROUTE_PATHS) == set(_EXPECTED_PUBLIC_PATHS), (
        "PUBLIC_ROUTE_PATHS a changé : toute ouverture de route exige une revue de "
        "sécurité (ADR-0015). Mettez à jour _EXPECTED_PUBLIC_PATHS en conscience."
    )


@pytest.mark.parametrize("substring", _NEVER_PUBLIC_SUBSTRINGS)
def test_no_sensitive_family_is_public(substring: str) -> None:
    """Aucune route finance/PII/admin ne figure dans la liste blanche."""

    offending = [path for path in PUBLIC_ROUTE_PATHS if substring in path]
    assert offending == [], (
        f"Chemin sensible ({substring}) trouvé dans PUBLIC_ROUTE_PATHS : {offending}"
    )


def test_all_public_paths_are_read_only_or_auth() -> None:
    """Chaque chemin public est une lecture catalogue, la sonde, ou une route d'auth.

    Garde-fou lisible : la liste blanche ne mélange jamais une ressource de gestion
    avec les seules surfaces destinées à un accès non authentifié.
    """

    for path in PUBLIC_ROUTE_PATHS:
        assert (
            path == "/health"
            or path.startswith("/auth/")
            or path.startswith("/catalog/")
        ), f"Chemin public inattendu (hors health/auth/catalog) : {path}"


def test_sensitive_real_routes_are_not_public() -> None:
    """Sur `main.app`, toute route finance/PII/admin réelle est **protégée**.

    Complète l'invariant statique : on énumère les routes **effectivement montées**
    et on vérifie qu'aucune de ces familles n'est reconnue publique par
    `is_public_path` (un `/me/receipts` public serait un oracle financier, §11.3).
    """

    leaking: list[str] = []
    for route in iter_api_routes(main_app):
        path = route.path
        if any(sub in path for sub in _NEVER_PUBLIC_SUBSTRINGS) and is_public_path(path):
            leaking.append(path)
    assert leaking == [], f"Routes sensibles exposées comme publiques : {leaking}"


# --------------------------------------------------------------------------- #
# 2. Schémas de réponse d'auth — jamais de secret.
# --------------------------------------------------------------------------- #
_SECRET_FIELD_NAMES = {"password", "password_hash", "jwt_secret", "secret", "hash"}


def test_user_response_exposes_no_secret_field() -> None:
    """`UserResponse` ne déclare aucun champ secret (ni `password`, ni `password_hash`)."""

    from coiflink_api.adapters.inbound.auth import UserResponse

    fields = set(UserResponse.model_fields)
    assert fields.isdisjoint(_SECRET_FIELD_NAMES), (
        f"UserResponse expose un champ secret : {fields & _SECRET_FIELD_NAMES}"
    )


def test_token_response_exposes_no_signing_secret() -> None:
    """`TokenResponse` porte les jetons émis, **jamais** la clé de signature ni un mot de passe."""

    from coiflink_api.adapters.inbound.auth import TokenResponse

    fields = set(TokenResponse.model_fields)
    for forbidden in ("jwt_secret", "secret", "password", "password_hash"):
        assert forbidden not in fields, f"TokenResponse expose {forbidden}."


def test_message_response_carries_only_a_detail() -> None:
    """`MessageResponse` (reset) ne transporte qu'un `detail` générique — aucun secret."""

    from coiflink_api.adapters.inbound.auth import MessageResponse

    assert set(MessageResponse.model_fields) == {"detail"}


# --------------------------------------------------------------------------- #
# 3. Schémas de réponse bornes terminal — §11.3 (US-8.1, #155)
# --------------------------------------------------------------------------- #

def test_terminal_device_response_has_no_secret_field() -> None:
    """`TerminalDeviceResponse` (GET/DELETE) ne déclare aucun champ secret (§11.3).

    La vue publique exposée sur les routes `GET`/`DELETE` ne porte **jamais** le
    secret de device ni son condensat — seul le `TerminalActivateResponse`
    (`POST /auth/terminal/activate`) peut exposer `secret`, et uniquement lors de
    l'activation (usage unique).
    """

    from coiflink_api.adapters.inbound.terminal_devices import TerminalDeviceResponse

    fields = set(TerminalDeviceResponse.model_fields)
    for forbidden in ("secret", "password_hash", "hash"):
        assert forbidden not in fields, (
            f"TerminalDeviceResponse expose le champ sensible « {forbidden} »."
        )


def test_provision_terminal_response_has_activation_code_but_no_secret_or_hash() -> None:
    """`ProvisionTerminalDeviceResponse` (`POST 201`) expose `activation_code`, jamais le secret ni le condensat.

    Le secret réel n'existe qu'après activation (`POST /auth/terminal/activate`,
    `TerminalActivateResponse`) — le provisioning ne révèle qu'un code d'activation
    à usage unique, jamais un secret directement utilisable pour `/auth/terminal/login`.
    """

    from coiflink_api.adapters.inbound.terminal_devices import ProvisionTerminalDeviceResponse

    fields = set(ProvisionTerminalDeviceResponse.model_fields)
    assert "activation_code" in fields, (
        "Le code d'activation doit figurer dans la réponse 201 (provisioning)."
    )
    assert "secret" not in fields, (
        "Le secret ne doit jamais être révélé au provisioning — seulement après activation."
    )
    assert "password_hash" not in fields, (
        "Le condensat argon2id ne doit jamais être exposé dans un schéma de réponse."
    )


def test_terminal_activate_response_has_secret_but_no_hash() -> None:
    """`TerminalActivateResponse` (`POST /auth/terminal/activate`) expose `secret` mais jamais le condensat.

    Le secret réel n'apparaît **qu'ici, une seule fois** (invariant de non-relecture) —
    généré à l'activation, jamais reconstruit ni relu ensuite.
    """

    from coiflink_api.adapters.inbound.auth import TerminalActivateResponse

    fields = set(TerminalActivateResponse.model_fields)
    assert "secret" in fields, "Le secret doit figurer dans la réponse d'activation."
    assert "password_hash" not in fields, (
        "Le condensat argon2id ne doit jamais être exposé dans un schéma de réponse."
    )


def test_terminal_provision_path_is_not_public() -> None:
    """`/salons/{salon_id}/terminal-devices` est **protégée** — jamais dans la liste blanche.

    Le provisioning des bornes exige `TERMINAL_PROVISION` (gérant uniquement) : le
    chemin ne peut pas figurer dans `PUBLIC_ROUTE_PATHS` (deny-by-default, ADR-0015).
    """

    from coiflink_api.adapters.inbound.security import is_public_path

    assert not is_public_path("/salons/{salon_id}/terminal-devices"), (
        "Le provisioning des bornes ne doit jamais être accessible publiquement."
    )


def test_terminal_login_path_is_public_and_auth_family() -> None:
    """`/auth/terminal/login` est bien dans la liste blanche (endpoint d'auth, rate-limité).

    Cette route est l'**unique** entrée publique liée aux bornes : le device échange
    son credential longue durée contre une paire JWT courte. Elle est déjà couverte
    par `test_public_route_paths_matches_expected_set` — on confirme ici l'invariant
    de famille (`/auth/…`) au niveau des bornes.
    """

    from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS, is_public_path

    assert "/auth/terminal/login" in PUBLIC_ROUTE_PATHS
    assert is_public_path("/auth/terminal/login")
