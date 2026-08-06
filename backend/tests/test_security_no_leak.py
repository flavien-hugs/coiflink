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
