"""Fabrique d'engine SQLAlchemy (adapter sortant de persistance, ADR-0008).

Lit `DATABASE_URL` **depuis l'environnement** (aucun secret en dur — PRD §11,
`backend/.env.example`). Fournie pour l'outillage (Alembic, scripts ponctuels) ;
elle n'est **pas câblée** à l'application FastAPI dans #3 : les *repository
ports* (`application/ports/`) et leurs adapters concrets arrivent avec les
features M1→. La voici volontairement minimale pour éviter de sur-construire.
"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine


def normaliser_dsn(url: str) -> str:
    """Force le driver **psycopg 3** sur un DSN PostgreSQL générique.

    SQLAlchemy interprète `postgresql://` comme psycopg2 (driver hérité) ; on
    bascule explicitement sur `postgresql+psycopg://` (psycopg 3, ADR-0009) sans
    toucher aux DSN déjà qualifiés (`postgresql+asyncpg://`, etc.).
    """

    prefixe = "postgresql://"
    if url.startswith(prefixe):
        return "postgresql+psycopg://" + url[len(prefixe) :]
    return url


def database_url() -> str:
    """Retourne le DSN de connexion, normalisé sur psycopg 3.

    Lève une erreur explicite si `DATABASE_URL` est absent — aucun défaut codé en
    dur, conforme à la lecture de configuration depuis l'environnement.
    """

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL non défini : configurez la connexion via l'environnement "
            "(voir backend/.env.example)."
        )
    return normaliser_dsn(url)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Engine SQLAlchemy synchrone (mémoïsé) lisant le DSN de l'environnement."""

    return create_engine(database_url(), pool_pre_ping=True, future=True)


__all__ = ["normaliser_dsn", "database_url", "get_engine"]
