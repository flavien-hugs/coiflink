"""Tests e2e des **parcours critiques** de bout en bout (#50, PRD §5).

Ce fichier *stitche* les briques déjà livrées et testées séparément (catalogue
public #15, file d'attente walk-in #148/#157, gestion des employés #150/#152,
fiches clients #28/#29/#32, encaissement #33/#35, journal de caisse #34, CA
#40, reçus #38) en **trois parcours continus** partagés — le **même** salon,
la **même** fiche ou le **même** ticket — pour attraper les régressions
d'**intégration inter-modules** qui passent entre les mailles des suites
par-fonctionnalité (un ticket `done` absent de l'historique de la fiche, un
paiement qui ne fait pas monter le CA, un reçu introuvable après encaissement).

**Pivot walk-in exclusif (#148).** Le module Rendez-vous (réservation à
l'avance, créneaux, notifications de confirmation/rappel) a été **retiré du
backend** — domaine, application, adapters et tables (`appointments`,
`appointment_services`, `notifications`) supprimés par la migration `0017`.
Le **seul** modèle de service du produit est désormais le **ticket de
passage walk-in** (`queue_tickets`) : un client entre au salon, une borne
(rôle `TERMINAL`) lui délivre un ticket, une coiffeuse le prend en charge puis
le clôture — aucune réservation à l'avance, aucun créneau, aucune notification
programmée. Ce fichier a été **réécrit** en conséquence ; deux invariants de
l'ancienne version n'ont **aucun équivalent** dans le modèle walk-in (voir
détail dans les docstrings de classe ci-dessous) :

- la vérification des **notifications tracées** (confirmation + rappels en
  base) : le module notifications-de-RDV a disparu **entièrement** avec la
  table qui le portait — un ticket walk-in ne programme ni ne confirme rien ;
- la lecture de **disponibilités** (`GET /catalog/salons/{id}/availability`,
  créneau futur `_next_monday`) : un ticket walk-in est délivré **maintenant**,
  il n'y a plus de créneau à consulter à l'avance.

Les trois classes (PostgreSQL requis) exercent la **pile HTTP réelle**
(`TestClient` → routers → cas d'usage → dépôts SQL → PostgreSQL), miroir strict
du patron `test_terminal_authentication_e2e.py`/`test_customer_e2e.py` :

- `TestQueueJourneyE2E` (**§5.1 walk-in, équivalent réservation client**) :
  catalogue → fiche (prestation active, prix) → fiche client créée par le
  gérant → **borne** (`TERMINAL` provisionnée/activée) délivre un ticket
  `waiting` pour cette fiche → prise en charge (assignation coiffeuse,
  `in_progress`) → clôture (`done`) → la visite figure dans l'**historique de
  la fiche** (`GET /customers/{id}/visits`), montant figé.
- `TestManagerQueueJourneyE2E` (**§5.2 gestion de la file gérant**) : file du
  jour (`waiting`) → prise en charge (assignation coiffeuse, `in_progress`,
  décompte mis à jour) → clôture (`done`) → encaissement → **CA du jour ↑** →
  le paiement figure dans l'**historique des paiements de la fiche**
  (`GET /customers/{id}/payments`).
- `TestCheckoutJourneyE2E` (**§5.3 encaissement**) : depuis un ticket `done`,
  un **montant incohérent** → `422` **sans écriture** (§8.2/§11.4, atomicité),
  puis le **bon montant** (lié à un **client** enregistré via `client_id`) →
  `201` `VALIDATED` → **une** ligne `PAYMENT` au journal (#34) + historique des
  transactions (#35) → **dashboard CA** (#40) → **reçu client** (#38)
  récupérable, un `payment_id` d'un tiers restant `404` neutre (§11.2).

Périmètre (spec `specs/tests-e2e-parcours-critiques.md`) : **aucune
modification du code de production**. Les parcours vérifient la **continuité
inter-modules** (les données produites par une étape sont bien consommées par
la suivante) et **un** chemin d'erreur structurant par parcours ; la
couverture fine des branches d'erreur et de l'authz reste dans les suites
par-fonctionnalité et #51. Au plus un `401` deny-by-default et un `404`
neutre d'appartenance par parcours, sans dupliquer #51.

**Deux identités client distinctes, délibérément non confondues.** Le modèle
walk-in porte **deux** notions indépendantes de « client » :
- la **fiche** (`customer_profiles`, créée par le gérant/la borne, jamais liée
  à un compte — `user_id` vaut toujours `NULL`) : c'est elle qui porte
  l'historique des visites/paiements **côté salon** (§5.1/§5.2 ci-dessus) ;
- le **compte client enregistré** (`users`, rôle `CLIENT`, `POST
  /auth/register`) : il ne peut **plus** réserver ni rejoindre la file
  lui-même (seule la borne `TERMINAL` détient `QUEUE_TICKET_CREATE`), mais il
  peut être **rattaché à un paiement** (`payments.client_id`) et consulter
  **ses** reçus (`GET /me/receipts`, §5.3 ci-dessus).

Ces deux parcours (§5.1/§5.2 côté fiche, §5.3 côté compte client) exercent
donc deux jointures SQL distinctes et complémentaires, plutôt que de dupliquer
la même vérification trois fois.

**Argent** : `NUMERIC(12,2)` sérialisé **en chaîne** (`"5000.00"`), jamais un
flottant.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_critical_journeys_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225068999xxxx). Ordre FK-safe (miroir
`test_hairdresser_performance_e2e.py`/`test_terminal_authentication_e2e.py`) :
`audit_logs` → `cash_journal` → `payments` → `queue_ticket_services` →
`queue_tickets` → `customer_profiles` → `services` → `salon_members` (libère
les comptes humains **et** la borne terminal) → comptes de service terminal
(téléphone sentinelle `uuid.hex`, hors plage réservée) → `salons` → `users`.
"""

