"""Socle ORM SQLAlchemy de la persistance CoifLink (adapter sortant, ADR-0008).

Ce module ne contient **aucune** règle métier : c'est un détail de persistance.
Il déclare la `DeclarativeBase` et la `MetaData` partagées par tous les modèles
(`modeles.py`) et par l'environnement Alembic (`migrations/env.py`).

La **convention de nommage des contraintes** garantit des noms *déterministes*
(donc des migrations reproductibles et des diff Alembic stables) : clés
primaires, étrangères, index, contraintes d'unicité et `CHECK` reçoivent un nom
prévisible dérivé de la table et des colonnes.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Convention de nommage (cf. spec §3) : préfixe + table + colonne(s).
#   pk_<table>                     ex. pk_users
#   fk_<table>_<col0>              ex. fk_salons_owner_id
#   uq_<table>_<col0>              ex. uq_users_phone
#   ix_<table>_<col0>              ex. ix_services_salon_id
#   ck_<table>_<nom logique>       ex. ck_users_role
# Les contraintes composites (`CHECK`, FK multi-colonnes, `EXCLUDE`) reçoivent un
# nom explicite à la déclaration pour rester lisibles et sans collision.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base déclarative partagée par tous les modèles de persistance."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


__all__ = ["Base", "NAMING_CONVENTION"]
