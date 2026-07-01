"""Environnement Alembic — migrations PostgreSQL CoifLink.

Importe la `metadata` de l'adapter sortant de persistance (la source de vérité
du schéma) et configure le contexte de migration. Le DSN est lu **depuis
l'environnement** (`DATABASE_URL`) et normalisé sur le driver psycopg 3
(ADR-0009) ; aucun identifiant n'est codé en dur (PRD §11).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importer le paquet de persistance enregistre tous les modèles dans la metadata.
from coiflink_api.adapters.sortant.persistance import Base  # noqa: F401
import coiflink_api.adapters.sortant.persistance  # noqa: F401  (enregistre les modèles)
from coiflink_api.adapters.sortant.persistance.session import database_url

# Objet de configuration Alembic (donne accès aux valeurs du fichier .ini).
config = context.config

# Configuration de la journalisation (le .ini ne dumpe aucune donnée).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata cible pour l'autogenerate et les comparaisons.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Exécute les migrations en mode « offline » (génération de SQL, sans connexion)."""

    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Exécute les migrations en mode « online » (connexion réelle à PostgreSQL)."""

    configuration = config.get_section(config.config_ini_section) or {}
    # Le DSN provient de l'environnement, jamais du fichier .ini.
    configuration["sqlalchemy.url"] = database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
