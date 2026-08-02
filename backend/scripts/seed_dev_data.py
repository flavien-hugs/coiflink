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
- insérer des RDV de démo avec un créneau/statut contrôlés (aucune API cliente
  ne permet de forcer un RDV `COMPLETED`/`CANCELLED`/`NO_SHOW` passé sans
  simuler tout le parcours de réservation + gestion de statut — même
  contournement ciblé que les suites e2e du dashboard, #39/#41). Les
  **paiements**, eux, passent par l'API réelle (`POST /payments`) : c'est ce qui
  peuple le journal de caisse et donc le chiffre d'affaires (#40).

Idempotent : un numéro déjà enregistré (409) est traité comme « déjà présent »
et le script continue plutôt que d'échouer. L'activité de démo (RDV/paiements)
n'est semée qu'une fois par salon — si des RDV existent déjà pour le salon
d'Aïcha, cette étape est simplement ignorée au lieu d'accumuler des doublons.

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


def _salon_appointment_count(salon_id: str) -> int:
    """Compte les RDV déjà enregistrés pour ce salon (garde d'idempotence de l'activité de démo)."""

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM appointments WHERE salon_id = %s", (salon_id,))
        return int(cur.fetchone()[0])


def _end_time(start_time: str, duration_minutes: int) -> str:
    """Calcule l'heure de fin (`HH:MM:SS`) à partir d'une heure de début et d'une durée."""

    start = datetime.datetime.combine(datetime.date.today(), datetime.time.fromisoformat(start_time))
    return (start + datetime.timedelta(minutes=duration_minutes)).time().isoformat()


def _seed_appointment(
    *,
    salon_id: str,
    client_id: str,
    hairdresser_id: str,
    service_id: str,
    price: str,
    day: datetime.date,
    start_time: str,
    duration_minutes: int,
    status: str,
) -> str:
    """Insère directement en base un RDV démo (statut/jour/prix contrôlés) avec sa prestation.

    Aucune API cliente ne permet de créer un RDV `COMPLETED`/`CANCELLED`/`NO_SHOW`
    sans simuler tout le parcours réservation + transition de statut — bypass
    ciblé, hors flux client, miroir du patron des suites e2e du dashboard
    (`test_daily_summary_e2e.py` #39, `test_service_demand_e2e.py` #41).
    L'exclusion de créneau (`ex_appointments_hairdresser_slot`) ne s'applique
    qu'aux statuts `PENDING`/`CONFIRMED` : les horaires ci-dessous les espacent
    pour éviter tout conflit, les autres statuts ne sont de toute façon jamais
    concernés par cette contrainte.
    """

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO appointments "
            "(salon_id, client_id, hairdresser_id, appointment_date, start_time, end_time, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                salon_id,
                client_id,
                hairdresser_id,
                day,
                start_time,
                _end_time(start_time, duration_minutes),
                status,
            ),
        )
        appointment_id = str(cur.fetchone()[0])
        cur.execute(
            "INSERT INTO appointment_services (salon_id, appointment_id, service_id, price_at_booking) "
            "VALUES (%s, %s, %s, %s)",
            (salon_id, appointment_id, service_id, price),
        )
        conn.commit()
    return appointment_id


