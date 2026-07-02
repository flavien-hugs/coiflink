"""Cas d'usage : **inscription d'un client** (application, ADR-0008).

Orchestre le parcours US-1.1 (issue #8) en s'appuyant uniquement sur des **ports**
(interfaces) — aucune dépendance à FastAPI, SQLAlchemy, argon2 ou au SMS. Le
câblage des adapters concrets est fait par le composition root (`main.py`).

Séquence : valider les entrées → **normaliser le téléphone** (forme canonique) →
**pré-vérifier le doublon** → **hacher** le mot de passe → **persister**
(`role=CLIENT`, `status=ACTIVE`) → si activé, émettre un OTP (capacité testable,
envoi différé M5) → retourner l'entité créée **sans** secret.

Garde-fous : le mot de passe en clair n'est ni journalisé ni conservé au-delà de
l'appel de hachage ; le refus de doublon est garanti par le pré-check **et** par
la contrainte base (l'adapter retraduit l'`IntegrityError` concurrente en
`TelephoneDejaUtilise`).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from random import Random, SystemRandom
from typing import Callable

from coiflink_api.application.ports.depot_otp import DepotOtp
from coiflink_api.application.ports.depot_utilisateur import DepotUtilisateur
from coiflink_api.application.ports.expediteur_otp import ExpediteurOtp
from coiflink_api.application.ports.hacheur_mot_de_passe import HacheurMotDePasse
from coiflink_api.domaine.enums import Role, UserStatus
from coiflink_api.domaine.erreurs import TelephoneDejaUtilise
from coiflink_api.domaine.mot_de_passe import valider_mot_de_passe
from coiflink_api.domaine.otp import (
    LONGUEUR_OTP_DEFAUT,
    MAX_ESSAIS_OTP_DEFAUT,
    TTL_OTP_DEFAUT,
    generer_defi_otp,
)
from coiflink_api.domaine.telephone import normaliser_telephone
from coiflink_api.domaine.utilisateur import Utilisateur, UtilisateurACreer, valider_nom


def _horloge_utc() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


@dataclass(frozen=True)
class CommandeInscription:
    """Données d'entrée du cas d'usage (mot de passe en clair, éphémère)."""

    full_name: str
    telephone: str
    mot_de_passe: str
    email: str | None = None


class InscrireClient:
    """Cas d'usage d'inscription d'un client (rôle `CLIENT`)."""

    def __init__(
        self,
        depot: DepotUtilisateur,
        hacheur: HacheurMotDePasse,
        *,
        otp_active: bool = False,
        expediteur_otp: ExpediteurOtp | None = None,
        depot_otp: DepotOtp | None = None,
        rng: Random | None = None,
        horloge: Callable[[], datetime.datetime] | None = None,
        longueur_otp: int = LONGUEUR_OTP_DEFAUT,
        ttl_otp: datetime.timedelta = TTL_OTP_DEFAUT,
        max_essais_otp: int = MAX_ESSAIS_OTP_DEFAUT,
    ) -> None:
        self._depot = depot
        self._hacheur = hacheur
        self._otp_active = otp_active
        self._expediteur_otp = expediteur_otp
        self._depot_otp = depot_otp
        # RNG cryptographique par défaut (les tests injectent un Random graine).
        self._rng: Random = rng if rng is not None else SystemRandom()
        self._horloge = horloge if horloge is not None else _horloge_utc
        self._longueur_otp = longueur_otp
        self._ttl_otp = ttl_otp
        self._max_essais_otp = max_essais_otp

    def executer(self, commande: CommandeInscription) -> Utilisateur:
        """Crée le compte client et retourne l'entité (sans secret)."""

        nom = valider_nom(commande.full_name)
        valider_mot_de_passe(commande.mot_de_passe)
        telephone = normaliser_telephone(commande.telephone)
        email = commande.email or None

        # Pré-vérification applicative du doublon (message clair → 409).
        if self._depot.telephone_existe(telephone):
            raise TelephoneDejaUtilise(
                "Ce numéro de téléphone est déjà associé à un compte."
            )

        condensat = self._hacheur.hacher(commande.mot_de_passe)

        a_creer = UtilisateurACreer(
            full_name=nom,
            telephone=telephone,
            password_hash=condensat,
            email=email,
            role=Role.CLIENT.value,
            status=UserStatus.ACTIVE.value,
        )
        # `creer` peut lever TelephoneDejaUtilise (fallback course concurrente via
        # la contrainte base `uq_users_phone`) : on laisse remonter tel quel.
        utilisateur = self._depot.creer(a_creer)

        if self._otp_active:
            self._emettre_otp(telephone)

        return utilisateur

    def _emettre_otp(self, telephone: str) -> None:
        """Génère, stocke et déclenche l'envoi d'un OTP (envoi stub en #8).

        Non bloquant : l'inscription reste valable même sans infra SMS (M5). Le
        code n'est jamais retourné ni journalisé.
        """

        defi = generer_defi_otp(
            self._rng,
            self._horloge(),
            longueur=self._longueur_otp,
            ttl=self._ttl_otp,
            max_essais=self._max_essais_otp,
        )
        if self._depot_otp is not None:
            self._depot_otp.enregistrer(telephone, defi)
        if self._expediteur_otp is not None:
            self._expediteur_otp.envoyer(telephone, defi.code)


__all__ = ["CommandeInscription", "InscrireClient"]
