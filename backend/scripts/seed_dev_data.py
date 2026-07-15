"""Jeu de données de développement — comptes, salons et employés de démo.

Peuple une instance **locale** (API + base) via le contrat HTTP réel (aucun
contournement du domaine : mots de passe hachés par le parcours d'inscription
normal, `owner_id`/`role` imposés côté serveur comme en production). Seules
deux exceptions ciblées passent par une requête SQL directe, faute d'endpoint
HTTP pour ces réglages à ce stade du produit :
- suspendre un compte (aucun endpoint d'administration des comptes encore) ;
- fixer des horaires d'ouverture (`opening_hours`, différé à une issue
  ultérieure) pour démontrer l'état « réservable » (§8.3) d'un salon.

Idempotent : un numéro déjà enregistré (409) est traité comme « déjà présent »
et le script continue plutôt que d'échouer.

Usage (backend/) :
    uvicorn coiflink_api.main:app --reload &   # ou via docker compose
    DATABASE_URL=postgresql://... python scripts/seed_dev_data.py

Variables d'environnement :
    API_BASE_URL   URL de l'API (défaut http://127.0.0.1:8000)
    DATABASE_URL   DSN PostgreSQL (requis — mêmes réglages que l'app/Alembic)
"""

from __future__ import annotations

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

        print("\nFatou (aucun salon — formulaire de création à tester)")
        # Volontairement : pas d'appel _ensure_salon ici.

        print("\nIbrahim (suspendu après coup — connexion refusée par la suite)")
        _suspend_by_phone("0709101112")

        print("\nClient (pour tester le refus de rôle sur le dashboard gérant)")
        _register(client, "/auth/register", full_name="Mariam Sanogo", phone="0705161718")

    print("\n" + "=" * 72)
    print("Comptes de démo — mot de passe commun :", DEV_PASSWORD)
    print("=" * 72)
    rows = [
        ("Aïcha Koné", "0701020304", "MANAGER", "ACTIVE", "salon réservable"),
        ("Fatou Diabaté", "0705060708", "MANAGER", "ACTIVE", "sans salon"),
        ("Ibrahim Touré", "0709101112", "MANAGER", "SUSPENDED", "connexion refusée (401 générique)"),
        ("Awa Bamba", "0701121314", "HAIRDRESSER", "ACTIVE", "refus de rôle sur /gerant"),
        ("Mariam Sanogo", "0705161718", "CLIENT", "ACTIVE", "refus de rôle sur /gerant"),
    ]
    for full_name, phone, role, status_, note in rows:
        print(f"  {full_name:<16} {phone:<14} {role:<12} {status_:<10} {note}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
