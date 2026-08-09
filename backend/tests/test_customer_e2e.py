"""Tests e2e PostgreSQL du **module clients** (`SqlCustomerRepository`, #107).

Comble le seul adapter de persistance du backend sans suite e2e : les modules
`salon`/`appointment`/`user`/`salon_member`/`payment`/`cash_journal` exercent déjà
leur **chemin SQL réel** contre une vraie base ; le module `customer` (US-4.x) ne
l'a jamais fait depuis #28. Les tests unitaires (domaine), cas d'usage (dépôts
*fakes*) et API/BFF (`app.dependency_overrides`) ne touchent **aucune** vraie base :
ils ne peuvent couvrir ni l'index unique partiel, ni la retraduction d'une
`IntegrityError` sous course concurrente, ni la jointure `list_visits`, ni le
round-trip de la migration `0005`.

Scénarios (spec `specs/suite-e2e-postgresql-module-clients.md`) :

**A. Isolation par salon** — même téléphone autorisé dans deux salons (index partiel
`(salon_id, phone)`, pas global) ; doublon dans le **même** salon → `409` (message
neutre, sans le numéro) ; lecture inter-salons → `404` (fiche hors salon,
indiscernable d'inexistante) *après* portée, `403` générique si le `salon_id` du
chemin est hors périmètre ; `401` sans jeton (deny-by-default, ADR-0015).

**B. Unicité `(salon_id, phone)` garantie en base** — deux `SqlCustomerRepository.create`
concurrents (deux `Session`, `threading.Barrier`, patron
`test_appointment_concurrency.py`) → exactement **1** succès + **1**
`CustomerAlreadyExists` ; une seule ligne subsiste ; le numéro soumis n'apparaît pas
dans l'erreur.

**C. `list_visits` — jointure + group-by multi-lignes** — fiche **liée** à un compte
(lien posé directement en base : l'API ne crée que des walk-in) avec RDV `COMPLETED`
multi-prestations → visites groupées par RDV, `total_amount` = somme des
`price_at_booking`, ordre récent d'abord ; refiltrage `salon_id` (un RDV du même
compte dans un autre salon n'apparaît jamais) ; walk-in (`user_id IS NULL`) →
historique vide ; statuts non terminés exclus ; les stats partagent la brique.

**D. Note privée (#32)** — persistance/replace/effacement (seule `notes` change,
`updated_at` régénéré) ; traçabilité `CUSTOMER_NOTE_UPDATED` **sans PII** (`metadata`
vide, la note n'apparaît dans **aucune** colonne d'`audit_logs`) ; atomicité
(une mutation ⇒ une entrée) ; isolation `404`/`403` ; `401` sans jeton, sans
mutation ni audit.

**E. Round-trip de la migration `0005`** — `downgrade`/`upgrade` de la **seule**
révision `0005` (via le proxy `op` d'Alembic, sans toucher la table de version ni
les autres révisions) : aucune erreur `op.f()` / double-préfixage, l'index partiel
et le `CHECK` réapparaissent, `head` restauré en `finally`.

**F. `CustomerFilter` — chemin SQL réel (#40)** — `SqlCustomerRepository.list_for_salon`/
`count_for_salon` exercés directement contre PostgreSQL : un `%` littéral dans `q`
est **échappé** (traité comme caractère du nom, jamais comme joker `LIKE`, sinon un
nom ne portant que la sous-chaîne numérique sans le `%` serait aussi retourné) ;
`count_for_salon` reste cohérent avec la page filtrée ; filtrage par genre exact ;
plage `created_from`/`created_to` **inclusive** aux deux bornes contre une vraie
colonne `TIMESTAMP` ; l'isolation par salon tient sous filtre.

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_customer_e2e.py -v

Sans `DATABASE_URL`, le fichier est **skippé proprement**. Nettoyage : les données de
test sont supprimées avant et après chaque test (plage réservée : +225077998xxxx).
"""

from __future__ import annotations

