"""Peuplement / **teardown** d'un jeu de données représentatif pour la charge (#52).

Le seed monte un décor **via l'API HTTP réelle** (jamais d'`INSERT` brut d'une
entité qui a un endpoint) — même patron que les `*_e2e.py` (`test_critical_journeys_e2e`) :
cohérence garantie par les invariants métier (machine à états des tickets walk-in,
journal de caisse append-only). Tout est **borné à la plage de téléphones réservée**
`config.RESERVED_PHONE_PREFIX` pour un **nettoyage FK-safe** ciblé.

Invariants §11 respectés :
- données **synthétiques** (comptes fictifs de la plage réservée) ;
- **aucune** PII journalisée : on **compte**, on n'affiche jamais un numéro, un nom,
  un jeton ni un montant nominatif ;
- jetons obtenus par **login HTTP réel** (rôle correct) — jamais un secret de prod,
  jamais tracés ;
- teardown **FK-safe** (`campaigns` avant `queue_tickets`/`payments`/`cash_journal`/
  `salons`/`users` ; les bornes `TERMINAL` provisionnées pour le seed sont nettoyées
  avec leur salon, pas par leur téléphone — sentinelle hex, hors plage réservée).

Ce module dépend de l'extra `perf` (`httpx`). Il n'est **pas** importé par le *test
gate* : `run.py` l'importe paresseusement, après avoir vérifié la présence de l'extra.
"""

from __future__ import annotations

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
# Sous-plages disjointes de `config.local_phone(index)` (index 0..9999) pour les
# comptes `users` (gérants, coiffeurs, clients) : ces trois-là partagent la
# contrainte d'unicité **globale** `users.phone` et doivent donc rester disjoints.
# Dimensionnées pour la volumétrie par défaut (10 salons, 30 coiffeurs, 100 clients)
# avec une marge confortable.

_MANAGER_INDEX_BASE = 0       # 0000..0999 : un gérant par salon
_HAIRDRESSER_INDEX_BASE = 1000  # 1000..3999 : coiffeurs (employés de salon)
_CLIENT_INDEX_BASE = 4000     # 4000..9999 : clients