from __future__ import annotations

import datetime
import decimal
import os
import uuid
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

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-critical-journeys-e2e-jwt-secret-not-for-production"

# Plage de numéros **réservée** aux parcours critiques (confirmée libre à
# l'implémentation : aucun autre `*_e2e.py` ne l'utilise, évitant les collisions de
# nettoyage entre suites partageant la même base CI).
_E2E_PHONE_PREFIX = "+225068999"
_PHONE_MANAGER_LOCAL = "0689990001"      # gérant (propriétaire du salon)
_PHONE_HAIRDRESSER_LOCAL = "0689990002"  # coiffeur (prise en charge §5.1/§5.2)
_PHONE_CLIENT_A_LOCAL = "0689990003"     # compte client — acteur principal du reçu (§5.3)
_PHONE_CLIENT_B_LOCAL = "0689990004"     # compte client tiers — appartenance du reçu (§5.3)
_PASSWORD = "critical-journeys-e2e-strong-password-2024"

_SALON_NAME = "e2e-salon-critical-journeys"
_SERVICE_NAME = "Coupe E2E Parcours"
_SERVICE_PRICE = "5000.00"
_SERVICE_DURATION = 30
_VALID_HOURS = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → cash_journal → payments → queue_ticket_services →
    queue_tickets → customer_profiles → services → salon_members → comptes de
    service terminal → salons → users. La borne terminal (rôle `TERMINAL`) a un
    `users.phone` **sentinelle** (`uuid.hex`, hors plage réservée) — elle est
    collectée via `salon_members` **avant** que ce dernier ne soit vidé (miroir
    `test_terminal_authentication_e2e.py`), puis supprimée explicitement.
    """
    engine = get_engine()
    salons_of_prefix = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    users_of_prefix = "SELECT id FROM users WHERE phone LIKE :prefix"
    with engine.connect() as conn:
        params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}

        # Collecte des comptes de service terminal avant de vider `salon_members`.
        terminal_rows = conn.execute(
            text(
                f"SELECT user_id FROM salon_members "
                f"WHERE salon_id IN ({salons_of_prefix}) AND role = 'TERMINAL'"
            ),
            params,
        ).fetchall()
        terminal_user_ids = [row[0] for row in terminal_rows]

        conn.execute(
            text(
                f"DELETE FROM audit_logs WHERE salon_id IN ({salons_of_prefix}) "
                f"OR actor_user_id IN ({users_of_prefix})"
            ),
            params,
        )
        for kuid in terminal_user_ids:
            conn.execute(
                text("DELETE FROM audit_logs WHERE actor_user_id = :uid"),
                {"uid": kuid},
            )
        conn.execute(
            text(f"DELETE FROM cash_journal WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(f"DELETE FROM payments WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM queue_ticket_services WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM queue_tickets WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM customer_profiles WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM services WHERE salon_id IN ({salons_of_prefix})"),
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
            text("DELETE FROM salons WHERE owner_id IN (" + users_of_prefix + ")"),
            params,
        )
        # Comptes de service terminal (téléphone sentinelle, hors plage réservée) :
        # aucune FK ne les rattache à `salons`, ils peuvent partir après elle.
        for kuid in terminal_user_ids:
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": kuid})
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT).

    - Injecte un JwtTokenService de test (secret local, jamais en production) sur app.state.
    - Injecte les limiteurs de tentatives de connexion humaine **et** borne terminal.
    - Supprime les données de test (plage +225068999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip(
            "DATABASE_URL requis pour les tests e2e des parcours critiques."
        )

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)
    orig_terminal_rate_limiter = getattr(
        main_app.state, "terminal_login_rate_limiter", None
    )

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


# ─── Helpers HTTP (via les endpoints réels) ──────────────────────────────────


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(client: TestClient, path: str, *, phone: str, full_name: str) -> str:
    """Inscrit un compte (`/auth/register` ou `/auth/register/manager`) → UUID."""
    resp = client.post(
        path, json={"full_name": full_name, "phone": phone, "password": _PASSWORD}
    )
    assert resp.status_code == 201, f"Inscription échouée ({phone}) : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str) -> str:
    """Connecte un compte et retourne l'access token."""
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée ({phone}) : {resp.text}"
    return resp.json()["access_token"]


def _provision_terminal_device(client: TestClient, manager_token: str, salon_id: str) -> dict:
    """`POST /salons/{id}/terminal-devices` — provisionne la borne du salon (#155)."""
    resp = client.post(
        f"/salons/{salon_id}/terminal-devices",
        json={"label": "Borne E2E Parcours Critiques"},
        headers=_auth(manager_token),
    )
    assert resp.status_code == 201, f"Provisioning de la borne échoué : {resp.text}"
    return resp.json()