import datetime
import decimal
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.outbound.persistence.customer_repository import (
    SqlCustomerRepository,
)
from coiflink_api.adapters.outbound.persistence.session import (
    get_engine,
    get_sessionmaker,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.domain.customer import CustomerToCreate, validate_customer_filter
from coiflink_api.domain.errors import CustomerAlreadyExists
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-customer-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e des fiches clients (distincte des autres
# fichiers e2e : ils peuvent tourner dans la même base sans se marcher dessus).
_E2E_PHONE_PREFIX = "+225077998"
_PHONE_A_LOCAL = "0779980001"      # gérant A — parcours principal
_PHONE_B_LOCAL = "0779980002"      # gérant B — isolation inter-salons
_PHONE_CLIENT_LOCAL = "0779980003"  # client enregistré — lien fiche ↔ compte (#29)
_PASSWORD = "customer-e2e-strong-password-2024"

_SALON_NAME_A = "e2e-salon-customers-a"
_SALON_NAME_B = "e2e-salon-customers-b"

# Téléphone d'une **fiche** client (E.164, tel que stocké après normalisation) :
# autorisé dans deux salons, refusé en doublon dans le même salon.
_CUSTOMER_PHONE = "+2250779980100"
# Téléphone dédié à la course concurrente (INSERT direct via le dépôt).
_RACE_PHONE = "+2250779980200"

_SERVICE_PRICE = "5000.00"

# Délai borné des tâches concurrentes : un blocage sur le verrou de l'index unique
# qui ne se résout pas doit faire échouer le test, pas le suspendre indéfiniment.
_TIMEOUT_SECONDS = 30

# Racine du paquet backend (contient `alembic.ini`) — round-trip du bloc E.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PHONE_INDEX = "uq_customer_profiles_salon_phone"
_GENDER_CHECK = "ck_customer_profiles_gender"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime les données de test dans l'ordre des contraintes FK.

    Ordre : audit_logs (par `salon_id` **et** `actor_user_id`) → payments →
    appointment_services → appointments → customer_profiles → services →
    salon_members (par `salon_id` **et** `user_id`) → salons → users. Toutes les
    données sont rattachées à un salon dont le propriétaire porte le préfixe réservé
    (miroir du wipe de `test_cash_discrepancies_e2e.py`, avec `customer_profiles`).
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
            text(
                f"DELETE FROM customer_profiles WHERE salon_id IN ({salons_of_prefix})"
            ),
            params,
        )
        conn.execute(
            text(f"DELETE FROM services WHERE salon_id IN ({salons_of_prefix})"), params
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
        pytest.skip("DATABASE_URL requis pour les tests e2e des fiches clients.")

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


def _register_manager(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E Fiches", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription gérant échouée : {resp.text}"
    return resp.json()["id"]


def _register_client(client: TestClient, *, phone: str = _PHONE_CLIENT_LOCAL) -> str:
    resp = client.post(
        "/auth/register",
        json={"full_name": "Client E2E Fiches", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription client échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": _PASSWORD})
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()["access_token"]


def _create_salon(client: TestClient, token: str, *, name: str = _SALON_NAME_A) -> str:
    resp = client.post(
        "/salons",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création salon échouée : {resp.text}"
    return resp.json()["id"]


def _create_service(
    client: TestClient, token: str, salon_id: str, *, name: str = "Coupe homme",
    price: str = _SERVICE_PRICE,
) -> str:
    resp = client.post(
        f"/salons/{salon_id}/services",
        json={"name": name, "price": price, "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création prestation échouée : {resp.text}"
    return resp.json()["id"]


def _create_customer(
    client: TestClient, token: str, salon_id: str, **body: object
) -> dict:
    body.setdefault("full_name", "Awa Koné")
    resp = client.post(
        f"/salons/{salon_id}/customers",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Création fiche échouée : {resp.text}"
    return resp.json()


def _update_note(
    client: TestClient, token: str, salon_id: str, customer_id: str, notes: str | None
):
    return client.put(
        f"/salons/{salon_id}/customers/{customer_id}/notes",
        json={"notes": notes},
        headers={"Authorization": f"Bearer {token}"},
    )


def _get_customer(client: TestClient, token: str, salon_id: str, customer_id: str):
    return client.get(
        f"/salons/{salon_id}/customers/{customer_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


def _get_history(client: TestClient, token: str, salon_id: str, customer_id: str) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/customers/{customer_id}/appointments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Historique échoué : {resp.text}"
    return resp.json()


def _get_stats(client: TestClient, token: str, salon_id: str, customer_id: str) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/customers/{customer_id}/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Stats échouées : {resp.text}"
    return resp.json()


def _get_payments(client: TestClient, token: str, salon_id: str, customer_id: str) -> dict:
    resp = client.get(
        f"/salons/{salon_id}/customers/{customer_id}/payments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Paiements échoués : {resp.text}"
    return resp.json()


def _setup_manager_salon(
    client: TestClient, *, phone: str = _PHONE_A_LOCAL, name: str = _SALON_NAME_A
) -> tuple[str, str]:
    """Inscrit un gérant, se connecte, crée son salon. Retourne (token, salon_id)."""
    _register_manager(client, phone=phone)
    token = _login(client, phone=phone)
    salon_id = _create_salon(client, token, name=name)
    return token, salon_id


# ─── Helpers SQL (insertion / lecture directes — bypass des gardes HTTP) ──────


def _link_customer_to_user(customer_id: str, user_id: str) -> None:
    """Rattache une fiche à un **compte** (`user_id`) — indispensable à `list_visits`.

    L'API ne crée que des fiches walk-in (`user_id = NULL`) ; sans lien, `list_visits`
    retourne un tuple vide. Le `user_id` doit être celui d'un client **enregistré**
    (FK `customer_profiles.user_id → users.id`, cohérent avec `appointments.client_id`).
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE customer_profiles SET user_id = :uid WHERE id = :cid"),
            {"uid": user_id, "cid": customer_id},
        )
        conn.commit()


def _insert_appointment(
    *,
    salon_id: str,
    client_id: str,
    appointment_date: datetime.date,
    start_time: str = "09:00",
    end_time: str = "10:00",
    status: str = "COMPLETED",
) -> str:
    """Insère un RDV directement en base pour contrôler son statut/créneau.

    `slot` est une colonne générée (COMPUTED) — pas d'insertion manuelle.
    `hairdresser_id` est laissé NULL (non pertinent pour l'historique).
    """
    appt_id = str(uuid.uuid4())
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO appointments "
                "(id, salon_id, client_id, appointment_date, start_time, end_time, status) "
                "VALUES (:id, :salon_id, :client_id, :date, :start, :end, :status)"
            ),
            {
                "id": appt_id,
                "salon_id": salon_id,
                "client_id": client_id,
                "date": appointment_date,
                "start": start_time,
                "end": end_time,
                "status": status,
            },
        )
        conn.commit()
    return appt_id


def _insert_appointment_service(
    *, salon_id: str, appointment_id: str, service_id: str, price: str
) -> None:
    """Rattache une prestation (prix figé `price_at_booking`) à un RDV."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO appointment_services "
                "(appointment_id, service_id, salon_id, price_at_booking) "
                "VALUES (:appt, :service, :salon, :price)"
            ),
            {
                "appt": appointment_id,
                "service": service_id,
                "salon": salon_id,
                "price": decimal.Decimal(price),
            },
        )
        conn.commit()


def _insert_payment(
    *,
    salon_id: str,
    client_id: str,
    recorded_by: str,
    appointment_id: str,
    amount: str = _SERVICE_PRICE,
    status: str = "VALIDATED",
    created_at: datetime.datetime | None = None,
) -> str:
    """Insère un paiement directement en base (statut/horodatage contrôlés).

    Bypass de l'API d'encaissement (#33, déjà couverte par `test_payments_e2e.py`) :
    seule la **lecture** fiche-scopée `list_payments` est exercée ici. Permet de
    couvrir des statuts que le chemin d'écriture normal ne produit pas directement
    (`PENDING`/`CANCELLED`/`ADJUSTED`). `appointment_id` satisfait le `CHECK`
    `ck_payments_ref_present` (un paiement est lié à un RDV **ou** une prestation).
    """
    payment_id = str(uuid.uuid4())
    engine = get_engine()
    with engine.connect() as conn:
        params: dict[str, object] = {
            "id": payment_id,
            "salon_id": salon_id,
            "client_id": client_id,
            "appointment_id": appointment_id,
            "amount": decimal.Decimal(amount),
            "recorded_by": recorded_by,
            "status": status,
        }
        columns = (
            "id, salon_id, client_id, appointment_id, amount, payment_method, "
            "recorded_by, status"
        )
        values = (
            ":id, :salon_id, :client_id, :appointment_id, :amount, 'CASH', "
            ":recorded_by, :status"
        )
        if created_at is not None:
            columns += ", created_at"
            values += ", :created_at"
            params["created_at"] = created_at
        conn.execute(
            text(f"INSERT INTO payments ({columns}) VALUES ({values})"), params
        )
        conn.commit()
    return payment_id


def _fetch_customer_row(customer_id: str) -> dict:
    """Lit les colonnes d'une fiche directement en base (source de vérité)."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT full_name, phone, gender, notes, user_id, "
                "created_at, updated_at FROM customer_profiles WHERE id = :cid"
            ),
            {"cid": customer_id},
        ).mappings().one()
        return dict(row)


def _count_profiles(salon_id: str, phone: str) -> int:
    """Nombre de fiches portant ce `(salon_id, phone)` (source de vérité base)."""
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT COUNT(*) FROM customer_profiles "
                "WHERE salon_id = :sid AND phone = :phone"
            ),
            {"sid": salon_id, "phone": phone},
        ).scalar_one()


def _set_customer_created_at(customer_id: str, created_at: datetime.datetime) -> None:
    """Force `created_at` d'une fiche (bloc F) : seul moyen de contrôler une borne exacte.

    `created_at` est généré côté serveur à l'insertion (`server_default`) ; le
    filtrage par plage de dates (§ bloc F) ne peut être testé de façon fiable aux
    **bornes exactes** qu'en fixant la valeur directement en base.
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE customer_profiles SET created_at = :created_at WHERE id = :cid"),
            {"created_at": created_at, "cid": customer_id},
        )
        conn.commit()


def _fetch_audit_rows(salon_id: str, action: str) -> list[dict]:
    """`audit_logs` filtré `(salon_id, action)` — assertions de traçabilité sans PII."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT actor_user_id, entity_type, entity_id, metadata, created_at "
                "FROM audit_logs WHERE salon_id = :sid AND action = :action"
            ),
            {"sid": salon_id, "action": action},
        ).mappings().all()
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


def _schema_object_present(*, index: bool = False, check: bool = False, column: bool = False) -> bool:
    """Présence en base de l'index partiel / du CHECK / de la colonne `gender` (bloc E)."""
    engine = get_engine()
    with engine.connect() as conn:
        if index:
            return conn.execute(
                text("SELECT COUNT(*) FROM pg_indexes WHERE indexname = :n"),
                {"n": _PHONE_INDEX},
            ).scalar_one() > 0
        if check:
            return conn.execute(
                text("SELECT COUNT(*) FROM pg_constraint WHERE conname = :n"),
                {"n": _GENDER_CHECK},
            ).scalar_one() > 0
        return conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = 'customer_profiles' AND column_name = 'gender'"
            )
        ).scalar_one() > 0


# ─── A. Isolation par salon en profondeur (§11.2, ADR-0026) ──────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCustomerIsolationE2E:
    """Filtre d'isolation `(salon_id, id)` et index partiel `(salon_id, phone)`."""

    def test_same_phone_allowed_in_two_salons(self, _e2e_client: TestClient) -> None:
        """Le même téléphone peut être fiché dans deux salons (index partiel `(salon_id, phone)`)."""
        token_a, salon_a = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_B_LOCAL, name=_SALON_NAME_B
        )

        _create_customer(_e2e_client, token_a, salon_a, phone=_CUSTOMER_PHONE)
        # Salon B, **même** téléphone : autorisé (fiches cloisonnées par salon).
        resp = _e2e_client.post(
            f"/salons/{salon_b}/customers",
            json={"full_name": "Awa Koné", "phone": _CUSTOMER_PHONE},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 201, resp.text

    def test_duplicate_phone_same_salon_returns_409(self, _e2e_client: TestClient) -> None:
        """Un doublon `(salon_id, phone)` → `409` avec message neutre (sans le numéro)."""
        token, salon = _setup_manager_salon(_e2e_client)
        _create_customer(_e2e_client, token, salon, phone=_CUSTOMER_PHONE)

        resp = _e2e_client.post(
            f"/salons/{salon}/customers",
            json={"full_name": "Awa Koné", "phone": _CUSTOMER_PHONE},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409, resp.text
        detail = resp.json().get("detail", "")
        assert _CUSTOMER_PHONE not in detail
        assert "0779980100" not in detail  # ni la forme locale saisissable

    def test_cross_salon_read_returns_404_after_scope(self, _e2e_client: TestClient) -> None:
        """Lire, dans **son** salon, une fiche d'un autre salon → `404` (hors salon)."""
        token_a, salon_a = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_B_LOCAL, name=_SALON_NAME_B
        )
        customer_b = _create_customer(_e2e_client, token_b, salon_b)["id"]

        # Portée = salon A (valide pour le gérant A), fiche du salon B → 404.
        resp = _get_customer(_e2e_client, token_a, salon_a, customer_b)
        assert resp.status_code == 404, resp.text
        assert customer_b not in resp.json().get("detail", "")

    def test_out_of_scope_salon_returns_403(self, _e2e_client: TestClient) -> None:
        """Cibler le salon B avec le jeton du gérant A → `403` générique (portée refusée avant accès)."""
        token_a, _ = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_B_LOCAL, name=_SALON_NAME_B
        )
        customer_b = _create_customer(_e2e_client, token_b, salon_b)["id"]

        resp = _get_customer(_e2e_client, token_a, salon_b, customer_b)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Accès refusé."

    def test_no_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET liste sans jeton → `401` (deny-by-default, ADR-0015)."""
        _, salon = _setup_manager_salon(_e2e_client)
        resp = _e2e_client.get(f"/salons/{salon}/customers")
        assert resp.status_code == 401


# ─── B. Unicité du téléphone garantie en base — course concurrente ───────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCustomerPhoneUniquenessRaceE2E:
    """Retraduction `IntegrityError` → `CustomerAlreadyExists` sous parallélisme réel."""

    def test_concurrent_create_yields_one_success_one_conflict(
        self, _e2e_client: TestClient
    ) -> None:
        """Deux `create` concurrents (même `(salon_id, phone)`) → 1 succès + 1 conflit ; 1 ligne.

        On appelle `SqlCustomerRepository.create` **directement** (deux `Session`
        distinctes) pour exercer le chemin `IntegrityError` : le pré-contrôle
        applicatif `phone_exists` masquerait sinon la course. La barrière aligne les
        deux INSERT sur l'index unique partiel au même instant (patron
        `test_appointment_concurrency.py`).
        """
        _, salon = _setup_manager_salon(_e2e_client)
        salon_uuid = uuid.UUID(salon)

        sessionmaker_ = get_sessionmaker()
        barrier = threading.Barrier(2)
        seen_numbers: list[str] = []

        def create() -> str:
            session = sessionmaker_()
            try:
                repository = SqlCustomerRepository(session)
                command = CustomerToCreate(
                    salon_id=salon_uuid,
                    full_name="Course Concurrente",
                    phone=_RACE_PHONE,
                )
                barrier.wait(timeout=_TIMEOUT_SECONDS)
                try:
                    repository.create(command)
                except CustomerAlreadyExists as exc:
                    # Le message est neutre : il ne rappelle jamais le numéro soumis.
                    seen_numbers.append(str(exc))
                    return "conflict"
                # Le commit du gagnant libère le verrou : le perdant, bloqué dans son
                # INSERT, reçoit alors la violation d'unicité.
                session.commit()
                return "created"
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create), pool.submit(create)]
            outcomes = sorted(f.result(timeout=_TIMEOUT_SECONDS) for f in futures)

        assert outcomes == ["conflict", "created"], (
            f"Attendu 1 succès + 1 conflit, obtenu : {outcomes}"
        )
        # La base tranche : une seule ligne porte ce (salon_id, phone).
        assert _count_profiles(salon, _RACE_PHONE) == 1
        # L'erreur de domaine ne divulgue jamais le numéro (§11.3).
        for message in seen_numbers:
            assert _RACE_PHONE not in message


# ─── C. list_visits — jointure + group-by multi-lignes (historique #29) ──────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCustomerVisitsE2E:
    """Jointure `appointments × appointment_services × services`, group-by, refiltrage salon."""

    def _linked_customer(
        self, client: TestClient
    ) -> tuple[str, str, str, str, str]:
        """Monte gérant A + salon A + prestation + fiche **liée** à un client enregistré.

        Retourne (token, salon_id, customer_id, client_user_id, service_id).
        """
        token, salon = _setup_manager_salon(client)
        client_user_id = _register_client(client)
        service_id = _create_service(client, token, salon)
        customer_id = _create_customer(client, token, salon, full_name="Client Lié")["id"]
        _link_customer_to_user(customer_id, client_user_id)
        return token, salon, customer_id, client_user_id, service_id

    def test_visits_grouped_and_ordered_recent_first(self, _e2e_client: TestClient) -> None:
        """Visites groupées par RDV, `total_amount` = somme des prix, plus récent d'abord."""
        token, salon, customer_id, client_user_id, service_id = self._linked_customer(
            _e2e_client
        )
        service_two = _create_service(
            _e2e_client, token, salon, name="Barbe", price="3000.00"
        )
        # RDV le plus ancien, multi-prestations (2000 + 3000 = 5000).
        older = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20), start_time="09:00", end_time="10:00",
        )
        _insert_appointment_service(
            salon_id=salon, appointment_id=older, service_id=service_id, price="2000.00"
        )
        _insert_appointment_service(
            salon_id=salon, appointment_id=older, service_id=service_two, price="3000.00"
        )
        # RDV plus récent, une seule prestation (5000).
        newer = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 25), start_time="11:00", end_time="12:00",
        )
        _insert_appointment_service(
            salon_id=salon, appointment_id=newer, service_id=service_id, price=_SERVICE_PRICE
        )

        history = _get_history(_e2e_client, token, salon, customer_id)
        items = history["items"]
        assert [item["appointment_id"] for item in items] == [newer, older]
        older_item = items[1]
        assert len(older_item["services"]) == 2
        assert decimal.Decimal(older_item["total_amount"]) == decimal.Decimal("5000.00")
        assert history["total_visits"] == 2
        assert decimal.Decimal(history["total_amount"]) == decimal.Decimal("10000.00")

    def test_service_order_within_visit_is_stable(self, _e2e_client: TestClient) -> None:
        """L'ordre des prestations d'une visite est **stable** entre deux appels."""
        token, salon, customer_id, client_user_id, service_id = self._linked_customer(
            _e2e_client
        )
        service_two = _create_service(
            _e2e_client, token, salon, name="Barbe", price="3000.00"
        )
        appt = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20),
        )
        _insert_appointment_service(
            salon_id=salon, appointment_id=appt, service_id=service_id, price="2000.00"
        )
        _insert_appointment_service(
            salon_id=salon, appointment_id=appt, service_id=service_two, price="3000.00"
        )

        first = _get_history(_e2e_client, token, salon, customer_id)["items"][0]["services"]
        second = _get_history(_e2e_client, token, salon, customer_id)["items"][0]["services"]
        assert [s["service_id"] for s in first] == [s["service_id"] for s in second]

    def test_other_salon_visit_never_appears(self, _e2e_client: TestClient) -> None:
        """Un RDV du **même compte** dans un autre salon n'apparaît jamais (refiltrage `salon_id`)."""
        token_a, salon_a, customer_id, client_user_id, service_a = self._linked_customer(
            _e2e_client
        )
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_B_LOCAL, name=_SALON_NAME_B
        )
        service_b = _create_service(_e2e_client, token_b, salon_b)
        # RDV du même client, mais dans le salon B.
        appt_b = _insert_appointment(
            salon_id=salon_b, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20),
        )
        _insert_appointment_service(
            salon_id=salon_b, appointment_id=appt_b, service_id=service_b, price=_SERVICE_PRICE
        )

        history = _get_history(_e2e_client, token_a, salon_a, customer_id)
        assert history["items"] == []
        assert history["total_visits"] == 0

    def test_walk_in_customer_has_empty_history(self, _e2e_client: TestClient) -> None:
        """Fiche walk-in (`user_id IS NULL`) → historique vide, sans erreur ni oracle."""
        token, salon = _setup_manager_salon(_e2e_client)
        customer_id = _create_customer(_e2e_client, token, salon)["id"]

        history = _get_history(_e2e_client, token, salon, customer_id)
        assert history["items"] == []
        assert history["total_visits"] == 0
        assert history["last_visit_at"] is None
        assert decimal.Decimal(history["total_amount"]) == decimal.Decimal("0")

    def test_non_completed_statuses_excluded(self, _e2e_client: TestClient) -> None:
        """Seuls les RDV `COMPLETED` comptent : les autres statuts sont exclus (#29)."""
        token, salon, customer_id, client_user_id, service_id = self._linked_customer(
            _e2e_client
        )
        completed = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20), status="COMPLETED",
        )
        _insert_appointment_service(
            salon_id=salon, appointment_id=completed, service_id=service_id, price=_SERVICE_PRICE
        )
        excluded_ids = []
        for day, status in ((10, "PENDING"), (11, "CONFIRMED"), (12, "CANCELLED"), (13, "NO_SHOW")):
            appt = _insert_appointment(
                salon_id=salon, client_id=client_user_id,
                appointment_date=datetime.date(2026, 6, day), status=status,
            )
            _insert_appointment_service(
                salon_id=salon, appointment_id=appt, service_id=service_id, price=_SERVICE_PRICE
            )
            excluded_ids.append(appt)

        history = _get_history(_e2e_client, token, salon, customer_id)
        returned = {item["appointment_id"] for item in history["items"]}
        assert returned == {completed}
        assert returned.isdisjoint(excluded_ids)

    def test_stats_share_list_visits_brick(self, _e2e_client: TestClient) -> None:
        """Les stats réutilisent `list_visits` : classement cohérent, `user_id`/`client_id` non exposés."""
        token, salon, customer_id, client_user_id, service_id = self._linked_customer(
            _e2e_client
        )
        # Deux RDV COMPLETED avec la même prestation → count == 2.
        for day in (20, 21):
            appt = _insert_appointment(
                salon_id=salon, client_id=client_user_id,
                appointment_date=datetime.date(2026, 6, day),
            )
            _insert_appointment_service(
                salon_id=salon, appointment_id=appt, service_id=service_id, price=_SERVICE_PRICE
            )

        stats = _get_stats(_e2e_client, token, salon, customer_id)
        assert stats["total_visits"] == 2
        assert stats["services"], "au moins une prestation classée"
        top = stats["services"][0]
        assert top["service_id"] == service_id
        assert top["count"] == 2
        assert "user_id" not in stats
        assert "client_id" not in stats
        for service in stats["services"]:
            assert "user_id" not in service and "client_id" not in service


