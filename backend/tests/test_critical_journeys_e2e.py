"""Tests e2e des **parcours critiques** de bout en bout (#50, PRD §5).

Ce fichier *stitche* les briques déjà livrées et testées séparément (réservation
#21, statuts #25, décompte du jour #39, encaissement #33/#35, journal de caisse
#34, CA #40, reçus #38, notifications #45/#46/#47) en **trois parcours continus**
partagés — le **même** salon, le **même** client, le **même** RDV — pour attraper
les régressions d'**intégration inter-modules** qui passent entre les mailles des
suites par-fonctionnalité (un RDV `COMPLETED` absent de l'historique client, un
paiement qui ne fait pas monter le CA, un reçu introuvable après encaissement).

Les trois classes (PostgreSQL requis) exercent la **pile HTTP réelle**
(`TestClient` → routers → cas d'usage → dépôts SQL → PostgreSQL), miroir strict du
patron `test_appointment_notification_e2e.py` :

- `TestBookingJourneyE2E` (**§5.1 réservation client**) : catalogue → fiche →
  disponibilités → réservation `PENDING` → confirmation/rappels **tracés** en base
  (#45/#46, présence, sans re-vérification fine) → transition gérant
  `CONFIRMED`→`COMPLETED` → RDV terminé dans l'historique client (#30).
- `TestManagerAppointmentJourneyE2E` (**§5.2 gestion RDV gérant**) : décompte du
  jour → assignation d'un coiffeur → `CONFIRMED` (arrivée) → `COMPLETED` (réalisée)
  → encaissement → **CA du jour ↑** → RDV archivé dans l'historique client.
- `TestCheckoutJourneyE2E` (**§5.3 encaissement**) : depuis un RDV `COMPLETED`, un
  **montant incohérent** → `422` **sans écriture** (§8.2/§11.4, atomicité), puis le
  **bon montant** → `201` `VALIDATED` → **une** ligne `PAYMENT` au journal (#34) +
  historique des transactions (#35) → **dashboard CA** (#40) → **reçu client** (#38)
  récupérable, un `payment_id` d'un tiers restant `404` neutre (appartenance §11.2).

Périmètre (spec `specs/tests-e2e-parcours-critiques.md`) : **aucune modification du
code de production**. Les parcours vérifient la **continuité inter-modules** (les
données produites par une étape sont bien consommées par la suivante) et **un**
chemin d'erreur structurant par parcours ; la couverture fine des branches d'erreur
et de l'authz reste dans les suites par-fonctionnalité et #51. Au plus un `401`
deny-by-default et un `404` neutre d'appartenance par parcours, sans dupliquer #51.

**Dates.** Le décompte du jour (#39) porte sur `appointment_date` : le RDV est
réservé sur un **créneau futur** (`_next_monday`, patron des e2e voisins) pour rester
déterministe (créneaux passés exclus), donc le `daily-summary` est interrogé sur
**ce jour-là**. Le CA (#40) dérive de `cash_journal.created_at` : un encaissement est
enregistré « maintenant » → le CA est interrogé pour **aujourd'hui** (paramètre `date`
omis, défaut serveur `Africa/Abidjan`), pas pour le jour du RDV.

**Argent** : `NUMERIC(12,2)` sérialisé **en chaîne** (`"5000.00"`), jamais un flottant.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_critical_journeys_e2e.py -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage réservée : +225068999xxxx). Ordre FK-safe (mémoire projet
`notifications-fk-restrict-cleanup`) : `notifications`/`campaigns` **avant**
`appointments`/`salons`/`users`, `cash_journal` avant `payments`, `payments`/
`appointment_services` avant `appointments`.
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
_PHONE_HAIRDRESSER_LOCAL = "0689990002"  # coiffeur (assignation §5.2)
_PHONE_CLIENT_A_LOCAL = "0689990003"     # client — acteur principal des parcours
_PHONE_CLIENT_B_LOCAL = "0689990004"     # client tiers — appartenance du reçu (§5.3)
_PASSWORD = "critical-journeys-e2e-strong-password-2024"

_SALON_NAME = "e2e-salon-critical-journeys"
_SERVICE_NAME = "Coupe E2E Parcours"
_SERVICE_PRICE = "5000.00"
_SERVICE_DURATION = 30
_VALID_HOURS = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK (`ON DELETE RESTRICT`).

    Ordre : audit_logs → notifications → campaigns → cash_journal → payments →
    appointment_services → appointments → services → salon_members → salon_photos →
    salons → users. `notifications`/`campaigns` **avant** `appointments`/`salons`/
    `users` (FK `RESTRICT` depuis #45/#49) ; `cash_journal` **avant** `payments`
    (FK `RESTRICT` sur `transaction_id`) ; `payments`/`appointment_services`
    **avant** `appointments`/`services`. Tout est borné par la plage de téléphones
    réservée, via le propriétaire du salon ou l'utilisateur directement.
    """
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
                f"DELETE FROM notifications WHERE salon_id IN ({salons_of_prefix}) "
                f"OR user_id IN ({users_of_prefix})"
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
            text(f"DELETE FROM payments WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text(
                f"DELETE FROM appointment_services WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM appointments WHERE salon_id IN ({salons_of_prefix})"),
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
            text(f"DELETE FROM salon_photos WHERE salon_id IN ({salons_of_prefix})"),
            params,
        )
        conn.execute(
            text("DELETE FROM salons WHERE owner_id IN (" + users_of_prefix + ")"),
            params,
        )
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT).

    - Injecte un JwtTokenService de test (secret local, jamais en production) sur app.state.
    - Supprime les données de test (plage +225068999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip(
            "DATABASE_URL requis pour les tests e2e des parcours critiques."
        )

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


def _next_monday() -> datetime.date:
    """Prochain lundi (jour couvert par `_VALID_HOURS`), toujours dans le futur."""
    today = datetime.date.today()
    days_ahead = (7 - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=days_ahead)


def _first_available_start(
    client: TestClient, salon_id: str, *, date: datetime.date, service_id: str
) -> str:
    """`GET /catalog/salons/{id}/availability` (public) → heure du premier créneau libre."""
    resp = client.get(
        f"/catalog/salons/{salon_id}/availability",
        params={"date": date.isoformat(), "service_id": service_id},
    )
    assert resp.status_code == 200, f"Disponibilité échouée : {resp.text}"
    slots = resp.json()["slots"]
    assert slots, "Aucun créneau libre — le salon devrait être réservable et vide."
    return slots[0]["start"]


def _book(
    client: TestClient,
    token: str,
    salon_id: str,
    *,
    date: datetime.date,
    start_time: str,
    service_id: str,
    hairdresser_id: str | None = None,
) -> object:
    """`POST /salons/{id}/appointments` — retourne la réponse HTTP brute."""
    body: dict[str, object] = {
        "date": date.isoformat(),
        "start_time": start_time,
        "service_ids": [service_id],
    }
    if hairdresser_id is not None:
        body["hairdresser_id"] = hairdresser_id
    return client.post(
        f"/salons/{salon_id}/appointments", json=body, headers=_auth(token)
    )


def _set_status(
    client: TestClient, token: str, salon_id: str, appointment_id: str, status: str
) -> object:
    """`POST /salons/{id}/appointments/{rdv}/status` (cycle gérant, #25)."""
    return client.post(
        f"/salons/{salon_id}/appointments/{appointment_id}/status",
        json={"status": status},
        headers=_auth(token),
    )


def _assign_hairdresser(
    client: TestClient,
    token: str,
    salon_id: str,
    appointment_id: str,
    hairdresser_id: str,
) -> object:
    """`PUT /salons/{id}/appointments/{rdv}/hairdresser` (assignation gérant, #25)."""
    return client.put(
        f"/salons/{salon_id}/appointments/{appointment_id}/hairdresser",
        json={"hairdresser_id": hairdresser_id},
        headers=_auth(token),
    )


def _record_payment(
    client: TestClient,
    token: str,
    salon_id: str,
    *,
    amount: str,
    appointment_id: str,
    client_id: str,
    payment_method: str = "CASH",
) -> object:
    """`POST /salons/{id}/payments` — encaissement d'un RDV (gérant, #33)."""
    return client.post(
        f"/salons/{salon_id}/payments",
        json={
            "amount": amount,
            "payment_method": payment_method,
            "appointment_id": appointment_id,
            "client_id": client_id,
        },
        headers=_auth(token),
    )


def _daily_summary(
    client: TestClient, token: str, salon_id: str, *, date: datetime.date
) -> dict:
    """`GET /salons/{id}/appointments/daily-summary` (décompte du jour, #39)."""
    resp = client.get(
        f"/salons/{salon_id}/appointments/daily-summary",
        params={"date": date.isoformat()},
        headers=_auth(token),
    )
    assert resp.status_code == 200, f"Décompte du jour échoué : {resp.text}"
    return resp.json()


def _revenue_summary(client: TestClient, token: str, salon_id: str) -> dict:
    """`GET /salons/{id}/revenue/summary` (CA, #40) — `date` omis = aujourd'hui.

    Le CA dérive de `cash_journal.created_at` (l'instant de l'encaissement, « ce
    jour ») — la fenêtre du jour est donc **aujourd'hui**, jamais le jour du RDV futur.
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


def _appointment_history(client: TestClient, token: str) -> list[dict]:
    """`GET /appointments/history` (RDV terminés du client, #30)."""
    resp = client.get("/appointments/history", headers=_auth(token))
    assert resp.status_code == 200, f"Historique client échoué : {resp.text}"
    return resp.json()


def _list_receipts(client: TestClient, token: str) -> dict:
    """`GET /me/receipts` (reçus du client, #38)."""
    resp = client.get("/me/receipts", headers=_auth(token))
    assert resp.status_code == 200, f"Liste des reçus échouée : {resp.text}"
    return resp.json()


# ─── Helpers SQL (lecture directe pour asserter la persistance) ──────────────


def _notifications_for_appointment(appointment_id: str) -> list[dict]:
    """Lit en base les notifications rattachées à un RDV (assertion, pas via l'app)."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT user_id, salon_id, appointment_id, type, channel, "
                    "status, sent_at FROM notifications WHERE appointment_id = :aid"
                ),
                {"aid": appointment_id},
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


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
    """Décor commun aux trois parcours : un salon réservable, un gérant, un
    coiffeur, deux clients — le tout monté **via l'API** (jamais d'INSERT brut pour
    une entité qui a un endpoint)."""

    salon_id: str
    owner_id: str  # gérant propriétaire (`salon.owner_id`)
    manager_token: str
    hairdresser_id: str
    service_id: str
    client_a_id: str
    client_a_token: str
    client_b_id: str
    client_b_token: str


@pytest.fixture()
def _journey(_e2e_client: TestClient) -> _Journey:
    """Monte le décor complet via les endpoints réels.

    1. Gérant inscrit + connecté ; 2. salon créé, **horaires valides** (→ `is_bookable`
    §8.3) + **prestation active** (durée + prix) ; 3. coiffeur créé
    (`POST /salons/{id}/employees`, requis par l'assignation §5.2) ; 4. deux clients
    inscrits + connectés (le second sert l'appartenance du reçu §5.3).
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
        client_a_id=client_a_id,
        client_a_token=_login(client, phone=_PHONE_CLIENT_A_LOCAL),
        client_b_id=client_b_id,
        client_b_token=_login(client, phone=_PHONE_CLIENT_B_LOCAL),
    )


# ─── Parcours §5.1 — Réservation client ──────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestBookingJourneyE2E:
    """§5.1 : ouverture → recherche → prestation → créneau → confirmation → historique."""

    def test_full_booking_journey(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Catalogue → fiche → disponibilité → réservation → notifications → historique.

        Un **seul** parcours continu sur des entités partagées : chaque étape consomme
        la sortie de la précédente (le salon listé est celui réservé, le RDV réservé est
        celui terminé puis archivé), ce qu'aucune suite par-fonctionnalité ne vérifie.
        """
        client = _e2e_client
        salon_id = _journey.salon_id

        # 1. Recherche : le salon de test (ACTIVE) apparaît au catalogue public.
        page = client.get("/catalog/salons", params={"q": _SALON_NAME}).json()
        listed = [item for item in page["items"] if item["id"] == salon_id]
        assert listed, "Le salon de test doit apparaître au catalogue (ACTIVE, §8.3)."
        assert listed[0]["is_bookable"] is True

        # 2. Fiche : prestation active + réservable.
        detail = client.get(f"/catalog/salons/{salon_id}").json()
        assert detail["is_bookable"] is True
        service_ids = [service["id"] for service in detail["services"]]
        assert _journey.service_id in service_ids
        service = next(s for s in detail["services"] if s["id"] == _journey.service_id)
        assert decimal.Decimal(str(service["price"])) == decimal.Decimal(_SERVICE_PRICE)

        # 3. Disponibilités : au moins un créneau libre sur un lundi futur.
        date = _next_monday()
        start_time = _first_available_start(
            client, salon_id, date=date, service_id=_journey.service_id
        )

        # 4. Réservation → 201, statut PENDING.
        booking = _book(
            client,
            _journey.client_a_token,
            salon_id,
            date=date,
            start_time=start_time,
            service_id=_journey.service_id,
        )
        assert booking.status_code == 201, f"Réservation échouée : {booking.text}"
        appointment = booking.json()
        appointment_id = appointment["id"]
        assert appointment["status"] == "PENDING"

        # 5. Notifications tracées (#45/#46) : une confirmation + des rappels PENDING,
        #    non remis (`sent_at IS NULL`) — présence, la couverture fine est ailleurs.
        rows = _notifications_for_appointment(appointment_id)
        confirmations = [r for r in rows if r["type"] == "CONFIRMATION"]
        reminders = [r for r in rows if r["type"] == "REMINDER"]
        assert len(confirmations) == 1
        assert confirmations[0]["status"] == "PENDING"
        assert confirmations[0]["sent_at"] is None
        assert str(confirmations[0]["user_id"]) == _journey.client_a_id
        assert len(reminders) >= 1
        for reminder in reminders:
            assert reminder["status"] == "PENDING"
            assert reminder["sent_at"] is None

        # 6. Transition salon → réalisée (PENDING → CONFIRMED → COMPLETED).
        confirmed = _set_status(
            client, _journey.manager_token, salon_id, appointment_id, "CONFIRMED"
        )
        assert confirmed.status_code == 200, f"Confirmation échouée : {confirmed.text}"
        completed = _set_status(
            client, _journey.manager_token, salon_id, appointment_id, "COMPLETED"
        )
        assert completed.status_code == 200, f"Réalisation échouée : {completed.text}"

        # 7. Historique client : le RDV terminé y figure avec son montant figé.
        history = _appointment_history(client, _journey.client_a_token)
        archived = [item for item in history if item["id"] == appointment_id]
        assert archived, "Le RDV COMPLETED doit apparaître dans l'historique client (#30)."
        assert archived[0]["status"] == "COMPLETED"
        line = archived[0]["services"][0]
        assert str(line["service_id"]) == _journey.service_id
        assert decimal.Decimal(str(line["price_at_booking"])) == decimal.Decimal(
            _SERVICE_PRICE
        )

    def test_booking_requires_authentication(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Garde-fou deny-by-default : réserver **sans jeton** → 401 (ADR-0015)."""
        client = _e2e_client
        date = _next_monday()
        start_time = _first_available_start(
            client, _journey.salon_id, date=date, service_id=_journey.service_id
        )
        resp = client.post(
            f"/salons/{_journey.salon_id}/appointments",
            json={
                "date": date.isoformat(),
                "start_time": start_time,
                "service_ids": [_journey.service_id],
            },
        )
        assert resp.status_code == 401


# ─── Parcours §5.2 — Gestion d'un RDV côté gérant ────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestManagerAppointmentJourneyE2E:
    """§5.2 : planning → assignation → arrivée → réalisée → encaissement → CA → archivage."""

    def test_full_manager_journey(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Décompte → assignation coiffeur → CONFIRMED → COMPLETED → paiement → CA ↑ → historique.

        Le RDV part d'une réservation client **sans coiffeur** : l'assignation gérant est
        donc une étape observable. Le CA du jour est comparé **avant/après** l'encaissement
        (fenêtre « aujourd'hui », l'encaissement étant enregistré maintenant).
        """
        client = _e2e_client
        salon_id = _journey.salon_id
        date = _next_monday()

        start_time = _first_available_start(
            client, salon_id, date=date, service_id=_journey.service_id
        )
        booking = _book(
            client,
            _journey.client_a_token,
            salon_id,
            date=date,
            start_time=start_time,
            service_id=_journey.service_id,
        )
        assert booking.status_code == 201, f"Réservation échouée : {booking.text}"
        appointment_id = booking.json()["id"]
        assert booking.json()["hairdresser_id"] is None

        # 1. Planning du jour : le RDV apparaît dans le décompte PENDING.
        summary = _daily_summary(client, _journey.manager_token, salon_id, date=date)
        assert summary["by_status"]["PENDING"] >= 1
        pending_before = summary["by_status"]["PENDING"]

        # 2. Assignation d'un coiffeur.
        assigned = _assign_hairdresser(
            client,
            _journey.manager_token,
            salon_id,
            appointment_id,
            _journey.hairdresser_id,
        )
        assert assigned.status_code == 200, f"Assignation échouée : {assigned.text}"
        assert str(assigned.json()["hairdresser_id"]) == _journey.hairdresser_id

        # 3. Arrivée du client → CONFIRMED ; le décompte reflète la transition.
        confirmed = _set_status(
            client, _journey.manager_token, salon_id, appointment_id, "CONFIRMED"
        )
        assert confirmed.status_code == 200, f"Confirmation échouée : {confirmed.text}"
        summary = _daily_summary(client, _journey.manager_token, salon_id, date=date)
        assert summary["by_status"]["CONFIRMED"] >= 1
        assert summary["by_status"]["PENDING"] == pending_before - 1

        # 4. Prestation réalisée → COMPLETED.
        completed = _set_status(
            client, _journey.manager_token, salon_id, appointment_id, "COMPLETED"
        )
        assert completed.status_code == 200, f"Réalisation échouée : {completed.text}"

        # 5. Encaissement (montant = prix de la prestation) → 201 VALIDATED.
        revenue_before = _revenue_summary(client, _journey.manager_token, salon_id)
        payment = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount=_SERVICE_PRICE,
            appointment_id=appointment_id,
            client_id=_journey.client_a_id,
        )
        assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
        assert payment.json()["status"] == "VALIDATED"

        # 6. CA du jour mis à jour : il a augmenté du montant encaissé.
        revenue_after = _revenue_summary(client, _journey.manager_token, salon_id)
        day_before = decimal.Decimal(revenue_before["day"]["total"])
        day_after = decimal.Decimal(revenue_after["day"]["total"])
        assert day_after - day_before == decimal.Decimal(_SERVICE_PRICE)
        assert day_after == decimal.Decimal(_SERVICE_PRICE)

        # 7. Archivage : le RDV terminé figure dans l'historique client.
        history = _appointment_history(client, _journey.client_a_token)
        assert any(item["id"] == appointment_id for item in history)

    def test_daily_summary_requires_authentication(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Garde-fou deny-by-default : le planning **sans jeton** → 401 (ADR-0015)."""
        resp = _e2e_client.get(
            f"/salons/{_journey.salon_id}/appointments/daily-summary"
        )
        assert resp.status_code == 401


# ─── Parcours §5.3 — Encaissement ────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCheckoutJourneyE2E:
    """§5.3 : cohérence montant → journal de caisse → dashboard → reçu client."""

    def _complete_appointment(
        self, client: TestClient, journey: _Journey, date: datetime.date
    ) -> str:
        """Réserve puis fait passer un RDV en `COMPLETED` (préalable de l'encaissement)."""
        start_time = _first_available_start(
            client, journey.salon_id, date=date, service_id=journey.service_id
        )
        booking = _book(
            client,
            journey.client_a_token,
            journey.salon_id,
            date=date,
            start_time=start_time,
            service_id=journey.service_id,
            hairdresser_id=journey.hairdresser_id,
        )
        assert booking.status_code == 201, f"Réservation échouée : {booking.text}"
        appointment_id = booking.json()["id"]
        for target in ("CONFIRMED", "COMPLETED"):
            resp = _set_status(
                client, journey.manager_token, journey.salon_id, appointment_id, target
            )
            assert resp.status_code == 200, f"Transition {target} échouée : {resp.text}"
        return appointment_id

    def test_full_checkout_journey(
        self, _e2e_client: TestClient, _journey: _Journey
    ) -> None:
        """Montant incohérent → 422 sans écriture, puis bon montant → journal + CA + reçu.

        Vérifie la **continuité** : la ligne `PAYMENT` du journal (#34), l'historique des
        transactions (#35), le dashboard CA (#40) et le reçu client (#38) reposent tous
        sur **le même** paiement — une régression rompant l'un d'eux serait attrapée ici.
        """
        client = _e2e_client
        salon_id = _journey.salon_id
        appointment_id = self._complete_appointment(client, _journey, _next_monday())

        # 1. Chemin d'erreur structurant : montant ≠ prix figé → 422 sans **aucune**
        #    écriture (payments / cash_journal / audit_logs inchangés) — §8.2/§11.4.
        payments_before = _count_payments(salon_id)
        journal_before = _count_cash_journal(salon_id)
        audit_before = _count_audit_entries_for_salon(salon_id)

        incoherent = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount="4999.00",
            appointment_id=appointment_id,
            client_id=_journey.client_a_id,
        )
        assert incoherent.status_code == 422, (
            f"Montant incohérent attendu 422 : {incoherent.text}"
        )
        assert _count_payments(salon_id) == payments_before
        assert _count_cash_journal(salon_id) == journal_before
        assert _count_audit_entries_for_salon(salon_id) == audit_before

        # 2. Chemin nominal : bon montant + mode CASH → 201 VALIDATED.
        payment = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount=_SERVICE_PRICE,
            appointment_id=appointment_id,
            client_id=_journey.client_a_id,
        )
        assert payment.status_code == 201, f"Encaissement échoué : {payment.text}"
        payment_id = payment.json()["id"]
        assert payment.json()["status"] == "VALIDATED"

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

        # 4. Dashboard : le CA du jour reflète le montant net encaissé.
        revenue = _revenue_summary(client, _journey.manager_token, salon_id)
        assert decimal.Decimal(revenue["day"]["total"]) == decimal.Decimal(_SERVICE_PRICE)

        # 5. Reçu client : listé + détail récupérable, avec la prestation figée.
        receipts = _list_receipts(client, _journey.client_a_token)
        receipt_items = [
            item for item in receipts["items"] if item["payment_id"] == payment_id
        ]
        assert receipt_items, "Le reçu doit être récupérable par le client (#38)."
        detail = client.get(
            f"/me/receipts/{payment_id}", headers=_auth(_journey.client_a_token)
        )
        assert detail.status_code == 200, f"Détail du reçu échoué : {detail.text}"
        receipt = detail.json()
        assert receipt["payment_id"] == payment_id
        assert receipt["salon_id"] == salon_id
        assert receipt["lines"], "Le reçu doit porter au moins une ligne de prestation."
        assert decimal.Decimal(receipt["lines"][0]["amount"]) == decimal.Decimal(
            _SERVICE_PRICE
        )
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
        appointment_id = self._complete_appointment(client, _journey, _next_monday())

        payment = _record_payment(
            client,
            _journey.manager_token,
            salon_id,
            amount=_SERVICE_PRICE,
            appointment_id=appointment_id,
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
