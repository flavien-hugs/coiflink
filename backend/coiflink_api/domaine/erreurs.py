"""Erreurs métier du domaine CoifLink (architecture hexagonale, ADR-0008).

Le domaine lève des erreurs **neutres** : elles ne connaissent pas HTTP. Ce sont
les adapters entrants (`adapters/entrant/`) qui les traduisent en codes de statut
(par ex. `TelephoneDejaUtilise` → `409`, `TelephoneInvalide` → `422`). Aucune de
ces erreurs ne doit transporter de secret ni de donnée personnelle (mot de passe,
condensat, code OTP, numéro de téléphone en clair) dans son message.
"""

from __future__ import annotations


class ErreurDomaine(Exception):
    """Base des erreurs métier — sans dépendance framework/I/O ni HTTP."""


class NomInvalide(ErreurDomaine):
    """Le nom complet fourni est vide ou hors bornes."""


class TelephoneInvalide(ErreurDomaine):
    """Le numéro de téléphone est absent, malformé ou hors bornes."""


class EmailInvalide(ErreurDomaine):
    """L'adresse e-mail fournie n'est pas exploitable."""


class MotDePasseInvalide(ErreurDomaine):
    """Le mot de passe ne respecte pas la politique (longueur minimale...)."""


class TelephoneDejaUtilise(ErreurDomaine):
    """Un compte existe déjà pour ce numéro de téléphone (doublon refusé)."""


class EmailDejaUtilise(ErreurDomaine):
    """Un compte existe déjà pour cette adresse e-mail (doublon refusé)."""


class OtpInvalide(ErreurDomaine):
    """Le code OTP saisi ne correspond pas au défi en cours."""


class OtpExpire(ErreurDomaine):
    """Le code OTP a dépassé sa fenêtre de validité."""


__all__ = [
    "ErreurDomaine",
    "NomInvalide",
    "TelephoneInvalide",
    "EmailInvalide",
    "MotDePasseInvalide",
    "TelephoneDejaUtilise",
    "EmailDejaUtilise",
    "OtpInvalide",
    "OtpExpire",
]
