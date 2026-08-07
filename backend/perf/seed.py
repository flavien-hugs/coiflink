"""Peuplement / **teardown** d'un jeu de données représentatif pour la charge (#52).

Le seed monte un décor **via l'API HTTP réelle** (jamais d'`INSERT` brut d'une
entité qui a un endpoint) — même patron que les `*_e2e.py` (`test_critical_journeys_e2e`,
`test_appointment_notification_e2e`) : cohérence garantie par les invariants métier
(machine à états des RDV, contrainte d'exclusion #21, journal de caisse append-only).
Tout est **borné à la plage de téléphones réservée** `config.RESERVED_PHONE_PREFIX`
pour un **nettoyage FK-safe** ciblé.

Invariants §11 respectés :
- données **synthétiques** (comptes fictifs de la plage réservée) ;
- **aucune** PII journalisée : on **compte**, on n'affiche jamais un numéro, un nom,
  un jeton ni un montant nominatif ;
- jetons obtenus par **login HTTP réel** (rôle correct) — jamais un secret de prod,
  jamais tracés ;
- teardown **FK-safe** (`notifications`/`campaigns` avant `appointments`/`payments`/
  `cash_journal`/`salons`/`users`, mémoire projet `notifications-fk-restrict-cleanup`).

Ce module dépend de l'extra `perf` (`httpx`). Il n'est **pas** importé par le *test
gate* : `run.py` l'importe paresseusement, après avoir vérifié la présence de l'extra.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import Engine, create_engine, text

from coiflink_api.adapters.outbound.persistence.session import normalize_dsn

from . import config
from .scenarios import SalonFixture, SeedContext

logger = logging.getLogger("perf.seed")

# ─── Allocation déterministe des numéros dans la plage réservée ───────────────
#
# Sous-plages disjointes de `config.local_phone(index)` (index 0..9999) : gérants,
# coiffeurs, clients. Dimensionnées pour la volumétrie par défaut (10 salons, 30
# coiffeurs, 100 clients) avec une marge confortable.

_MANAGER_INDEX_BASE = 0       # 0000..0999 : un gérant par salon
_HAIRDRESSER_INDEX_BASE = 1000  # 1000..3999 : coiffeurs (employés de salon)
_CLIENT_INDEX_BASE = 4000     # 4000..9999 : clients

# Jeu de villes/communes synthétiques (aucune PII) pour varier la recherche §12.1.
_CITIES = ["Abidjan", "Bouaké", "Yamoussoukro", "San-Pédro", "Korhogo"]
_COMMUNES = ["Cocody", "Yopougon", "Plateau", "Marcory", "Treichville", "Adjamé"]

# Prix synthétiques (chaîne `NUMERIC(12,2)`) des prestations seedées, indexés par
# position de prestation dans le salon — l'encaissement exige le prix figé (§8.2).
_SERVICE_PRICES = ["3000.00", "5000.00", "7500.00", "10000.00", "12000.00", "15000.00"]
_SERVICE_DURATION_MIN = 30

# Horaires d'ouverture larges (lundi→samedi) : maximise les créneaux disponibles
# pour le seed historique et le scénario de réservation.
_OPENING_HOURS = {
    "weekly": {
        day: [{"start": "08:00", "end": "18:00"}]
        for day in ("mon", "tue", "wed", "thu", "fri", "sat")
    }
}


# ─── Identités seedées (produites par `seed`, consommées par les scénarios) ───


@dataclass
class _ClientIdentity:
    """Un client seedé : id + jeton d'accès (jamais tracé)."""

    user_id: str
    token: str


# ─── Client HTTP de seed (httpx, séquentiel) ──────────────────────────────────


