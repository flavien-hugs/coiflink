"""Normalisation & validation du numéro de téléphone (domaine pur, ADR-0008).

La colonne `users.phone` est **unique** (`uq_users_phone`). Sans forme canonique,
`0700000000` et `+2250700000000` créeraient deux comptes distincts et
**contourneraient** le refus de doublon : la normalisation est donc une exigence
de **sécurité**, pas seulement de confort (PRD §11.1, spec §Security).

Plan de numérotation par défaut : **Côte d'Ivoire (`+225`)**, marché prioritaire
(README). Un numéro national (sans `+`) est préfixé de l'indicatif pays *tel
quel* (sans retirer un éventuel `0` de tête), de sorte que `0700000000` et
`+2250700000000` produisent **la même** forme canonique E.164. Les numéros déjà
internationaux (`+…` ou `00…`) sont conservés.

Ce module n'a **aucune** dépendance framework/I/O (seulement la stdlib).
"""

from __future__ import annotations

import re

from coiflink_api.domain.errors import InvalidPhone

# Indicatif pays par défaut pour un numéro national (Côte d'Ivoire).
DEFAULT_COUNTRY_CODE = "225"

# Bornes E.164 : un numéro comporte au plus 15 chiffres (indicatif inclus) ; on
# fixe un plancher prudent pour rejeter les saisies manifestement incomplètes.
_MIN_DIGITS = 8
_MAX_DIGITS = 15

# Séparateurs de présentation tolérés en entrée (espaces, points, tirets,
# parenthèses) — retirés avant analyse.
_SEPARATORS = re.compile(r"[\s.\-()]")


def normalize_phone(raw: str, *, country_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Retourne la forme canonique **E.164** (`+` suivi de 8 à 15 chiffres).

    Lève `InvalidPhone` si l'entrée est vide, contient des caractères non
    numériques ou tombe hors des bornes E.164. La sortie est déterministe et
    **idempotente** : `normalize_phone(normalize_phone(x)) == x`.
    """

    if not isinstance(raw, str):
        raise InvalidPhone("Le numéro de téléphone est requis.")

    cleaned = _SEPARATORS.sub("", raw.strip())
    if not cleaned:
        raise InvalidPhone("Le numéro de téléphone est requis.")

    # Préfixe international composé « 00 » → « + » (équivalents E.164).
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    if cleaned.startswith("+"):
        digits = cleaned[1:]
    else:
        # Numéro national : on préfixe l'indicatif pays sans altérer les chiffres
        # saisis (un éventuel « 0 » de tête est conservé — cf. docstring module).
        digits = country_code + cleaned

    if not digits.isdigit():
        raise InvalidPhone(
            "Le numéro de téléphone contient des caractères non autorisés."
        )
    if not (_MIN_DIGITS <= len(digits) <= _MAX_DIGITS):
        raise InvalidPhone("La longueur du numéro de téléphone est invalide.")

    return "+" + digits


__all__ = ["normalize_phone", "DEFAULT_COUNTRY_CODE"]