class TestCustomerPaymentsE2E:
    """Jointure `customer_profiles.user_id × payments.client_id`, refiltrage salon."""

    def _linked_customer(
        self, client: TestClient
    ) -> tuple[str, str, str, str, str]:
        """Monte gérant A + salon A + fiche **liée** à un client enregistré.

        Retourne (token, salon_id, customer_id, client_user_id, manager_id).
        """
        manager_id = _register_manager(client)
        token = _login(client)
        salon = _create_salon(client, token)
        client_user_id = _register_client(client)
        customer_id = _create_customer(client, token, salon, full_name="Client Lié")["id"]
        _link_customer_to_user(customer_id, client_user_id)
        return token, salon, customer_id, client_user_id, manager_id

    def test_payments_ordered_recent_first(self, _e2e_client: TestClient) -> None:
        """Paiements du compte lié, triés date décroissante (plus récent d'abord)."""
        token, salon, customer_id, client_user_id, manager_id = self._linked_customer(
            _e2e_client
        )
        appt_older = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20),
        )
        appt_newer = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 25),
        )
        older = _insert_payment(
            salon_id=salon, client_id=client_user_id, recorded_by=manager_id,
            appointment_id=appt_older, amount="2000.00",
            created_at=datetime.datetime(2026, 6, 20, 9, 0, tzinfo=datetime.timezone.utc),
        )
        newer = _insert_payment(
            salon_id=salon, client_id=client_user_id, recorded_by=manager_id,
            appointment_id=appt_newer, amount="3000.00",
            created_at=datetime.datetime(2026, 6, 25, 9, 0, tzinfo=datetime.timezone.utc),
        )

        payments = _get_payments(_e2e_client, token, salon, customer_id)
        ids = [item["payment_id"] for item in payments["items"]]
        assert ids == [newer, older]

    def test_all_statuses_returned(self, _e2e_client: TestClient) -> None:
        """Tous les statuts sont renvoyés (`PENDING`/`VALIDATED`/`CANCELLED`/`ADJUSTED`)."""
        token, salon, customer_id, client_user_id, manager_id = self._linked_customer(
            _e2e_client
        )
        for day, status in enumerate(
            ("PENDING", "VALIDATED", "CANCELLED", "ADJUSTED"), start=20
        ):
            appt = _insert_appointment(
                salon_id=salon, client_id=client_user_id,
                appointment_date=datetime.date(2026, 6, day),
            )
            _insert_payment(
                salon_id=salon, client_id=client_user_id, recorded_by=manager_id,
                appointment_id=appt, status=status,
            )

        payments = _get_payments(_e2e_client, token, salon, customer_id)
        statuses = {item["status"] for item in payments["items"]}
        assert statuses == {"PENDING", "VALIDATED", "CANCELLED", "ADJUSTED"}

    def test_amount_and_currency_correct(self, _e2e_client: TestClient) -> None:
        token, salon, customer_id, client_user_id, manager_id = self._linked_customer(
            _e2e_client
        )
        appt = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20),
        )
        _insert_payment(
            salon_id=salon, client_id=client_user_id, recorded_by=manager_id,
            appointment_id=appt, amount="12500.00",
        )

        payments = _get_payments(_e2e_client, token, salon, customer_id)
        item = payments["items"][0]
        assert decimal.Decimal(item["amount"]) == decimal.Decimal("12500.00")
        assert item["currency"] == "XOF"

    def test_other_salon_payment_never_appears(self, _e2e_client: TestClient) -> None:
        """Un paiement du **même compte** dans un autre salon n'apparaît jamais (refiltrage `salon_id`)."""
        token_a, salon_a, customer_id, client_user_id, manager_a = self._linked_customer(
            _e2e_client
        )
        manager_b_id = _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        token_b = _login(_e2e_client, phone=_PHONE_B_LOCAL)
        salon_b = _create_salon(_e2e_client, token_b, name=_SALON_NAME_B)
        appt_b = _insert_appointment(
            salon_id=salon_b, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20),
        )
        _insert_payment(
            salon_id=salon_b, client_id=client_user_id, recorded_by=manager_b_id,
            appointment_id=appt_b,
        )

        payments = _get_payments(_e2e_client, token_a, salon_a, customer_id)
        assert payments["items"] == []

    def test_walk_in_customer_has_empty_payments(self, _e2e_client: TestClient) -> None:
        """Fiche walk-in (`user_id IS NULL`) → liste vide, sans erreur ni oracle."""
        token, salon = _setup_manager_salon(_e2e_client)
        customer_id = _create_customer(_e2e_client, token, salon)["id"]

        payments = _get_payments(_e2e_client, token, salon, customer_id)
        assert payments["items"] == []

    def test_response_has_no_pii_beyond_amount_and_status(
        self, _e2e_client: TestClient
    ) -> None:
        """Anti-oracle ADR-0026 : `user_id`/`client_id`/`recorded_by` absents de la réponse."""
        token, salon, customer_id, client_user_id, manager_id = self._linked_customer(
            _e2e_client
        )
        appt = _insert_appointment(
            salon_id=salon, client_id=client_user_id,
            appointment_date=datetime.date(2026, 6, 20),
        )
        _insert_payment(
            salon_id=salon, client_id=client_user_id, recorded_by=manager_id,
            appointment_id=appt,
        )

        payments = _get_payments(_e2e_client, token, salon, customer_id)
        assert "user_id" not in payments
        assert "client_id" not in payments
        for item in payments["items"]:
            assert "user_id" not in item
            assert "client_id" not in item
            assert "recorded_by" not in item