class _SeedClient:
    """Fin wrapper httpx pour le peuplement séquentiel (pas de mesure de latence)."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> _SeedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def post(
        self, path: str, *, json: dict | None = None, token: str | None = None
    ) -> httpx.Response:
        return self._client.post(path, json=json, headers=_auth(token))

    def put(
        self, path: str, *, json: dict | None = None, token: str | None = None
    ) -> httpx.Response:
        return self._client.put(path, json=json, headers=_auth(token))

    def get(
        self, path: str, *, params: dict | None = None, token: str | None = None
    ) -> httpx.Response:
        return self._client.get(path, params=params, headers=_auth(token))


def _auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


# ─── Helpers de peuplement (via endpoints réels) ──────────────────────────────


def _register(client: _SeedClient, path: str, *, phone: str, full_name: str, password: str) -> str:
    resp = client.post(path, json={"full_name": full_name, "phone": phone, "password": password})
    resp.raise_for_status()
    return resp.json()["id"]


def _login(client: _SeedClient, *, phone: str, password: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def _opening_days_ahead(count: int) -> list[datetime.date]:
    """Les `count` prochains jours **ouvrés** (lundi→samedi), à partir de demain."""

    days: list[datetime.date] = []
    cursor = datetime.date.today() + datetime.timedelta(days=1)
    while len(days) < count:
        if cursor.weekday() != 6:  # exclut le dimanche (fermé)
            days.append(cursor)
        cursor += datetime.timedelta(days=1)
    return days


# ─── Seed principal ───────────────────────────────────────────────────────────


def seed(
    base_url: str,
    dataset: config.DatasetProfile | None = None,
    *,
    password: str = config.SEED_PASSWORD,
    timeout: float = 30.0,
) -> SeedContext:
    """Peuple `base_url` d'un jeu représentatif et renvoie le `SeedContext` de charge.

    Étapes (toutes via l'API réelle) : clients → salons (horaires + prestations +
    coiffeurs) → historique de RDV `COMPLETED` + encaissements. Best-effort sur
    l'historique (un créneau plein n'interrompt pas le seed) ; aucune PII journalisée.
    """

    dataset = dataset or config.DatasetProfile()
    with _SeedClient(base_url, timeout=timeout) as client:
        clients = _seed_clients(client, dataset, password)
        salons = _seed_salons(client, dataset, password)
        history = _seed_history(client, dataset, salons, clients)
        logger.info(
            "Seed perf terminé : %d salons, %d clients, %d RDV historiques (%d échecs de créneau).",
            len(salons),
            len(clients),
            history["completed"],
            history["failed"],
        )
        token_clients = [c.token for c in clients[: dataset.token_clients]]
        search_terms = _search_terms(salons)
        return SeedContext(
            salons=[fixture for fixture, _price in salons],
            client_tokens=token_clients,
            search_terms=search_terms,
        )


def _seed_clients(
    client: _SeedClient, dataset: config.DatasetProfile, password: str
) -> list[_ClientIdentity]:
    """Inscrit les clients ; ne connecte (jeton) que les `token_clients` premiers."""

    identities: list[_ClientIdentity] = []
    for i in range(dataset.clients):
        # Forme **locale** ; l'API la normalise en `+225…` (cf. `domain/phone.py`),
        # ce qui la place dans `RESERVED_PHONE_PREFIX` — patron des `*_e2e.py`.
        phone = config.local_phone(_CLIENT_INDEX_BASE + i)
        user_id = _register(
            client, "/auth/register", phone=phone, full_name=f"Perf Client {i}", password=password
        )
        token = ""
        if i < dataset.token_clients:
            token = _login(client, phone=phone, password=password)
        identities.append(_ClientIdentity(user_id=user_id, token=token))
    return identities


def _seed_salons(
    client: _SeedClient, dataset: config.DatasetProfile, password: str
) -> list[tuple[SalonFixture, list[str]]]:
    """Monte les salons réservables (gérant, horaires, prestations, coiffeurs).

    Renvoie, par salon, le `SalonFixture` (consommé par les scénarios) **et** la liste
    des prix figés de ses prestations (nécessaires à l'encaissement de l'historique).
    """

    salons: list[tuple[SalonFixture, list[str]]] = []
    for s in range(dataset.salons):
        manager_phone = config.local_phone(_MANAGER_INDEX_BASE + s)
        _register(
            client,
            "/auth/register/manager",
            phone=manager_phone,
            full_name=f"Perf Manager {s}",
            password=password,
        )
        manager_token = _login(client, phone=manager_phone, password=password)

        name = f"CoifLink Perf Salon {s:03d}"
        city = _CITIES[s % len(_CITIES)]
        commune = _COMMUNES[s % len(_COMMUNES)]
        resp = client.post(
            "/salons", json={"name": name, "city": city, "commune": commune}, token=manager_token
        )
        resp.raise_for_status()
        salon_id = resp.json()["id"]

        client.put(
            f"/salons/{salon_id}/opening-hours", json=_OPENING_HOURS, token=manager_token
        ).raise_for_status()

        service_ids: list[str] = []
        prices: list[str] = []
        for k in range(dataset.services_per_salon):
            price = _SERVICE_PRICES[k % len(_SERVICE_PRICES)]
            resp = client.post(
                f"/salons/{salon_id}/services",
                json={
                    "name": f"Prestation {k}",
                    "price": price,
                    "duration_minutes": _SERVICE_DURATION_MIN,
                },
                token=manager_token,
            )
            resp.raise_for_status()
            service_ids.append(resp.json()["id"])
            prices.append(price)

        hairdresser_ids: list[str] = []
        for h in range(dataset.hairdressers_per_salon):
            index = _HAIRDRESSER_INDEX_BASE + s * dataset.hairdressers_per_salon + h
            phone = config.local_phone(index)
            resp = client.post(
                f"/salons/{salon_id}/employees",
                json={"full_name": f"Perf Coiffeur {s}-{h}", "phone": phone, "password": password},
                token=manager_token,
            )
            resp.raise_for_status()
            hairdresser_ids.append(resp.json()["id"])

        salons.append(
            (
                SalonFixture(
                    salon_id=salon_id,
                    manager_token=manager_token,
                    service_ids=service_ids,
                    hairdresser_ids=hairdresser_ids,
                    name=name,
                    city=city,
                    commune=commune,
                ),
                prices,
            )
        )
    return salons


def _seed_history(
    client: _SeedClient,
    dataset: config.DatasetProfile,
    salons: list[tuple[SalonFixture, list[str]]],
    clients: list[_ClientIdentity],
) -> dict[str, int]:
    """Crée des RDV `COMPLETED` + encaissements pour des agrégats dashboard non triviaux.

    Chaque RDV : réservation (client) → `CONFIRMED` → `COMPLETED` (gérant) →
    encaissement (gérant, montant = prix figé). Best-effort : un créneau indisponible
    (journée pleine, course) est compté comme échec, jamais fatal. Les paiements
    « maintenant » alimentent le CA du jour (#40) ; les RDV alimentent le décompte du
    jour (#39), la demande de prestations (#41), les clients actifs (#42) et la
    performance des coiffeurs (#43).
    """

    bookers = [c for c in clients if c.token]
    if not bookers or not salons:
        return {"completed": 0, "failed": 0}

    target = dataset.completed_appointments
    per_salon = max(1, -(-target // len(salons)))  # ceil
    days = _opening_days_ahead(12)
    completed = 0
    failed = 0
    booker_ix = 0

    for fixture, prices in salons:
        made = 0
        for day in days:
            if made >= per_salon or completed >= target:
                break
            service_pos = made % len(fixture.service_ids)
            service_id = fixture.service_ids[service_pos]
            price = prices[service_pos]
            slots = _availability_slots(client, fixture.salon_id, day, service_id)
            for slot in slots:
                if made >= per_salon or completed >= target:
                    break
                booker = bookers[booker_ix % len(bookers)]
                booker_ix += 1
                ok = _complete_one(
                    client, fixture, service_id, price, booker, day, slot["start"]
                )
                if ok:
                    completed += 1
                    made += 1
                else:
                    failed += 1
        if completed >= target:
            break
    return {"completed": completed, "failed": failed}


def _availability_slots(
    client: _SeedClient, salon_id: str, day: datetime.date, service_id: str
) -> list[dict]:
    resp = client.get(
        f"/catalog/salons/{salon_id}/availability",
        params={"date": day.isoformat(), "service_id": service_id},
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("slots", [])


def _complete_one(
    client: _SeedClient,
    fixture: SalonFixture,
    service_id: str,
    price: str,
    booker: _ClientIdentity,
    day: datetime.date,
    start_time: str,
) -> bool:
    """Réserve → CONFIRMED → COMPLETED → encaisse un RDV. `True` si tout aboutit."""

    booking = client.post(
        f"/salons/{fixture.salon_id}/appointments",
        json={"date": day.isoformat(), "start_time": start_time, "service_ids": [service_id]},
        token=booker.token,
    )
    if booking.status_code != 201:
        return False
    appointment_id = booking.json()["id"]

    for status_value in ("CONFIRMED", "COMPLETED"):
        resp = client.post(
            f"/salons/{fixture.salon_id}/appointments/{appointment_id}/status",
            json={"status": status_value},
            token=fixture.manager_token,
        )
        if resp.status_code != 200:
            return False

    payment = client.post(
        f"/salons/{fixture.salon_id}/payments",
        json={
            "amount": price,
            "payment_method": "CASH",
            "appointment_id": appointment_id,
            "client_id": booker.user_id,
        },
        token=fixture.manager_token,
    )
    return payment.status_code == 201


def _search_terms(salons: list[tuple[SalonFixture, list[str]]]) -> list[str]:
    """Termes de recherche non-PII qui matchent le catalogue seedé (fragments de nom)."""

    terms = {"Perf", "CoifLink", "Salon"}
    for fixture, _prices in salons:
        terms.add(fixture.name.split()[-1])  # le suffixe numérique
    return sorted(terms)


# ─── Teardown FK-safe (SQL, borné à la plage réservée) ────────────────────────


def build_cleanup_engine(database_url: str) -> Engine:
    """Engine SQLAlchemy dédié au nettoyage, normalisé sur psycopg 3 (ADR-0009)."""

    return create_engine(normalize_dsn(database_url), pool_pre_ping=True, future=True)


def wipe_perf_data(engine: Engine) -> None:
    """Supprime **toutes** les données de perf (plage réservée) dans l'ordre FK-safe.

    Ordre (FK `ON DELETE RESTRICT`) : audit_logs → notifications → campaigns →
    cash_journal → payments → appointment_services → appointments → services →
    salon_members → salon_photos → salons → users. `notifications`/`campaigns`
    **avant** `appointments`/`salons`/`users` (mémoire `notifications-fk-restrict-cleanup`) ;
    `cash_journal` avant `payments` ; `payments`/`appointment_services` avant
    `appointments`/`services`. Tout est borné par `RESERVED_PHONE_PREFIX`.
    """

    prefix = f"{config.RESERVED_PHONE_PREFIX}%"
    salons_of_prefix = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    users_of_prefix = "SELECT id FROM users WHERE phone LIKE :prefix"
    statements = [
        f"DELETE FROM audit_logs WHERE salon_id IN ({salons_of_prefix}) "
        f"OR actor_user_id IN ({users_of_prefix})",
        f"DELETE FROM notifications WHERE salon_id IN ({salons_of_prefix}) "
        f"OR user_id IN ({users_of_prefix})",
        f"DELETE FROM campaigns WHERE salon_id IN ({salons_of_prefix}) "
        f"OR created_by IN ({users_of_prefix})",
        f"DELETE FROM cash_journal WHERE salon_id IN ({salons_of_prefix})",
        f"DELETE FROM payments WHERE salon_id IN ({salons_of_prefix})",
        f"DELETE FROM appointment_services WHERE salon_id IN ({salons_of_prefix})",
        f"DELETE FROM appointments WHERE salon_id IN ({salons_of_prefix})",
        f"DELETE FROM services WHERE salon_id IN ({salons_of_prefix})",
        f"DELETE FROM salon_members WHERE salon_id IN ({salons_of_prefix}) "
        f"OR user_id IN ({users_of_prefix})",
        f"DELETE FROM salon_photos WHERE salon_id IN ({salons_of_prefix})",
        f"DELETE FROM salons WHERE owner_id IN ({users_of_prefix})",
        "DELETE FROM users WHERE phone LIKE :prefix",
    ]
    with engine.connect() as conn:
        for statement in statements:
            conn.execute(text(statement), {"prefix": prefix})
        conn.commit()


__all__ = [
    "seed",
    "wipe_perf_data",
    "build_cleanup_engine",
]
