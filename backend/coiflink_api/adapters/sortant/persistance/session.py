"""Fabrique d'engine & de session SQLAlchemy (adapter sortant, ADR-0008/0009).

Lit `DATABASE_URL` **depuis l'environnement** (aucun secret en dur — PRD §11,
`backend/.env.example`). Fournie initialement pour l'outillage (Alembic, scripts
ponctuels), elle est **câblée à l'application** à partir de #8 : `get_sessionmaker`
et la dépendance FastAPI `get_session` alimentent les cas d'usage (repository
ports) via une session **synchrone** (endpoints exécutés en threadpool par
FastAPI ; migration async possible ultérieurement — cf. ADR-0009).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


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


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    """Fabrique de sessions synchrones (mémoïsée), adossée à `get_engine()`.

    `expire_on_commit=False` évite d'invalider les attributs déjà lus après un
    commit ; `autoflush=False` laisse les cas d'usage maîtriser le `flush`
    (cf. `DepotUtilisateurSql.creer`).
    """

    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête, commit/rollback encadrés.

    Commit si la requête aboutit, rollback si une exception remonte (y compris
    une `HTTPException` levée par l'adapter entrant), puis fermeture systématique.
    """

    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "normaliser_dsn",
    "database_url",
    "get_engine",
    "get_sessionmaker",
    "get_session",
]