# ─── D. Mise à jour de note privée (#32) ─────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCustomerNoteE2E:
    """Édition de note : persistance, traçabilité sans PII, atomicité, isolation."""

    def test_note_replace_and_clear_touches_only_notes(self, _e2e_client: TestClient) -> None:
        """PUT « A » puis « B » remplace ; PUT `null` efface ; seule `notes` change."""
        token, salon = _setup_manager_salon(_e2e_client)
        customer = _create_customer(
            _e2e_client, token, salon, full_name="Awa Koné",
            phone=_CUSTOMER_PHONE, gender="FEMALE",
        )
        customer_id = customer["id"]
        before = _fetch_customer_row(customer_id)

        resp_a = _update_note(_e2e_client, token, salon, customer_id, "Note A")
        assert resp_a.status_code == 200, resp_a.text
        resp_b = _update_note(_e2e_client, token, salon, customer_id, "Note B")
        assert resp_b.status_code == 200, resp_b.text
        assert resp_b.json()["notes"] == "Note B"

        after = _fetch_customer_row(customer_id)
        assert after["notes"] == "Note B"
        # Seule la colonne `notes` a bougé ; `updated_at` régénéré.
        assert after["full_name"] == before["full_name"]
        assert after["phone"] == before["phone"]
        assert after["gender"] == before["gender"]
        assert after["updated_at"] >= before["updated_at"]

        resp_clear = _update_note(_e2e_client, token, salon, customer_id, None)
        assert resp_clear.status_code == 200, resp_clear.text
        assert resp_clear.json()["notes"] is None
        assert _fetch_customer_row(customer_id)["notes"] is None

    def test_note_update_audited_without_pii(self, _e2e_client: TestClient) -> None:
        """`CUSTOMER_NOTE_UPDATED` : une entrée neutre, la note absente de tout `audit_logs`."""
        token, salon = _setup_manager_salon(_e2e_client)
        # L'acteur journalisé est le gérant : on le compare à l'entrée d'audit de
        # création (le POST journalise CUSTOMER_CREATED avec le même acteur).
        customer_id = _create_customer(_e2e_client, token, salon)["id"]
        secret_note = "Allergie au réactif ZZZ-marqueur-unique-12345 (donnée de santé)."
        resp = _update_note(_e2e_client, token, salon, customer_id, secret_note)
        assert resp.status_code == 200, resp.text

        rows = _fetch_audit_rows(salon, "CUSTOMER_NOTE_UPDATED")
        assert len(rows) == 1, "exactement une entrée d'audit pour la mise à jour"
        entry = rows[0]
        assert entry["entity_type"] == "customer"
        assert str(entry["entity_id"]) == customer_id
        # `metadata` **vide** : aucune PII (ni contenu de note, ni ancienne valeur).
        assert entry["metadata"] == {}
        # L'actor est bien le gérant (celui qui a créé la fiche).
        created = _fetch_audit_rows(salon, "CUSTOMER_CREATED")
        assert entry["actor_user_id"] == created[0]["actor_user_id"]
        # La note n'apparaît dans AUCUNE colonne d'audit (invariant central #32).
        assert "ZZZ-marqueur-unique-12345" not in _audit_dump(salon)

    def test_note_update_is_atomic_single_audit_entry(self, _e2e_client: TestClient) -> None:
        """Une mutation réussie ⇒ exactement une entrée d'audit correspondante (atomicité)."""
        token, salon = _setup_manager_salon(_e2e_client)
        customer_id = _create_customer(_e2e_client, token, salon)["id"]
        assert _update_note(_e2e_client, token, salon, customer_id, "x").status_code == 200

        assert len(_fetch_audit_rows(salon, "CUSTOMER_NOTE_UPDATED")) == 1

    def test_note_update_cross_salon_returns_404(self, _e2e_client: TestClient) -> None:
        """PUT sur une fiche d'un autre salon (dans **son** salon) → `404` après portée."""
        token_a, salon_a = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_B_LOCAL, name=_SALON_NAME_B
        )
        customer_b = _create_customer(_e2e_client, token_b, salon_b)["id"]

        resp = _update_note(_e2e_client, token_a, salon_a, customer_b, "tentative")
        assert resp.status_code == 404, resp.text

    def test_note_update_out_of_scope_returns_403(self, _e2e_client: TestClient) -> None:
        """PUT en ciblant un salon hors périmètre → `403` générique (portée avant fiche)."""
        token_a, _ = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_B_LOCAL, name=_SALON_NAME_B
        )
        customer_b = _create_customer(_e2e_client, token_b, salon_b)["id"]

        resp = _update_note(_e2e_client, token_a, salon_b, customer_b, "tentative")
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Accès refusé."

    def test_note_update_without_token_returns_401_no_mutation(self, _e2e_client: TestClient) -> None:
        """PUT sans jeton → `401`, sans mutation ni entrée d'audit (deny-by-default)."""
        token, salon = _setup_manager_salon(_e2e_client)
        customer_id = _create_customer(
            _e2e_client, token, salon, notes="Note conservée"
        )["id"]

        resp = _e2e_client.put(
            f"/salons/{salon}/customers/{customer_id}/notes",
            json={"notes": "injection"},
        )
        assert resp.status_code == 401
        # Aucune mutation : la note d'origine subsiste.
        assert _fetch_customer_row(customer_id)["notes"] == "Note conservée"
        # Aucune trace d'audit de mise à jour.
        assert _fetch_audit_rows(salon, "CUSTOMER_NOTE_UPDATED") == []


