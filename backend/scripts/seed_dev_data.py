"""Jeu de données de développement — comptes, salons et employés de démo.

Peuple une instance **locale** (API + base) via le contrat HTTP réel (aucun
contournement du domaine : mots de passe hachés par le parcours d'inscription
normal, `owner_id`/`role` imposés côté serveur comme en production). Quatre
exceptions ciblées passent par une requête SQL directe, faute d'endpoint HTTP
pour ces réglages à ce stade du produit :
- suspendre un compte (aucun endpoint d'administration des comptes encore) ;
- fixer des horaires d'ouverture (`opening_hours`, différé à une issue
  ultérieure) pour démontrer l'état « réservable » (§8.3) d'un salon ;
- promouvoir un compte `ADMIN` (aucun endpoint d'inscription `ADMIN`, PRD §9.1 —
  le compte est d'abord inscrit `CLIENT` par l'API, puis promu par SQL, comme
  dans les tests e2e de la supervision plateforme, #37) ;
- insérer des tickets walk-in de démo avec un jour/statut contrôlés (aucune API
  cliente ne permet d'émettre un ticket `done`/`expired` sur un jour passé sans
  simuler toute la borne + le cycle de vie complet — même contournement ciblé
  que les suites e2e du dashboard, #148/#157). Les **paiements**, eux, passent
  par l'API réelle (`POST /payments`) : c'est ce qui peuple le journal de caisse
  et donc le chiffre d'affaires (#40).

Idempotent : un numéro déjà enregistré (409) est traité comme « déjà présent »
et le script continue plutôt que d'échouer. L'activité de démo (tickets/
paiements) n'est semée qu'une fois par salon — si des tickets **antérieurs à
aujourd'hui** existent déjà pour le salon d'Aïcha, cette étape est simplement
ignorée au lieu d'accumuler des doublons.

Usage (backend/) :
    uvicorn coiflink_api.main:app --reload &   # ou via docker compose
    DATABASE_URL=postgresql://... python scripts/seed_dev_data.py

Variables d'environnement :
    API_BASE_URL   URL de l'API (défaut http://127.0.0.1:8000)
    DATABASE_URL   DSN PostgreSQL (requis — mêmes réglages que l'app/Alembic)
"""

from __future__ import annotations

import datetime
import json
import os
import sys

import httpx
import psycopg

from coiflink_api.domain.phone import normalize_phone

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Mot de passe commun à tous les comptes de démo (politique : 8-128 caractères).
# Volontairement identique partout pour simplifier les essais manuels.
DEV_PASSWORD = "CoifLink#2026"


def _register(client: httpx.Client, path: str, *, full_name: str, phone: str, email: str | None = None) -> str | None:
    """Inscrit un compte ; retourne son id, ou None si déjà existant (409)."""

    resp = client.post(
        path,
        json={"full_name": full_name, "phone": phone, "password": DEV_PASSWORD, "email": email},
    )
    if resp.status_code == 201:
        print(f"  + créé  : {full_name} ({phone})")
        return resp.json()["id"]
    if resp.status_code == 409:
        print(f"  = existe déjà : {full_name} ({phone})")
        return None
    resp.raise_for_status()
    return None  # pragma: no cover - inatteignable (raise_for_status lève avant)


def _login(client: httpx.Client, phone: str) -> str:
    resp = client.post("/auth/login", json={"identifier": phone, "password": DEV_PASSWORD})
    resp.raise_for_status()
    return resp.json()["access_token"]


def _ensure_salon(client: httpx.Client, token: str, *, name: str, **fields: object) -> str:
    """Crée le salon du gérant s'il n'en a pas déjà un ; retourne son id."""

    auth = {"Authorization": f"Bearer {token}"}
    existing = client.get("/salons", headers=auth)
    existing.raise_for_status()
    salons = existing.json()
    if salons:
        print(f"  = salon déjà présent pour ce gérant : {salons[0]['name']}")
        return salons[0]["id"]

    resp = client.post("/salons", headers=auth, json={"name": name, **fields})
    resp.raise_for_status()
    salon_id = resp.json()["id"]
    print(f"  + salon créé : {name}")
    return salon_id


