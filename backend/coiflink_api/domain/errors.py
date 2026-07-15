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


class EmployeeAlreadyInSalon(DomainError):
    """Cet utilisateur est déjà membre (employé) de ce salon (doublon refusé, #13).

    Levée quand l'unicité `(salon_id, user_id)` de la table d'appartenance
    `salon_members` est violée : un même compte n'est employé qu'une fois par
    salon. Le message reste neutre (ni PII ni détail SQL) — l'adapter entrant la
    traduit en `409 Conflict`.
    """


class InvalidSalonName(DomainError):
    """Le nom du salon fourni est vide ou hors bornes (US-2.1, #15)."""


class InvalidLocation(DomainError):
    """Les coordonnées du salon sont incomplètes ou hors bornes (US-2.1, #15).

    Levée quand une seule des deux coordonnées est fournie, ou quand la latitude
    (`[-90, 90]`) / la longitude (`[-180, 180]`) sort de ses bornes. Message
    neutre — l'adapter entrant la traduit en `422`.
    """


class InvalidOpeningHours(DomainError):
    """La structure d'horaires d'ouverture soumise est incohérente (US-2.2, #16).

    Levée par `domain/opening_hours.py` (heures malformées, intervalles
    chevauchants, dates d'exception invalides, horaires entièrement fermés, bornes
    de robustesse dépassées…). Message **neutre** — ni valeur soumise in extenso
    ni détail SQL. L'adapter entrant la traduit en `422`.
    """


class SalonNotFound(DomainError):
    """Le salon visé n'existe pas (US-2.1, #15).

    N'est traduite en `404` **qu'après** validation de la portée : un salon hors
    périmètre a déjà reçu un `403` générique (aucun oracle d'existence, §11.2).
    """


class InvalidMediaType(DomainError):
    """Type MIME de média hors liste blanche (`image/jpeg|png|webp`, #15)."""


class PhotoLimitExceeded(DomainError):
    """Le salon a atteint le nombre maximal de photos (`MEDIA_MAX_PHOTOS`, #15)."""


class MediaKeyMismatch(DomainError):
    """La clé d'objet soumise n'appartient pas au préfixe du salon ciblé (#15).

    Garde-fou d'isolation (§11.2) : sans cette revalidation, un gérant pourrait
    faire référencer par son salon une clé appartenant à un autre salon. Traduite
    en `422` par l'adapter entrant.
    """


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


class NotAuthenticated(DomainError):
    """Aucune identité exploitable pour la requête (autorisation, #12).

    Jeton absent, illisible, expiré, de mauvais `type` (un refresh présenté comme
    jeton d'accès), ou compte du `sub` introuvable. **Volontairement indistincte**
    (comme `InvalidCredentials`) : l'adapter entrant la traduit en `401` avec un
    message générique unique, qui ne révèle jamais le motif exact.
    """


class PermissionDenied(DomainError):
    """Identité valide, mais droit ou portée insuffisants (autorisation, #12).

    Couvre le rôle non habilité, la permission absente de la matrice (PRD §4.1)
    et l'**accès inter-salons** (PRD §11.2). Le message reste **générique** : il ne
    nomme jamais la ressource visée ni son propriétaire — un refus ne doit pas
    renseigner sur ce qui existe chez autrui.
    """


__all__ = [
    "DomainError",
    "InvalidName",
    "InvalidPhone",
    "InvalidEmail",
    "InvalidPassword",
    "PhoneAlreadyInUse",
    "EmailAlreadyInUse",
    "EmployeeAlreadyInSalon",
    "InvalidSalonName",
    "InvalidLocation",
    "InvalidOpeningHours",
    "SalonNotFound",
    "InvalidMediaType",
    "PhotoLimitExceeded",
    "MediaKeyMismatch",
    "InvalidOtp",
    "OtpExpired",
    "InvalidCredentials",
    "TooManyLoginAttempts",
    "InvalidToken",
    "ExpiredToken",
    "NotAuthenticated",
    "PermissionDenied",
]