# ─── E. Round-trip de la migration 0005 ──────────────────────────────────────


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoque le **CLI Alembic** (sous-processus) depuis `backend/`, comme en CI.

    On mirrore le job CI (`.github/workflows/ci.yml` : `alembic downgrade …` /
    `alembic upgrade head`) plutôt que l'API `alembic.command` en processus : seule
    l'exécution CLI charge `alembic.ini` et applique fidèlement la convention de
    nommage (`ck_customer_profiles_gender`) — le correctif `op.f()` post-#28 n'est
    validé que dans ces conditions. `DATABASE_URL` est hérité de l'environnement.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestMigration0005RoundTripE2E:
    """`downgrade`/`upgrade` de la seule révision `0005` (correctif `op.f()` post-#28).

    `0005` est la **tête** de révision : `downgrade 0004` ne réverse qu'elle,
    `upgrade head` la ré-applique. Isolé dans son propre test, il **restaure `head`**
    en `finally` pour ne laisser aucun effet de bord aux autres fichiers e2e du job.
    """

    def test_round_trip_recreates_partial_index_and_check(self) -> None:
        """Le round-trip ne lève aucune erreur `op.f()` ; l'index partiel et le `CHECK` réapparaissent."""
        # Pré-condition : la base est à `head` (index/CHECK/colonne présents).
        assert _schema_object_present(column=True)
        assert _schema_object_present(index=True)
        assert _schema_object_present(check=True)

        try:
            down = _run_alembic("downgrade", "0004")
            assert down.returncode == 0, f"downgrade 0004 échoué : {down.stderr}"
            # Downgrade complet : les trois objets ont disparu.
            assert not _schema_object_present(column=True)
            assert not _schema_object_present(index=True)
            assert not _schema_object_present(check=True)

            up = _run_alembic("upgrade", "head")
            assert up.returncode == 0, f"upgrade head échoué : {up.stderr}"
            # Upgrade : réapparition sans double-préfixage du nom de contrainte
            # (`ck_customer_profiles_gender` bien reconstruit, pas d'erreur `op.f()`).
            assert _schema_object_present(column=True)
            assert _schema_object_present(index=True)
            assert _schema_object_present(check=True)
        finally:
            # `head` restauré quoi qu'il arrive (idempotent si déjà à `head`).
            restore = _run_alembic("upgrade", "head")
            assert restore.returncode == 0, f"restauration head échouée : {restore.stderr}"