# Fiches walk-in (`customer_profiles.phone`) de l'historique de tickets : table et
# contrainte d'unicité **distinctes** de `users.phone` (unique **par salon**, pas
# globalement) — réutiliser le même espace 0..9999 est donc sans risque de
# collision réelle, y compris avec les bases ci-dessus.
_HISTORY_PHONE_BASE = 0

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
    coiffeurs + borne walk-in) → historique de tickets `done` + encaissements.
    Best-effort sur l'historique (un échec d'un ticket n'interrompt pas le seed) ;
    aucune PII journalisée.
    """

    dataset = dataset or config.DatasetProfile()
    with _SeedClient(base_url, timeout=timeout) as client:
        clients = _seed_clients(client, dataset, password)
        salons = _seed_salons(client, dataset, password)
        history = _seed_history(client, dataset, salons)
        logger.info(
            "Seed perf terminé : %d salons, %d clients, %d tickets historiques (%d échecs).",
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

        terminal_token = _provision_terminal(client, salon_id, manager_token, label=f"Borne perf {s}")

        salons.append(
            (
                SalonFixture(
                    salon_id=salon_id,
                    manager_token=manager_token,
                    terminal_token=terminal_token,
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


def _provision_terminal(client: _SeedClient, salon_id: str, manager_token: str, *, label: str) -> str:
    """Provisionne + active une borne walk-in pour le salon, renvoie son jeton d'accès.

    Deux appels réels, comme en production (patron `scripts/seed_dev_data.py`) :
    `POST .../terminal-devices` (gérant, code d'activation à 6 chiffres) puis
    `POST /auth/terminal/activate` (public, échange le code contre `device_id`/
    `secret` — jamais relisible ensuite). Le compte `TERMINAL` créé porte une
    sentinelle de téléphone (`device_id` hex, hors plage réservée) : son nettoyage
    passe par `salon_members`/`salon_id`, pas par `users.phone` (cf. `wipe_perf_data`).
    """

    provision = client.post(
        f"/salons/{salon_id}/terminal-devices", json={"label": label}, token=manager_token
    )
    provision.raise_for_status()
    activation_code = provision.json()["activation_code"]

    activate = client.post("/auth/terminal/activate", json={"code": activation_code})
    activate.raise_for_status()
    body = activate.json()

    login = client.post(
        "/auth/terminal/login", json={"device_id": body["device_id"], "secret": body["secret"]}
    )
    login.raise_for_status()
    return login.json()["access_token"]


def _seed_history(
    client: _SeedClient,
    dataset: config.DatasetProfile,
    salons: list[tuple[SalonFixture, list[str]]],
) -> dict[str, int]:
    """Crée des tickets `done` + encaissements pour des agrégats dashboard non triviaux.

    Chaque ticket : fiche walk-in (borne) → ticket (borne) → prise en charge → clôture
    → encaissement (gérant, montant = prix figé). Best-effort : un échec (fiche/ticket/
    encaissement) est compté comme échec, jamais fatal. Contrairement à l'ancien RDV,
    un ticket n'a pas de date future planifiée : l'historique est daté du jour de son
    émission (aucun paramètre de date sur les endpoints réels), suffisant pour des
    agrégats non triviaux au moment du run. Les paiements alimentent le CA (#40), les
    tickets la demande de prestations (#41) et la performance des coiffeurs (#43).
    """

    if not salons:
        return {"completed": 0, "failed": 0}

    target = dataset.completed_tickets
    per_salon = max(1, -(-target // len(salons)))  # ceil
    completed = 0
    failed = 0

    for fixture, prices in salons:
        for made in range(per_salon):
            if completed >= target:
                break
            service_pos = made % len(fixture.service_ids)
            service_id = fixture.service_ids[service_pos]
            price = prices[service_pos]
            if _complete_one_ticket(client, fixture, service_id, price, made):
                completed += 1
            else:
                failed += 1
        if completed >= target:
            break
    return {"completed": completed, "failed": failed}


def _complete_one_ticket(
    client: _SeedClient,
    fixture: SalonFixture,
    service_id: str,
    price: str,
    index: int,
) -> bool:
    """Fiche walk-in → ticket → prise en charge → clôture → encaisse. `True` si tout aboutit."""

    if not fixture.hairdresser_ids:
        return False

    customer = client.post(
        f"/salons/{fixture.salon_id}/terminal/customers",
        json={
            "first_name": "Perf",
            "last_name": f"Historique{index}",
            "phone": config.local_phone((_HISTORY_PHONE_BASE + index) % 10_000),
        },
        token=fixture.terminal_token,
    )
    if customer.status_code != 201:
        return False
    customer_profile_id = customer.json()["customer_id"]

    ticket = client.post(
        f"/salons/{fixture.salon_id}/queue/tickets",
        json={"customer_profile_id": customer_profile_id, "service_ids": [service_id]},
        token=fixture.terminal_token,
    )
    if ticket.status_code != 201:
        return False
    ticket_id = ticket.json()["id"]

    hairdresser_id = fixture.hairdresser_ids[index % len(fixture.hairdresser_ids)]
    start = client.post(
        f"/salons/{fixture.salon_id}/queue/tickets/{ticket_id}/start",
        json={"hairdresser_id": hairdresser_id},
        token=fixture.manager_token,
    )
    if start.status_code != 200:
        return False

    complete = client.post(
        f"/salons/{fixture.salon_id}/queue/tickets/{ticket_id}/complete",
        token=fixture.manager_token,
    )
    if complete.status_code != 200:
        return False

    payment = client.post(
        f"/salons/{fixture.salon_id}/payments",
        json={"amount": price, "payment_method": "CASH", "queue_ticket_id": ticket_id},
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

    Ordre (FK `ON DELETE RESTRICT`) : audit_logs → campaigns → cash_journal →
    payments → queue_ticket_services → queue_tickets → customer_profiles →
    services → salon_members → bornes `TERMINAL` (identifiées **avant** la
    suppression de `salon_members`, supprimées **après**) → salon_photos → salons
    → users. `notifications`/`appointments`/`appointment_services` ont disparu avec
    le module RDV (migration `0017`) — plus rien à nettoyer de ce côté.
    `cash_journal` avant `payments` ; `payments`/`queue_ticket_services` avant
    `queue_tickets` ; `queue_tickets` avant `customer_profiles` (référencées par
    `customer_profile_id`). Les bornes `TERMINAL` provisionnées pour le seed
    (`_provision_terminal`) portent une sentinelle de téléphone (`device_id` hex)
    **hors** `RESERVED_PHONE_PREFIX` : leur nettoyage passe par leur rattachement
    `salon_members`/`salon_id`, pas par `users.phone` — sans quoi elles
    s'accumuleraient indéfiniment d'un run à l'autre. Leurs ids doivent être
    **capturés avant** de supprimer `salon_members` (FK `RESTRICT` : un `user`
    encore référencé par `salon_members` ne peut pas être supprimé) puis leur
    suppression n'intervient **qu'après** — d'où le `SELECT` isolé ci-dessous,
    plutôt qu'une sous-requête imbriquée dans un unique `DELETE`. Tout le reste est
    borné par `RESERVED_PHONE_PREFIX`.
    """

    prefix = f"{config.RESERVED_PHONE_PREFIX}%"
    salons_of_prefix = (
        "SELECT id FROM salons WHERE owner_id IN "
        "(SELECT id FROM users WHERE phone LIKE :prefix)"
    )
    users_of_prefix = "SELECT id FROM users WHERE phone LIKE :prefix"

    with engine.connect() as conn:
        terminal_user_ids = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT user_id FROM salon_members WHERE role = 'TERMINAL' "
                    f"AND salon_id IN ({salons_of_prefix})"
                ),
                {"prefix": prefix},
            )
        ]

        statements = [
            f"DELETE FROM audit_logs WHERE salon_id IN ({salons_of_prefix}) "
            f"OR actor_user_id IN ({users_of_prefix})",
            f"DELETE FROM campaigns WHERE salon_id IN ({salons_of_prefix}) "
            f"OR created_by IN ({users_of_prefix})",
            f"DELETE FROM cash_journal WHERE salon_id IN ({salons_of_prefix})",
            f"DELETE FROM payments WHERE salon_id IN ({salons_of_prefix})",
            f"DELETE FROM queue_ticket_services WHERE salon_id IN ({salons_of_prefix})",
            f"DELETE FROM queue_tickets WHERE salon_id IN ({salons_of_prefix})",
            f"DELETE FROM customer_profiles WHERE salon_id IN ({salons_of_prefix})",
            f"DELETE FROM services WHERE salon_id IN ({salons_of_prefix})",
            f"DELETE FROM salon_members WHERE salon_id IN ({salons_of_prefix}) "
            f"OR user_id IN ({users_of_prefix})",
            f"DELETE FROM salon_photos WHERE salon_id IN ({salons_of_prefix})",
            f"DELETE FROM salons WHERE owner_id IN ({users_of_prefix})",
            "DELETE FROM users WHERE phone LIKE :prefix",
        ]
        for statement in statements:
            conn.execute(text(statement), {"prefix": prefix})

        if terminal_user_ids:
            conn.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"),
                {"ids": terminal_user_ids},
            )
        conn.commit()


__all__ = [
    "seed",
    "wipe_perf_data",
    "build_cleanup_engine",
]