def _record_payment_for_appointment(
    client: httpx.Client,
    token: str,
    salon_id: str,
    *,
    appointment_id: str,
    amount: str,
    client_id: str,
) -> None:
    """Encaisse un RDV `COMPLETED` via l'API réelle (le journal de caisse pilote le CA, #40)."""

    resp = client.post(
        f"/salons/{salon_id}/payments",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "amount": amount,
            "payment_method": "CASH",
            "appointment_id": appointment_id,
            "client_id": client_id,
        },
    )
    resp.raise_for_status()
    print(f"  + paiement encaissé : {amount} FCFA (RDV {appointment_id})")


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

        print("\nCliente du salon d'Aïcha (historique de RDV pour peupler le dashboard, #39/#40/#41)")
        client_id = (
            _register(client, "/auth/register", full_name="Koffi N'Guessan", phone="0702030405")
            or _user_id_by_phone("0702030405")
        )

        if _salon_appointment_count(salon_id) > 0:
            print("  = activité déjà présente (RDV/paiements) — seed ignoré")
        else:
            today = datetime.date.today()
            completed: list[tuple[str, str]] = []  # (appointment_id, montant)

            def _seed(
                *, day: datetime.date, start_time: str, duration_minutes: int, status: str,
                service_id: str, price: str,
            ) -> None:
                appointment_id = _seed_appointment(
                    salon_id=salon_id,
                    client_id=client_id,
                    hairdresser_id=hairdresser_id,
                    service_id=service_id,
                    price=price,
                    day=day,
                    start_time=start_time,
                    duration_minutes=duration_minutes,
                    status=status,
                )
                if status == "COMPLETED":
                    completed.append((appointment_id, price))

            print("  RDV du jour (statuts variés, US-6.1 #39)")
            _seed(day=today, start_time="09:00", duration_minutes=45, status="CONFIRMED",
                  service_id=service_coupe, price="5000.00")
            _seed(day=today, start_time="10:00", duration_minutes=120, status="CONFIRMED",
                  service_id=service_tresses, price="15000.00")
            _seed(day=today, start_time="12:30", duration_minutes=60, status="PENDING",
                  service_id=service_soin, price="8000.00")
            _seed(day=today, start_time="13:30", duration_minutes=90, status="COMPLETED",
                  service_id=service_coloration, price="12000.00")
            _seed(day=today, start_time="15:00", duration_minutes=45, status="CANCELLED",
                  service_id=service_coupe, price="5000.00")
            _seed(day=today, start_time="16:00", duration_minutes=60, status="NO_SHOW",
                  service_id=service_soin, price="8000.00")

            print("  Historique réalisé (prestations les plus demandées, US-6.3 #41)")
            _seed(day=today - datetime.timedelta(days=1), start_time="10:00", duration_minutes=45,
                  status="COMPLETED", service_id=service_coupe, price="5000.00")
            _seed(day=today - datetime.timedelta(days=2), start_time="10:00", duration_minutes=45,
                  status="COMPLETED", service_id=service_coupe, price="5000.00")
            _seed(day=today - datetime.timedelta(days=3), start_time="10:00", duration_minutes=120,
                  status="COMPLETED", service_id=service_tresses, price="15000.00")
            _seed(day=today - datetime.timedelta(days=10), start_time="10:00", duration_minutes=60,
                  status="COMPLETED", service_id=service_soin, price="8000.00")

            print("  Encaissement des RDV terminés (chiffre d'affaires, US-6.2 #40)")
            for appointment_id, amount in completed:
                _record_payment_for_appointment(
                    client, token_aicha, salon_id,
                    appointment_id=appointment_id, amount=amount, client_id=client_id,
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
        ("Aïcha Koné", "0701020304", "MANAGER", "ACTIVE", "salon réservable, dashboard peuplé (#39/#40/#41)"),
        ("Fatou Diabaté", "0705060708", "MANAGER", "ACTIVE", "sans salon"),
        ("Ibrahim Touré", "0709101112", "MANAGER", "SUSPENDED", "connexion refusée (401 générique)"),
        ("Awa Bamba", "0701121314", "HAIRDRESSER", "ACTIVE", "refus de rôle sur /gerant"),
        ("Koffi N'Guessan", "0702030405", "CLIENT", "ACTIVE", "historique de RDV chez Aïcha"),
        ("Mariam Sanogo", "0705161718", "CLIENT", "ACTIVE", "refus de rôle sur /gerant"),
        ("Adama Ouattara", "0700112233", "ADMIN", "ACTIVE", "supervision plateforme /admin"),
    ]
    for full_name, phone, role, status_, note in rows:
        print(f"  {full_name:<16} {phone:<14} {role:<12} {status_:<10} {note}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