def _activate_terminal_device(client: TestClient, activation_code: str) -> dict:
    """`POST /auth/terminal/activate` — échange le code contre le secret réel."""
    resp = client.post("/auth/terminal/activate", json={"code": activation_code})
    assert resp.status_code == 200, f"Activation de la borne échouée : {resp.text}"
    return resp.json()


def _terminal_login(client: TestClient, device_id: str, secret: str) -> str:
    """`POST /auth/terminal/login` — retourne l'access token de la borne."""
    resp = client.post(
        "/auth/terminal/login", json={"device_id": device_id, "secret": secret}
    )
    assert resp.status_code == 200, f"Connexion de la borne échouée : {resp.text}"
    return resp.json()["access_token"]


def _provision_and_login_terminal(
    client: TestClient, manager_token: str, salon_id: str
) -> str:
    """Provisionne + active + connecte une borne du salon → access token `TERMINAL`.

    Cycle de vie complet déjà couvert en détail par
    `test_terminal_authentication_e2e.py` ; ici, on ne fait que **l'emprunter**
    pour obtenir un jeton `TERMINAL` capable de délivrer un ticket walk-in
    (`QUEUE_TICKET_CREATE`, seul rôle qui la détient).
    """
    provisioned = _provision_terminal_device(client, manager_token, salon_id)
    activated = _activate_terminal_device(client, provisioned["activation_code"])
    return _terminal_login(client, activated["device_id"], activated["secret"])


