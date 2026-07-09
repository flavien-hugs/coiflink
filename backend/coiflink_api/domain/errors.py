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


class InvalidCredentials(DomainError):
    """Échec d'authentification à la connexion (#10).

    **Volontairement indistincte** : identifiant inconnu, mot de passe faux **ou**
    compte non `ACTIVE` lèvent la *même* erreur, avec le *même* message générique,
    pour ne jamais divulguer l'existence ou l'état d'un compte (anti-énumération,
    PRD §11.1). Ne transporte donc aucun détail sur le motif exact.
    """


class TooManyLoginAttempts(DomainError):
    """Trop d'échecs de connexion sur la fenêtre glissante (anti-bruteforce, #10).

    Peut porter un `retry_after` (secondes) que l'adapter entrant expose via
    l'en-tête HTTP `Retry-After` accompagnant le `429 Too Many Requests`.
    """

    def __init__(self, message: str = "", *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InvalidToken(DomainError):
    """Jeton (refresh) absent, altéré, de mauvaise signature ou de mauvais `type`."""


class ExpiredToken(DomainError):
    """Jeton (refresh) dont la fenêtre de validité (`exp`) est dépassée."""


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
    "InvalidCredentials",
    "TooManyLoginAttempts",
    "InvalidToken",
    "ExpiredToken",
]