# ─── F. Filtres CustomerFilter — chemin SQL réel (#40) ───────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCustomerFilterSqlE2E:
    """`SqlCustomerRepository.list_for_salon`/`count_for_salon` contre PostgreSQL réel.

    Les tests unitaires/cas d'usage (dépôts *fakes*) ne peuvent couvrir ni la
    collation `ILIKE` réelle, ni l'échappement effectif de `%`/`_` par
    `escape_like`, ni le comportement d'inclusivité d'une plage de dates contre une
    vraie colonne `TIMESTAMP`. Ces tests appellent le dépôt **directement**
    (nouvelle `Session`), comme le bloc B, pour isoler `SqlCustomerRepository` du
    routeur HTTP.
    """

    def test_percent_literal_is_escaped_not_treated_as_wildcard(
        self, _e2e_client: TestClient
    ) -> None:
        """`q="50%"` ne matche que le nom contenant **littéralement** "50%" (§ échappement `LIKE`).

        Sans `escape_like`, `%` serait un joker : le motif `%50%%` équivaudrait à
        « contient 50 » et retournerait aussi une fiche qui porte "50" **sans** le
        `%` — la fiche « Anniversaire 50 ans Koné » ci-dessous.
        """
        token, salon = _setup_manager_salon(_e2e_client)
        salon_uuid = uuid.UUID(salon)
        _create_customer(_e2e_client, token, salon, full_name="Réduction 50% Koné")
        _create_customer(_e2e_client, token, salon, full_name="Anniversaire 50 ans Koné")
        _create_customer(_e2e_client, token, salon, full_name="Awa Koné")

        session = get_sessionmaker()()
        try:
            results = SqlCustomerRepository(session).list_for_salon(
                salon_uuid,
                filter=validate_customer_filter(q="50%"),
                limit=50,
                offset=0,
            )
        finally:
            session.close()

        assert len(results) == 1
        assert results[0].full_name == "Réduction 50% Koné"

    def test_count_for_salon_matches_filtered_page(self, _e2e_client: TestClient) -> None:
        """`count_for_salon` sous le même filtre `q` égale la taille de la page."""
        token, salon = _setup_manager_salon(_e2e_client)
        salon_uuid = uuid.UUID(salon)
        _create_customer(_e2e_client, token, salon, full_name="Réduction 50% Koné")
        _create_customer(_e2e_client, token, salon, full_name="Anniversaire 50 ans Koné")
        _create_customer(_e2e_client, token, salon, full_name="Ibrahim Traoré")
        filter_ = validate_customer_filter(q="Koné")

        session = get_sessionmaker()()
        try:
            repository = SqlCustomerRepository(session)
            results = repository.list_for_salon(
                salon_uuid, filter=filter_, limit=50, offset=0
            )
            total = repository.count_for_salon(salon_uuid, filter=filter_)
        finally:
            session.close()

        assert total == len(results) == 2

    def test_gender_exact_match_filtering(self, _e2e_client: TestClient) -> None:
        """`gender="FEMALE"` ne retourne que les fiches portant exactement cette valeur."""
        token, salon = _setup_manager_salon(_e2e_client)
        salon_uuid = uuid.UUID(salon)
        female_id = _create_customer(
            _e2e_client, token, salon, full_name="Awa Koné", gender="FEMALE"
        )["id"]
        _create_customer(
            _e2e_client, token, salon, full_name="Ibrahim Traoré", gender="MALE"
        )
        _create_customer(
            _e2e_client, token, salon, full_name="Sana Ouattara", gender="OTHER"
        )

        session = get_sessionmaker()()
        try:
            results = SqlCustomerRepository(session).list_for_salon(
                salon_uuid,
                filter=validate_customer_filter(gender="FEMALE"),
                limit=50,
                offset=0,
            )
        finally:
            session.close()

        assert {str(c.id) for c in results} == {female_id}
        assert all(c.gender == "FEMALE" for c in results)

    def test_created_at_range_filter_inclusive_at_both_bounds(
        self, _e2e_client: TestClient
    ) -> None:
        """`created_from`/`created_to` incluent les deux **bornes exactes** du jour civil."""
        token, salon = _setup_manager_salon(_e2e_client)
        salon_uuid = uuid.UUID(salon)
        target_day = datetime.date(2026, 3, 15)
        start_of_day = datetime.datetime.combine(
            target_day, datetime.time.min, tzinfo=datetime.timezone.utc
        )
        end_of_day = datetime.datetime.combine(
            target_day, datetime.time(23, 59, 59, 999999), tzinfo=datetime.timezone.utc
        )
        just_before = start_of_day - datetime.timedelta(microseconds=1)

        at_start_id = _create_customer(_e2e_client, token, salon, full_name="Fiche Borne Début")["id"]
        at_end_id = _create_customer(_e2e_client, token, salon, full_name="Fiche Borne Fin")["id"]
        outside_id = _create_customer(_e2e_client, token, salon, full_name="Fiche Hors Plage")["id"]
        _set_customer_created_at(at_start_id, start_of_day)
        _set_customer_created_at(at_end_id, end_of_day)
        _set_customer_created_at(outside_id, just_before)

        session = get_sessionmaker()()
        try:
            results = SqlCustomerRepository(session).list_for_salon(
                salon_uuid,
                filter=validate_customer_filter(
                    created_from=target_day, created_to=target_day
                ),
                limit=50,
                offset=0,
            )
        finally:
            session.close()

        result_ids = {str(c.id) for c in results}
        assert result_ids == {at_start_id, at_end_id}
        assert outside_id not in result_ids

    def test_isolation_holds_under_filter(self, _e2e_client: TestClient) -> None:
        """Une fiche d'un autre salon matchant le même `q` n'apparaît jamais."""
        token_a, salon_a = _setup_manager_salon(_e2e_client)
        token_b, salon_b = _setup_manager_salon(
            _e2e_client, phone=_PHONE_B_LOCAL, name=_SALON_NAME_B
        )
        _create_customer(_e2e_client, token_a, salon_a, full_name="Awa Koné")
        _create_customer(_e2e_client, token_b, salon_b, full_name="Awa Koné")

        session = get_sessionmaker()()
        try:
            results = SqlCustomerRepository(session).list_for_salon(
                uuid.UUID(salon_a),
                filter=validate_customer_filter(q="Awa"),
                limit=50,
                offset=0,
            )
        finally:
            session.close()

        assert len(results) == 1
        assert results[0].salon_id == uuid.UUID(salon_a)