def _create_employee(client: httpx.Client, token: str, salon_id: str, *, full_name: str, phone: str) -> None:
    resp = client.post(
        f"/salons/{salon_id}/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": full_name, "phone": phone, "password": DEV_PASSWORD},
    )
    if resp.status_code == 201:
        print(f"  + employé créé : {full_name} ({phone})")
    elif resp.status_code == 409:
        print(f"  = employé déjà membre : {full_name} ({phone})")
    else:
        resp.raise_for_status()


def _suspend_by_phone(phone: str) -> None:
    """Bascule un compte en `SUSPENDED` par SQL direct (pas d'endpoint HTTP)."""

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET status = 'SUSPENDED' WHERE phone = %s", (normalize_phone(phone),)
        )
        conn.commit()


def _promote_to_admin_by_phone(phone: str) -> None:
    """Promeut un compte `ADMIN` par SQL direct (aucun endpoint d'inscription ADMIN, PRD §9.1)."""

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET role = 'ADMIN' WHERE phone = %s", (normalize_phone(phone),)
        )
        conn.commit()


def _set_opening_hours_by_owner_phone(phone: str) -> None:
    """Fixe des horaires factices sur le salon du propriétaire (démo §8.3)."""

    hours = {"mon-fri": "09:00-19:00", "sat": "09:00-17:00"}
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE salons SET opening_hours = %s::jsonb
            WHERE owner_id = (SELECT id FROM users WHERE phone = %s)
            """,
            (json.dumps(hours), normalize_phone(phone)),
        )
        conn.commit()


def _user_id_by_phone(phone: str) -> str:
    """Résout l'id d'un compte déjà inscrit par son numéro (idempotence des reruns)."""

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE phone = %s", (normalize_phone(phone),))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Utilisateur introuvable pour {phone!r} (inscription échouée ?)")
        return str(row[0])


def _ensure_service(
    client: httpx.Client, token: str, salon_id: str, *, name: str, price: str, duration_minutes: int
) -> str:
    """Crée une prestation si aucune du même nom n'existe déjà pour ce salon (idempotent).

    `POST /salons/{id}/services` n'impose aucune unicité de nom : sans ce
    contrôle préalable, relancer le script dupliquerait les prestations à
    chaque exécution.
    """

    auth = {"Authorization": f"Bearer {token}"}
    existing = client.get(f"/salons/{salon_id}/services", headers=auth)
    existing.raise_for_status()
    for service in existing.json():
        if service["name"] == name:
            print(f"  = prestation déjà présente : {name}")
            return service["id"]

    resp = client.post(
        f"/salons/{salon_id}/services",
        headers=auth,
        json={"name": name, "price": price, "duration_minutes": duration_minutes},
    )
    resp.raise_for_status()
    print(f"  + prestation créée : {name} ({price} FCFA)")
    return resp.json()["id"]


def _provision_and_activate_terminal(
    client: httpx.Client, manager_token: str, salon_id: str, *, label: str
) -> tuple[str, str]:
    """Provisionne une borne puis l'active immédiatement — miroir du geste du gérant.

    Deux appels réels, comme en production : `POST .../terminal-devices` (gérant,
    rend un code d'activation à 6 chiffres, jamais le secret) puis
    `POST /auth/terminal/activate` (public, échange le code contre `device_id` +
    `secret` — le secret n'est **jamais** relisible après cet appel, d'où la garde
    d'idempotence en amont dans `main()`, pas ici).
    """

    resp = client.post(
        f"/salons/{salon_id}/terminal-devices",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"label": label},
    )
    resp.raise_for_status()
    activation_code = resp.json()["activation_code"]
    print(f"  + borne provisionnée : {label} (code d'activation : {activation_code})")

    resp = client.post("/auth/terminal/activate", json={"code": activation_code})
    resp.raise_for_status()
    body = resp.json()
    print(f"  + borne activée : device_id={body['device_id']}")
    return body["device_id"], body["secret"]


def _terminal_login(client: httpx.Client, device_id: str, secret: str) -> str:
    resp = client.post("/auth/terminal/login", json={"device_id": device_id, "secret": secret})
    resp.raise_for_status()
    return resp.json()["access_token"]


def _create_walk_in_customer(
    client: httpx.Client, terminal_token: str, salon_id: str, *, first_name: str, last_name: str, phone: str
) -> str:
    """Crée une fiche walk-in via la borne (`POST .../terminal/customers`, #156)."""

    resp = client.post(
        f"/salons/{salon_id}/terminal/customers",
        headers={"Authorization": f"Bearer {terminal_token}"},
        json={"first_name": first_name, "last_name": last_name, "phone": phone},
    )
    resp.raise_for_status()
    customer_id = resp.json()["customer_id"]
    print(f"  + fiche walk-in créée : {first_name} {last_name} ({phone})")
    return customer_id


def _join_queue(
    client: httpx.Client,
    terminal_token: str,
    salon_id: str,
    *,
    customer_profile_id: str,
    service_ids: list[str],
) -> None:
    """Émet un ticket de passage via la borne (`POST .../queue/tickets`, #157)."""

    resp = client.post(
        f"/salons/{salon_id}/queue/tickets",
        headers={"Authorization": f"Bearer {terminal_token}"},
        json={"customer_profile_id": customer_profile_id, "service_ids": service_ids},
    )
    resp.raise_for_status()
    ticket = resp.json()
    print(f"  + ticket émis : N° {ticket['ticket_number']} (attente estimée {ticket['estimated_wait_minutes']} min)")


def _customer_profile_has_tickets(customer_profile_id: str) -> bool:
    """Vrai si cette fiche a déjà des tickets (garde d'idempotence de l'activité de démo).

    Scopé à la fiche de démo (`customer_profile_id`), pas au salon entier : un
    salon de dev accumule aussi de vrais tickets manuels (borne, essais manuels)
    au fil des jours, qui deviendraient tous « antérieurs à aujourd'hui » sans
    jamais correspondre au seed d'historique de ce module — un garde salon-large
    se déclencherait donc à tort dès le lendemain de tout essai manuel.
    """

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM queue_tickets WHERE customer_profile_id = %s)",
            (customer_profile_id,),
        )
        return bool(cur.fetchone()[0])


def _salon_terminal_device_id(salon_id: str) -> str | None:
    """Id de la borne déjà provisionnée pour ce salon, ou `None` (garde d'idempotence).

    Résolu par SQL direct (et non `GET /salons/{id}/terminal-devices`) car la
    ré-exécution du script doit pouvoir décider de **sauter tout le bloc borne**
    (provisioning + activation + walk-in + ticket) avant même le premier appel HTTP :
    le code d'activation et le secret ne sont, par construction, jamais relisibles
    une fois émis (§11.3) — il n'y a donc rien à « re-provisionner à moitié ».
    """

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE role = 'TERMINAL' AND id IN "
            "(SELECT user_id FROM salon_members WHERE salon_id = %s)",
            (salon_id,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None


def _ensure_customer_profile(
    client: httpx.Client, token: str, salon_id: str, *, full_name: str, phone: str
) -> str:
    """Crée une fiche cliente walk-in via l'API gérant (`POST .../customers`), idempotent.

    Distinct d'un compte `users` (rôle CLIENT) : une fiche `customer_profiles`
    est **salon-scopée**, sans connexion possible — c'est elle, et non un compte
    utilisateur, que référence `queue_tickets.customer_profile_id` (#148/#157).
    Un doublon de téléphone dans ce salon (409) n'est pas une erreur : la fiche
    existante est résolue par recherche de nom (aucun filtre par téléphone côté
    liste), comme pour `_ensure_salon`.
    """

    resp = client.post(
        f"/salons/{salon_id}/customers",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": full_name, "phone": phone},
    )
    if resp.status_code == 409:
        existing = client.get(
            f"/salons/{salon_id}/customers",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": full_name},
        )
        existing.raise_for_status()
        for customer in existing.json()["items"]:
            if customer["phone"] == normalize_phone(phone):
                print(f"  = fiche cliente déjà présente : {full_name} ({phone})")
                return customer["id"]
        raise RuntimeError(
            f"Fiche cliente {full_name!r}/{phone!r} en conflit (409) mais introuvable par recherche."
        )
    resp.raise_for_status()
    customer_id = resp.json()["id"]
    print(f"  + fiche cliente créée : {full_name} ({phone})")
    return customer_id


def _next_ticket_number(salon_id: str, day: datetime.date) -> int:
    """Prochain `ticket_number` libre pour ce salon/jour (évite toute collision avec la borne)."""

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(ticket_number), 0) FROM queue_tickets "
            "WHERE salon_id = %s AND issued_date = %s",
            (salon_id, day),
        )
        return int(cur.fetchone()[0]) + 1


