"""Adapter sortant : dépôt d'utilisateurs sur SQLAlchemy (ADR-0008/0009).

Implémente le port `DepotUtilisateur` avec une `Session` SQLAlchemy 2.0 sur le
modèle ORM `User` (`modeles.py`). Seul cet adapter connaît SQLAlchemy ; il mappe
l'entité de domaine `UtilisateurACreer` ↔ le modèle ORM et retraduit les
violations d'unicité base en **erreurs de domaine** (jamais de fuite d'un détail
SQLAlchemy vers l'application).

Le champ métier `telephone` correspond à la colonne `phone` (unique
`uq_users_phone`) ; l'e-mail optionnel est unique partiel (`uq_users_email`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.sortant.persistance.modeles import User
from coiflink_api.domaine.erreurs import EmailDejaUtilise, TelephoneDejaUtilise
from coiflink_api.domaine.utilisateur import Utilisateur, UtilisateurACreer


class DepotUtilisateurSql:
    """Dépôt d'utilisateurs adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def telephone_existe(self, telephone: str) -> bool:
        """Vrai si un compte porte déjà ce téléphone (forme canonique)."""

        stmt = select(User.id).where(User.phone == telephone).limit(1)
        return self._session.scalar(stmt) is not None

    def creer(self, utilisateur: UtilisateurACreer) -> Utilisateur:
        """Insère l'utilisateur et retourne l'entité (avec `id`, `created_at`).

        Retraduit la violation de contrainte unique en erreur de domaine :
        `uq_users_phone` → `TelephoneDejaUtilise`, `uq_users_email` →
        `EmailDejaUtilise`. Toute autre `IntegrityError` est propagée telle quelle.
        """

        model = User(
            full_name=utilisateur.full_name,
            phone=utilisateur.telephone,
            email=utilisateur.email,
            password_hash=utilisateur.password_hash,
            role=utilisateur.role,
            status=utilisateur.status,
        )
        self._session.add(model)
        try:
            # `flush` déclenche l'INSERT (et donc les contraintes) sans committer :
            # le commit est piloté par la dépendance de session (`get_session`).
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            detail = str(getattr(exc, "orig", exc))
            if "uq_users_phone" in detail:
                raise TelephoneDejaUtilise(
                    "Ce numéro de téléphone est déjà associé à un compte."
                ) from exc
            if "uq_users_email" in detail:
                raise EmailDejaUtilise(
                    "Cette adresse e-mail est déjà associée à un compte."
                ) from exc
            raise

        # Recharge les valeurs générées côté serveur (id, created_at, status...).
        self._session.refresh(model)
        return Utilisateur(
            id=model.id,
            full_name=model.full_name,
            telephone=model.phone,
            email=model.email,
            role=model.role,
            status=model.status,
            created_at=model.created_at,
        )


__all__ = ["DepotUtilisateurSql"]
