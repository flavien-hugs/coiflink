"""Erreurs métier du domaine CoifLink (architecture hexagonale, ADR-0008).

Le domaine lève des erreurs **neutres** : elles ne connaissent pas HTTP. Ce sont
les adapters entrants (`adapters/inbound/`) qui les traduisent en codes de statut
(par ex. `PhoneAlreadyInUse` → `409`, `InvalidPhone` → `422`). Aucune de
ces erreurs ne doit transporter de secret ni de donnée personnelle (mot de passe,
condensat, code OTP, numéro de téléphone en clair) dans son message.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base des erreurs métier — sans dépendance framework/I/O ni HTTP."""


class InvalidName(DomainError):
    """Le nom complet fourni est vide ou hors bornes."""


class InvalidPhone(DomainError):
    """Le numéro de téléphone est absent, malformé ou hors bornes."""


class InvalidEmail(DomainError):
    """L'adresse e-mail fournie n'est pas exploitable."""


class InvalidPassword(DomainError):
    """Le mot de passe ne respecte pas la politique (longueur minimale...)."""


class PhoneAlreadyInUse(DomainError):
    """Un compte existe déjà pour ce numéro de téléphone (doublon refusé)."""


class EmailAlreadyInUse(DomainError):
    """Un compte existe déjà pour cette adresse e-mail (doublon refusé)."""


class InvalidOtp(DomainError):
    """Le code OTP saisi ne correspond pas au défi en cours."""


class OtpExpired(DomainError):
    """Le code OTP a dépassé sa fenêtre de validité."""


__all__ = [
    "DomainError",
    "InvalidName",
    "InvalidPhone",
    "InvalidEmail",
    "InvalidPassword",
    "PhoneAlreadyInUse",
    "EmailAlreadyInUse",
    "InvalidOtp",
    "OtpExpired",
]