def _seed_ticket(
    *,
    salon_id: str,
    customer_profile_id: str,
    hairdresser_id: str | None,
    service_ids: list[str],
    day: datetime.date,
    status: str,
    estimated_wait_minutes: int = 15,
) -> str:
    """Insère directement en base un ticket walk-in démo (statut/jour contrôlés) avec ses prestations.

    Aucune API cliente ne permet d'émettre un ticket `in_progress`/`done`/
    `expired` sur un jour passé sans simuler toute la borne + le cycle de vie
    complet — bypass ciblé, hors flux client, miroir du patron des suites e2e du
    dashboard (`test_dashboard_e2e.py`, `test_service_demand_e2e.py`).
    """

    now = datetime.datetime.now(datetime.timezone.utc)
    started_at = now if status in ("in_progress", "done") else None
    completed_at = now if status == "done" else None
    ticket_number = _next_ticket_number(salon_id, day)

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO queue_tickets "
            "(salon_id, ticket_number, issued_date, customer_profile_id, hairdresser_id, "
            "status, estimated_wait_minutes, started_at, completed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                salon_id,
                ticket_number,
                day,
                customer_profile_id,
                hairdresser_id,
                status,
                estimated_wait_minutes,
                started_at,
                completed_at,
            ),
        )
        ticket_id = str(cur.fetchone()[0])
        for service_id in service_ids:
            cur.execute(
                "INSERT INTO queue_ticket_services (salon_id, queue_ticket_id, service_id) "
                "VALUES (%s, %s, %s)",
                (salon_id, ticket_id, service_id),
            )
        conn.commit()
    return ticket_id