def _create_customer_profile(
    client: TestClient, token: str, salon_id: str, *, full_name: str = "Cliente Walk-in E2E"
) -> str:
    """`POST /salons/{id}/customers` — fiche walk-in créée par le gérant (#28)."""
    resp = client.post(
        f"/salons/{salon_id}/customers",
        json={"full_name": full_name},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"Création de la fiche échouée : {resp.text}"
    return resp.json()["id"]


def _join_queue(
    client: TestClient,
    terminal_token: str,
    salon_id: str,
    *,
    service_ids: list[str],
    customer_profile_id: str | None = None,
) -> object:
    """`POST /salons/{id}/queue/tickets` — la borne délivre un ticket `waiting` (#157)."""
    body: dict[str, object] = {"service_ids": service_ids}
    if customer_profile_id is not None:
        body["customer_profile_id"] = customer_profile_id
    return client.post(
        f"/salons/{salon_id}/queue/tickets", json=body, headers=_auth(terminal_token)
    )


def _list_queue(client: TestClient, token: str, salon_id: str) -> dict:
    """`GET /salons/{id}/queue/tickets` — file du jour (défaut aujourd'hui, #157)."""
    resp = client.get(f"/salons/{salon_id}/queue/tickets", headers=_auth(token))
    assert resp.status_code == 200, f"Lecture de la file échouée : {resp.text}"
    return resp.json()


def _status_counts(listing: dict) -> dict[str, int]:
    """Décompte des tickets de la file par statut (équivalent local du défunt `by_status`)."""
    counts: dict[str, int] = {}
    for item in listing["items"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def _start_ticket(
    client: TestClient, token: str, salon_id: str, ticket_id: str, hairdresser_id: str
) -> object:
    """`POST /salons/{id}/queue/tickets/{id}/start` — prise en charge (#157)."""
    return client.post(
        f"/salons/{salon_id}/queue/tickets/{ticket_id}/start",
        json={"hairdresser_id": hairdresser_id},
        headers=_auth(token),
    )


def _complete_ticket(client: TestClient, token: str, salon_id: str, ticket_id: str) -> object:
    """`POST /salons/{id}/queue/tickets/{id}/complete` — clôture (#157)."""
    return client.post(
        f"/salons/{salon_id}/queue/tickets/{ticket_id}/complete", headers=_auth(token)
    )


def _cancel_ticket(
    client: TestClient, token: str, salon_id: str, ticket_id: str, *, reason: str
) -> object:
    """`POST /salons/{id}/queue/tickets/{id}/cancel` — annulation manuelle, no-show."""
    return client.post(
        f"/salons/{salon_id}/queue/tickets/{ticket_id}/cancel",
        json={"reason": reason},
        headers=_auth(token),
    )


def _record_payment(
    client: TestClient,
    token: str,
    salon_id: str,
    *,
    amount: str,
    queue_ticket_id: str,
    client_id: str | None = None,
    payment_method: str = "CASH",
) -> object:
    """`POST /salons/{id}/payments` — encaissement d'un ticket walk-in (gérant, #33)."""
    body: dict[str, object] = {
        "amount": amount,
        "payment_method": payment_method,
        "queue_ticket_id": queue_ticket_id,
    }
    if client_id is not None:
        body["client_id"] = client_id
    return client.post(f"/salons/{salon_id}/payments", json=body, headers=_auth(token))


def _revenue_summary(client: TestClient, token: str, salon_id: str) -> dict:
    """`GET /salons/{id}/revenue/summary` (CA, #40) — `date` omis = aujourd'hui.

    Le CA dérive de `cash_journal.created_at` (l'instant de l'encaissement) —
    la fenêtre du jour est **aujourd'hui**, cohérente avec un ticket délivré et
    encaissé le jour même (walk-in, aucun créneau différé).
    """
    resp = client.get(
        f"/salons/{salon_id}/revenue/summary", headers=_auth(token)
    )
    assert resp.status_code == 200, f"CA échoué : {resp.text}"
    return resp.json()


def _list_transactions(client: TestClient, token: str, salon_id: str) -> dict:
    """`GET /salons/{id}/payments` (historique des transactions, #35)."""
    resp = client.get(f"/salons/{salon_id}/payments", headers=_auth(token))
    assert resp.status_code == 200, f"Historique des transactions échoué : {resp.text}"
    return resp.json()


def _customer_visits(client: TestClient, token: str, salon_id: str, customer_id: str) -> dict:
    """`GET /salons/{id}/customers/{id}/visits` — historique des visites de la fiche (#29)."""
    resp = client.get(
        f"/salons/{salon_id}/customers/{customer_id}/visits", headers=_auth(token)
    )
    assert resp.status_code == 200, f"Historique des visites échoué : {resp.text}"
    return resp.json()


def _customer_payments(client: TestClient, token: str, salon_id: str, customer_id: str) -> dict:
    """`GET /salons/{id}/customers/{id}/payments` — historique des paiements de la fiche."""
    resp = client.get(
        f"/salons/{salon_id}/customers/{customer_id}/payments", headers=_auth(token)
    )
    assert resp.status_code == 200, f"Historique des paiements échoué : {resp.text}"
    return resp.json()


def _list_receipts(client: TestClient, token: str) -> dict:
    """`GET /me/receipts` (reçus du **compte client**, #38)."""
    resp = client.get("/me/receipts", headers=_auth(token))
    assert resp.status_code == 200, f"Liste des reçus échouée : {resp.text}"
    return resp.json()


# ─── Helpers SQL (lecture directe pour asserter la persistance) ──────────────


def _count_payments(salon_id: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM payments WHERE salon_id = :sid"),
            {"sid": salon_id},
        ).scalar_one()


def _count_cash_journal(salon_id: str, operation_type: str | None = None) -> int:
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


# ─── Décor partagé (installation d'un salon réservable via les endpoints réels) ─


@dataclass
class _Journey:
    """Décor commun aux trois parcours : un salon walk-in, un gérant, un
    coiffeur, une borne terminal active, deux comptes client — le tout monté
    **via l'API** (jamais d'INSERT brut pour une entité qui a un endpoint)."""

    salon_id: str
    owner_id: str  # gérant propriétaire (`salon.owner_id`)
    manager_token: str
    hairdresser_id: str
    service_id: str
    terminal_token: str
    client_a_id: str
    client_a_token: str
    client_b_id: str
    client_b_token: str


@pytest.fixture()
def _journey(_e2e_client: TestClient) -> _Journey:
    """Monte le décor complet via les endpoints réels.

    1. Gérant inscrit + connecté ; 2. salon créé, **horaires valides** (→ `is_bookable`
    §8.3) + **prestation active** (durée + prix) ; 3. coiffeur créé
    (`POST /salons/{id}/employees`, requis par la prise en charge §5.1/§5.2) ;
    4. borne walk-in provisionnée + activée + connectée (`TERMINAL`, requise pour
    délivrer un ticket, seul rôle détenteur de `QUEUE_TICKET_CREATE`) ; 5. deux
    comptes client inscrits + connectés (le second sert l'appartenance du reçu §5.3).
    """
    client = _e2e_client

    owner_id = _register(
        client,
        "/auth/register/manager",
        phone=_PHONE_MANAGER_LOCAL,
        full_name="Gérant E2E Parcours",
    )
    manager_token = _login(client, phone=_PHONE_MANAGER_LOCAL)
    auth = _auth(manager_token)

    resp = client.post("/salons", json={"name": _SALON_NAME}, headers=auth)
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    salon_id = resp.json()["id"]

    resp = client.put(
        f"/salons/{salon_id}/opening-hours", json=_VALID_HOURS, headers=auth
    )
    assert resp.status_code == 200, f"Horaires refusés : {resp.text}"

    resp = client.post(
        f"/salons/{salon_id}/services",
        json={
            "name": _SERVICE_NAME,
            "price": _SERVICE_PRICE,
            "duration_minutes": _SERVICE_DURATION,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    service_id = resp.json()["id"]

    resp = client.post(
        f"/salons/{salon_id}/employees",
        json={
            "full_name": "Coiffeur E2E Parcours",
            "phone": _PHONE_HAIRDRESSER_LOCAL,
            "password": _PASSWORD,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Création coiffeur échouée : {resp.text}"
    hairdresser_id = resp.json()["id"]

    terminal_token = _provision_and_login_terminal(client, manager_token, salon_id)

    client_a_id = _register(
        client, "/auth/register", phone=_PHONE_CLIENT_A_LOCAL, full_name="Client E2E A"
    )
    client_b_id = _register(
        client, "/auth/register", phone=_PHONE_CLIENT_B_LOCAL, full_name="Client E2E B"
    )

    return _Journey(
        salon_id=salon_id,
        owner_id=owner_id,
        manager_token=manager_token,
        hairdresser_id=hairdresser_id,
        service_id=service_id,
        terminal_token=terminal_token,
        client_a_id=client_a_id,
        client_a_token=_login(client, phone=_PHONE_CLIENT_A_LOCAL),
        client_b_id=client_b_id,
        client_b_token=_login(client, phone=_PHONE_CLIENT_B_LOCAL),
    )


# ─── Parcours §5.1 — File d'attente walk-in (équivalent « réservation client ») ─


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestQueueJourneyE2E:
    """§5.1 : ouverture → recherche → fiche → ticket → prise en charge → historique de la fiche.

    Équivalent walk-in de l'ancien « parcours de réservation client ». Deux
    étapes de l'ancienne version **n'ont aucun équivalent** dans le modèle
    walk-in exclusif et sont donc **absentes** ci-dessous (aucun remplacement
    artificiel) :

    - la consultation de **disponibilités** (`GET .../availability`, créneau
      futur) : un ticket walk-in est délivré **immédiatement**, il n'y a plus
      de créneau à l'avance à interroger ;
    - la vérification des **notifications tracées** (confirmation + rappels en
      base, #45/#46) : le module notifications-de-RDV — et la table qui le
      portait — a disparu **entièrement** avec le pivot walk-in (#148/`0017`).
      Un ticket walk-in ne programme ni ne confirme rien.
    """

    def test_full_queue_journey(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Catalogue → fiche → fiche client → ticket → prise en charge → clôture → visite.

        Un **seul** parcours continu sur des entités partagées : chaque étape
        consomme la sortie de la précédente (le salon listé est celui dont la
        borne délivre le ticket, le ticket clôturé est celui qui apparaît dans
        l'historique), ce qu'aucune suite par-fonctionnalité ne vérifie.
        """
        client = _e2e_client
        salon_id = _journey.salon_id

        # 1. Recherche : le salon de test (ACTIVE) apparaît au catalogue public.
        page = client.get("/catalog/salons", params={"q": _SALON_NAME}).json()
        listed = [item for item in page["items"] if item["id"] == salon_id]
        assert listed, "Le salon de test doit apparaître au catalogue (ACTIVE, §8.3)."
        assert listed[0]["is_bookable"] is True

        # 2. Fiche : prestation active + prix.
        detail = client.get(f"/catalog/salons/{salon_id}").json()
        assert detail["is_bookable"] is True
        service_ids = [service["id"] for service in detail["services"]]
        assert _journey.service_id in service_ids
        service = next(s for s in detail["services"] if s["id"] == _journey.service_id)
        assert decimal.Decimal(str(service["price"])) == decimal.Decimal(_SERVICE_PRICE)

        # 3. Le gérant ouvre une fiche walk-in pour la cliente qui vient d'entrer.
        customer_id = _create_customer_profile(
            client, _journey.manager_token, salon_id, full_name="Cliente E2E Parcours"
        )

        # 4. La borne délivre un ticket `waiting` pour cette fiche.
        joined = _join_queue(
            client,
            _journey.terminal_token,
            salon_id,
            service_ids=[_journey.service_id],
            customer_profile_id=customer_id,
        )
        assert joined.status_code == 201, f"Émission du ticket échouée : {joined.text}"
        ticket = joined.json()
        ticket_id = ticket["id"]
        assert ticket["status"] == "waiting"

        # 5. Prise en charge : assignation de la coiffeuse + passage `in_progress`.
        started = _start_ticket(
            client, _journey.manager_token, salon_id, ticket_id, _journey.hairdresser_id
        )
        assert started.status_code == 200, f"Prise en charge échouée : {started.text}"
        assert started.json()["status"] == "in_progress"
        assert str(started.json()["hairdresser_id"]) == _journey.hairdresser_id

        # 6. Clôture : `in_progress` → `done`.
        completed = _complete_ticket(client, _journey.manager_token, salon_id, ticket_id)
        assert completed.status_code == 200, f"Clôture échouée : {completed.text}"
        assert completed.json()["status"] == "done"

        # 7. Historique de la fiche : la visite terminée y figure avec son montant.
        history = _customer_visits(client, _journey.manager_token, salon_id, customer_id)
        visited = [item for item in history["items"] if item["queue_ticket_id"] == ticket_id]
        assert visited, "Le ticket `done` doit apparaître dans l'historique de la fiche (#29)."
        assert visited[0]["status"] == "done"
        line = visited[0]["services"][0]
        assert str(line["service_id"]) == _journey.service_id
        assert decimal.Decimal(str(line["price"])) == decimal.Decimal(_SERVICE_PRICE)
        assert decimal.Decimal(str(visited[0]["total_amount"])) == decimal.Decimal(
            _SERVICE_PRICE
        )

    def test_join_queue_requires_authentication(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Garde-fou deny-by-default : délivrer un ticket **sans jeton** → 401 (ADR-0015)."""
        resp = _e2e_client.post(
            f"/salons/{_journey.salon_id}/queue/tickets",
            json={"service_ids": [_journey.service_id]},
        )
        assert resp.status_code == 401

    def test_people_ahead_count_reflects_still_waiting_tickets(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """`people_ahead_count` du 2e ticket = celui du 1er + 1 (toujours `waiting`)."""
        first = _join_queue(
            _e2e_client,
            _journey.terminal_token,
            _journey.salon_id,
            service_ids=[_journey.service_id],
        )
        assert first.status_code == 201, f"Émission du 1er ticket échouée : {first.text}"
        second = _join_queue(
            _e2e_client,
            _journey.terminal_token,
            _journey.salon_id,
            service_ids=[_journey.service_id],
        )
        assert second.status_code == 201, f"Émission du 2e ticket échouée : {second.text}"
        assert (
            second.json()["people_ahead_count"]
            == first.json()["people_ahead_count"] + 1
        )


# ─── Parcours §5.2 — Gestion de la file côté gérant ──────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestManagerQueueJourneyE2E:
    """§5.2 : file du jour → prise en charge → clôture → encaissement → CA → historique paiements."""

    def test_full_manager_journey(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """File → assignation coiffeuse → in_progress → done → paiement → CA ↑ → historique.

        Le ticket part d'une émission borne **sans coiffeuse assignée** :
        l'assignation gérant (au moment de la prise en charge) est donc une
        étape observable. Le CA du jour est comparé **avant/après**
        l'encaissement (fenêtre « aujourd'hui », le ticket étant délivré et
        encaissé le jour même).
        """
        client = _e2e_client
        salon_id = _journey.salon_id

        customer_id = _create_customer_profile(
            client, _journey.manager_token, salon_id, full_name="Cliente E2E Gérant"
        )
        joined = _join_queue(
            client,
            _journey.terminal_token,
            salon_id,
            service_ids=[_journey.service_id],
            customer_profile_id=customer_id,
        )
        assert joined.status_code == 201, f"Émission du ticket échouée : {joined.text}"
        ticket_id = joined.json()["id"]

        # 1. File du jour : le ticket apparaît en `waiting`.
        listing = _list_queue(client, _journey.manager_token, salon_id)
        counts_before = _status_counts(listing)
        assert counts_before.get("waiting", 0) >= 1

        # 2. Prise en charge : assignation d'une coiffeuse + passage `in_progress`.
        started = _start_ticket(
            client, _journey.manager_token, salon_id, ticket_id, _journey.hairdresser_id
        )
        assert started.status_code == 200, f"Prise en charge échouée : {started.text}"
        assert str(started.json()["hairdresser_id"]) == _journey.hairdresser_id

        # 3. La file reflète la transition : `in_progress` ↑, `waiting` ↓.
        listing = _list_queue(client, _journey.manager_token, salon_id)
        counts_after_start = _status_counts(listing)
        assert counts_after_start.get("in_progress", 0) >= 1
        assert counts_after_start.get("waiting", 0) == counts_before.get("waiting", 0) - 1

        # 4. Prestation réalisée → `done`.
        completed = _complete_ticket(client, _journey.manager_token, salon_id, ticket_id)
        assert completed.status_code == 200, f"Clôture échouée : {completed.text}"

        # 5. Encaissement (montant = prix de la prestation) → 201 VALIDATED.
        revenue_before = _revenue_summary(client, _journey.manager_token, salon_id)
        payment = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount=_SERVICE_PRICE,
            queue_ticket_id=ticket_id,
        )
        assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
        assert payment.json()["status"] == "VALIDATED"

        # 6. CA du jour mis à jour : il a augmenté du montant encaissé.
        revenue_after = _revenue_summary(client, _journey.manager_token, salon_id)
        day_before = decimal.Decimal(revenue_before["day"]["total"])
        day_after = decimal.Decimal(revenue_after["day"]["total"])
        assert day_after - day_before == decimal.Decimal(_SERVICE_PRICE)
        assert day_after == decimal.Decimal(_SERVICE_PRICE)

        # 7. Historique des paiements de la fiche : le paiement y figure.
        payments_history = _customer_payments(
            client, _journey.manager_token, salon_id, customer_id
        )
        assert any(
            item["payment_id"] == payment.json()["id"]
            for item in payments_history["items"]
        )

    def test_queue_list_requires_authentication(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Garde-fou deny-by-default : la file **sans jeton** → 401 (ADR-0015)."""
        resp = _e2e_client.get(f"/salons/{_journey.salon_id}/queue/tickets")
        assert resp.status_code == 401

    def test_cancel_ticket_stays_visible_in_queue_and_blocks_once_in_progress(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Annulation manuelle (no-show) : `expired` + motif, visible dans la file,
        puis garde-fou `409` une fois le ticket pris en charge (règle centrale).

        Preuve **de bout en bout contre du SQL réel** que l'élargissement de
        `QUEUE_TICKET_ACTIVE_STATUSES` fonctionne (la liste ne filtre plus
        `expired`) et que la machine à états interdit bien l'annulation d'un
        ticket déjà `in_progress`.
        """
        client = _e2e_client
        salon_id = _journey.salon_id
        reason = "Cliente absente au moment de l'appel"

        # 1. Un premier ticket, annulé pendant qu'il attend encore.
        joined = _join_queue(
            client, _journey.terminal_token, salon_id, service_ids=[_journey.service_id]
        )
        assert joined.status_code == 201, f"Émission du ticket échouée : {joined.text}"
        ticket_id = joined.json()["id"]

        cancelled = _cancel_ticket(
            client, _journey.manager_token, salon_id, ticket_id, reason=reason
        )
        assert cancelled.status_code == 200, f"Annulation échouée : {cancelled.text}"
        assert cancelled.json()["status"] == "expired"
        assert cancelled.json()["cancellation_reason"] == reason

        # 2. Le ticket annulé reste visible dans la file du jour, motif intact.
        listing = _list_queue(client, _journey.manager_token, salon_id)
        entry = next(item for item in listing["items"] if item["ticket_id"] == ticket_id)
        assert entry["status"] == "expired"
        assert entry["cancellation_reason"] == reason

        # 3. Un second ticket, pris en charge puis dont l'annulation est refusée.
        joined_2 = _join_queue(
            client, _journey.terminal_token, salon_id, service_ids=[_journey.service_id]
        )
        assert joined_2.status_code == 201, f"Émission du 2e ticket échouée : {joined_2.text}"
        ticket_id_2 = joined_2.json()["id"]

        started = _start_ticket(
            client, _journey.manager_token, salon_id, ticket_id_2, _journey.hairdresser_id
        )
        assert started.status_code == 200, f"Prise en charge échouée : {started.text}"

        blocked = _cancel_ticket(
            client, _journey.manager_token, salon_id, ticket_id_2, reason=reason
        )
        assert blocked.status_code == 409, (
            "Un ticket in_progress ne doit plus jamais être annulable ainsi."
        )


# ─── Parcours §5.3 — Encaissement ────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCheckoutJourneyE2E:
    """§5.3 : cohérence montant → journal de caisse → dashboard → reçu du compte client."""

    def _complete_ticket_journey(
        self, client: TestClient, journey: _Journey
    ) -> str:
        """Délivre puis fait passer un ticket en `done` (préalable de l'encaissement).

        Ticket **anonyme** (`customer_profile_id=None`) : ce parcours exerce le
        rattachement d'un paiement à un **compte client enregistré**
        (`client_id`), indépendant de toute fiche walk-in (§5.1/§5.2 les couvrent
        déjà côté fiche) — les deux identités client du produit sont
        volontairement exercées séparément (voir docstring de module).
        """
        ticket_id, _ = self._complete_ticket_journey_with_number(client, journey)
        return ticket_id

    def _complete_ticket_journey_with_number(
        self, client: TestClient, journey: _Journey
    ) -> tuple[str, int]:
        """Comme `_complete_ticket_journey`, renvoie aussi `ticket_number` (#38)."""

        joined = _join_queue(
            client,
            journey.terminal_token,
            journey.salon_id,
            service_ids=[journey.service_id],
        )
        assert joined.status_code == 201, f"Émission du ticket échouée : {joined.text}"
        ticket_id = joined.json()["id"]
        ticket_number = joined.json()["ticket_number"]

        started = _start_ticket(
            client, journey.manager_token, journey.salon_id, ticket_id, journey.hairdresser_id
        )
        assert started.status_code == 200, f"Prise en charge échouée : {started.text}"

        completed = _complete_ticket(client, journey.manager_token, journey.salon_id, ticket_id)
        assert completed.status_code == 200, f"Clôture échouée : {completed.text}"
        return ticket_id, ticket_number

    def test_full_checkout_journey(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Montant incohérent → 422 sans écriture, puis bon montant → journal + CA + reçu.

        Vérifie la **continuité** : la ligne `PAYMENT` du journal (#34),
        l'historique des transactions (#35), le dashboard CA (#40) et le reçu
        client (#38) reposent tous sur **le même** paiement — une régression
        rompant l'un d'eux serait attrapée ici.
        """
        client = _e2e_client
        salon_id = _journey.salon_id
        ticket_id, ticket_number = self._complete_ticket_journey_with_number(client, _journey)

        # 1. Chemin d'erreur structurant : montant ≠ prix de la prestation → 422 sans
        #    **aucune** écriture (payments / cash_journal / audit_logs inchangés) — §8.2/§11.4.
        payments_before = _count_payments(salon_id)
        journal_before = _count_cash_journal(salon_id)
        audit_before = _count_audit_entries_for_salon(salon_id)

        incoherent = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount="4999.00",
            queue_ticket_id=ticket_id,
            client_id=_journey.client_a_id,
        )
        assert incoherent.status_code == 422, (
            f"Montant incohérent attendu 422 : {incoherent.text}"
        )
        assert _count_payments(salon_id) == payments_before
        assert _count_cash_journal(salon_id) == journal_before
        assert _count_audit_entries_for_salon(salon_id) == audit_before

        # 2. Chemin nominal : bon montant + mode CASH, rattaché au compte client A → 201 VALIDATED.
        payment = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount=_SERVICE_PRICE,
            queue_ticket_id=ticket_id,
            client_id=_journey.client_a_id,
        )
        assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
        payment_id = payment.json()["id"]
        assert payment.json()["status"] == "VALIDATED"

        # 2bis. La file d'attente reflète le paiement (sous-requête SQL réelle, #157) :
        #       le ticket encaissé porte désormais `payment_id`, prouvant que la
        #       sous-requête scalaire de `list_active_for_salon` fonctionne en base.
        listing = _list_queue(client, _journey.manager_token, salon_id)
        listed_ticket = next(
            item for item in listing["items"] if item["ticket_id"] == ticket_id
        )
        assert listed_ticket["payment_id"] == payment_id

        # 3. Journal de caisse : une ligne PAYMENT liée au paiement + historique cohérent.
        assert _count_cash_journal(salon_id, "PAYMENT") == 1
        journal_entry = _fetch_cash_journal_entry(salon_id, payment_id)
        assert journal_entry["operation_type"] == "PAYMENT"
        assert journal_entry["amount"] == decimal.Decimal(_SERVICE_PRICE)

        transactions = _list_transactions(client, _journey.manager_token, salon_id)
        listed = [item for item in transactions["items"] if item["id"] == payment_id]
        assert listed, "Le paiement doit figurer dans l'historique des transactions (#35)."
        assert listed[0]["status"] == "VALIDATED"
        assert decimal.Decimal(listed[0]["amount"]) == decimal.Decimal(_SERVICE_PRICE)
        assert str(listed[0]["recorded_by"]) == _journey.owner_id
        assert listed[0]["ticket_number"] == ticket_number

        # 4. Dashboard : le CA du jour reflète le montant net encaissé.
        revenue = _revenue_summary(client, _journey.manager_token, salon_id)
        assert decimal.Decimal(revenue["day"]["total"]) == decimal.Decimal(_SERVICE_PRICE)

        # 5. Reçu du compte client : listé + détail récupérable, montant figé,
        #    numéro de ticket et lignes de prestation résolues (`SqlReceiptRepository.
        #    _lines_for_payment` résout désormais aussi `payment.queue_ticket_id`, #38).
        receipts = _list_receipts(client, _journey.client_a_token)
        receipt_items = [
            item for item in receipts["items"] if item["payment_id"] == payment_id
        ]
        assert receipt_items, "Le reçu doit être récupérable par le client (#38)."
        assert decimal.Decimal(receipt_items[0]["amount"]) == decimal.Decimal(
            _SERVICE_PRICE
        )
        assert receipt_items[0]["ticket_number"] == ticket_number
        assert len(receipt_items[0]["lines"]) == 1
        assert receipt_items[0]["lines"][0]["service_name"] == _SERVICE_NAME
        assert decimal.Decimal(receipt_items[0]["lines"][0]["amount"]) == decimal.Decimal(
            _SERVICE_PRICE
        )
        detail = client.get(
            f"/me/receipts/{payment_id}", headers=_auth(_journey.client_a_token)
        )
        assert detail.status_code == 200, f"Détail du reçu échoué : {detail.text}"
        receipt = detail.json()
        assert receipt["payment_id"] == payment_id
        assert receipt["salon_id"] == salon_id
        assert decimal.Decimal(receipt["amount"]) == decimal.Decimal(_SERVICE_PRICE)
        assert receipt["ticket_number"] == ticket_number
        assert len(receipt["lines"]) == 1
        # Aucune PII tierce ni jeton dans le reçu (§11.3).
        assert _journey.client_a_token not in detail.text
        assert "recorded_by" not in detail.text

    def test_third_party_receipt_returns_404(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Garde-fou d'appartenance : le reçu du client A est `404` neutre pour le client B.

        Indiscernable d'un `payment_id` inexistant (aucun oracle §11.2) — un seul cas,
        sans dupliquer la matrice authz de #51.
        """
        client = _e2e_client
        salon_id = _journey.salon_id
        ticket_id = self._complete_ticket_journey(client, _journey)

        payment = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount=_SERVICE_PRICE,
            queue_ticket_id=ticket_id,
            client_id=_journey.client_a_id,
        )
        assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
        payment_id = payment.json()["id"]

        third_party = client.get(
            f"/me/receipts/{payment_id}", headers=_auth(_journey.client_b_token)
        )
        assert third_party.status_code == 404
        nonexistent = client.get(
            f"/me/receipts/{uuid.uuid4()}", headers=_auth(_journey.client_b_token)
        )
        assert nonexistent.status_code == 404
        # Message identique : le reçu d'un tiers est indiscernable d'un id inexistant.
        assert third_party.json()["detail"] == nonexistent.json()["detail"]

    def test_transaction_client_name_resolves_from_ticket_customer_profile(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Paiement d'un ticket walk-in **sans** compte client → `client_name` vient
        de la fiche (`customer_profiles.full_name`), pas de `users.full_name` (#35).
        """
        client = _e2e_client
        salon_id = _journey.salon_id
        customer_id = _create_customer_profile(
            client, _journey.manager_token, salon_id, full_name="Cliente Walk-in Caisse"
        )
        joined = _join_queue(
            client,
            _journey.terminal_token,
            salon_id,
            service_ids=[_journey.service_id],
            customer_profile_id=customer_id,
        )
        assert joined.status_code == 201, f"Émission du ticket échouée : {joined.text}"
        ticket_id = joined.json()["id"]
        ticket_number = joined.json()["ticket_number"]

        started = _start_ticket(
            client, _journey.manager_token, salon_id, ticket_id, _journey.hairdresser_id
        )
        assert started.status_code == 200, f"Prise en charge échouée : {started.text}"
        completed = _complete_ticket(client, _journey.manager_token, salon_id, ticket_id)
        assert completed.status_code == 200, f"Clôture échouée : {completed.text}"

        payment = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount=_SERVICE_PRICE,
            queue_ticket_id=ticket_id,
        )
        assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
        payment_id = payment.json()["id"]

        transactions = _list_transactions(client, _journey.manager_token, salon_id)
        listed = next(item for item in transactions["items"] if item["id"] == payment_id)
        assert listed["client_id"] is None
        assert listed["client_name"] == "Cliente Walk-in Caisse"
        assert listed["ticket_number"] == ticket_number

        # La recherche texte (`q`) matche aussi ce nom résolu côté fiche (#35).
        found = client.get(
            f"/salons/{salon_id}/payments",
            params={"q": "Walk-in Caisse"},
            headers=_auth(_journey.manager_token),
        )
        assert found.status_code == 200, f"Recherche `q` échouée : {found.text}"
        assert any(item["id"] == payment_id for item in found.json()["items"])