def _record_payment_for_ticket(
    client: httpx.Client,
    token: str,
    salon_id: str,
    *,
    queue_ticket_id: str,
    amount: str,
) -> None:
    """Encaisse un ticket `done` via l'API réelle (le journal de caisse pilote le CA, #40).

    Pas de `client_id` : ce champ référence un compte `users` (rôle CLIENT),
    distinct de la fiche `customer_profiles` du ticket walk-in — un encaissement
    comptoir n'a normalement aucun compte rattaché (#148/#157).
    """

    resp = client.post(
        f"/salons/{salon_id}/payments",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "amount": amount,
            "payment_method": "CASH",
            "queue_ticket_id": queue_ticket_id,
        },
    )
    resp.raise_for_status()
    print(f"  + paiement encaissé : {amount} FCFA (ticket {queue_ticket_id})")


def main() -> int:
    if not DATABASE_URL:
        print("error: DATABASE_URL est requis (SQL direct pour suspension/horaires).", file=sys.stderr)
        return 1

    with httpx.Client(base_url=API_BASE_URL, timeout=10.0) as client:
        print("Gérants")
        _register(client, "/auth/register/manager", full_name="Aïcha Koné", phone="0701020304")
        _register(client, "/auth/register/manager", full_name="Fatou Diabaté", phone="0705060708")
        _register(client, "/auth/register/manager", full_name="Ibrahim Touré", phone="0709101112")

        print("\nSalon d'Aïcha (réservable — horaires fixés)")
        token_aicha = _login(client, "0701020304")
        salon_id = _ensure_salon(
            client,
            token_aicha,
            name="Salon Élégance Cocody",
            description="Coiffure afro, tresses et soins capillaires.",
            phone="0701020304",
            address="Rue des Jardins, Cocody",
            city="Abidjan",
            commune="Cocody",
        )
        _set_opening_hours_by_owner_phone("0701020304")

        print("\nEmployé du salon d'Aïcha")
        _create_employee(client, token_aicha, salon_id, full_name="Awa Bamba", phone="0701121314")
        hairdresser_id = _user_id_by_phone("0701121314")

        print("\nPrestations du salon d'Aïcha")
        service_coupe = _ensure_service(
            client, token_aicha, salon_id, name="Coupe & Brushing", price="5000.00", duration_minutes=45
        )
        service_tresses = _ensure_service(
            client, token_aicha, salon_id, name="Tresses", price="15000.00", duration_minutes=120
        )
        service_soin = _ensure_service(
            client, token_aicha, salon_id, name="Soin capillaire", price="8000.00", duration_minutes=60
        )
        service_coloration = _ensure_service(
            client, token_aicha, salon_id, name="Coloration", price="12000.00", duration_minutes=90
        )

        print("\nBorne (terminal) du salon d'Aïcha — walk-in + file d'attente (#155/#156/#157)")
        terminal_credential: tuple[str, str] | None = None
        existing_terminal_id = _salon_terminal_device_id(salon_id)
        if existing_terminal_id is not None:
            print(f"  = borne déjà provisionnée (device_id={existing_terminal_id}) — secret non relisible, seed ignoré")
        else:
            device_id, device_secret = _provision_and_activate_terminal(
                client, token_aicha, salon_id, label="Borne accueil"
            )
            terminal_credential = (device_id, device_secret)
            terminal_token = _terminal_login(client, device_id, device_secret)

            walkin_id = _create_walk_in_customer(
                client, terminal_token, salon_id,
                first_name="Aminata", last_name="Diarra", phone="0706070809",
            )
            _join_queue(
                client, terminal_token, salon_id,
                customer_profile_id=walkin_id, service_ids=[service_coupe],
            )

            walkin_id_2 = _create_walk_in_customer(
                client, terminal_token, salon_id,
                first_name="Yssouf", last_name="Traoré", phone="0706070810",
            )
            _join_queue(
                client, terminal_token, salon_id,
                customer_profile_id=walkin_id_2, service_ids=[service_soin, service_coloration],
            )

        print("\nFiche cliente du salon d'Aïcha (historique de visites pour peupler le dashboard, #40/#41/#148)")
        history_customer_id = _ensure_customer_profile(
            client, token_aicha, salon_id, full_name="Koffi N'Guessan", phone="0702030405"
        )

        if _customer_profile_has_tickets(history_customer_id):
            print("  = activité déjà présente (tickets/paiements de cette fiche) — seed ignoré")
        else:
            today = datetime.date.today()
            done_tickets: list[tuple[str, str]] = []  # (queue_ticket_id, montant)

            def _seed(
                *, day: datetime.date, status: str, service_id: str, price: str,
                assigned: bool = True,
            ) -> None:
                ticket_id = _seed_ticket(
                    salon_id=salon_id,
                    customer_profile_id=history_customer_id,
                    hairdresser_id=hairdresser_id if assigned else None,
                    service_ids=[service_id],
                    day=day,
                    status=status,
                )
                if status == "done":
                    done_tickets.append((ticket_id, price))

            print("  Tickets du jour (statuts variés, #148)")
            _seed(day=today, status="waiting", service_id=service_soin, price="8000.00", assigned=False)
            _seed(day=today, status="in_progress", service_id=service_tresses, price="15000.00")
            _seed(day=today, status="done", service_id=service_coloration, price="12000.00")
            _seed(day=today, status="expired", service_id=service_coupe, price="5000.00", assigned=False)

            print("  Historique réalisé (prestations les plus demandées, US-6.3 #41)")
            _seed(day=today - datetime.timedelta(days=1), status="done",
                  service_id=service_coupe, price="5000.00")
            _seed(day=today - datetime.timedelta(days=2), status="done",
                  service_id=service_coupe, price="5000.00")
            _seed(day=today - datetime.timedelta(days=3), status="done",
                  service_id=service_tresses, price="15000.00")
            _seed(day=today - datetime.timedelta(days=10), status="done",
                  service_id=service_soin, price="8000.00")

            print("  Encaissement des tickets terminés (chiffre d'affaires, US-6.2 #40)")
            for queue_ticket_id, amount in done_tickets:
                _record_payment_for_ticket(
                    client, token_aicha, salon_id,
                    queue_ticket_id=queue_ticket_id, amount=amount,
                )

        print("\nFatou (aucun salon — formulaire de création à tester)")
        # Volontairement : pas d'appel _ensure_salon ici.

        print("\nIbrahim (suspendu après coup — connexion refusée par la suite)")
        _suspend_by_phone("0709101112")

        print("\nClient (pour tester le refus de rôle sur le dashboard gérant)")
        _register(client, "/auth/register", full_name="Mariam Sanogo", phone="0705161718")

        print("\nAdmin plateforme (supervision inter-salons, #37)")
        _register(client, "/auth/register", full_name="Adama Ouattara", phone="0700112233")
        _promote_to_admin_by_phone("0700112233")

    print("\n" + "=" * 72)
    print("Comptes de démo — mot de passe commun :", DEV_PASSWORD)
    print("=" * 72)
    rows = [
        ("Aïcha Koné", "0701020304", "MANAGER", "ACTIVE", "salon réservable, dashboard peuplé (#40/#41/#148)"),
        ("Fatou Diabaté", "0705060708", "MANAGER", "ACTIVE", "sans salon"),
        ("Ibrahim Touré", "0709101112", "MANAGER", "SUSPENDED", "connexion refusée (401 générique)"),
        ("Awa Bamba", "0701121314", "HAIRDRESSER", "ACTIVE", "refus de rôle sur /gerant"),
        ("Mariam Sanogo", "0705161718", "CLIENT", "ACTIVE", "refus de rôle sur /gerant"),
        ("Adama Ouattara", "0700112233", "ADMIN", "ACTIVE", "supervision plateforme /admin"),
    ]
    for full_name, phone, role, status_, note in rows:
        print(f"  {full_name:<16} {phone:<14} {role:<12} {status_:<10} {note}")
    print()
    print(
        "  Fiche cliente walk-in « Koffi N'Guessan » (0702030405) : pas de compte/connexion,"
        " historique de visites chez Aïcha (customer_profiles, #148)."
    )
    print()

    if terminal_credential is not None:
        device_id, device_secret = terminal_credential
        print("Borne (terminal) du salon d'Aïcha — credential émis à l'instant, non relisible ensuite")
        print("  " + "-" * 68)
        print(f"  device_id : {device_id}")
        print(f"  secret    : {device_secret}")
        print("  " + "-" * 68)
        print("  À utiliser côté app-mobile via l'écran d'activation (le code à 6")
        print("  chiffres est celui affiché ci-dessus lors du provisioning), ou en")
        print("  direct : POST /auth/terminal/login {device_id, secret}.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
