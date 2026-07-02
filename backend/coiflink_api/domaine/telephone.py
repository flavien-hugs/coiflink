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

from coiflink_api.domaine.erreurs import TelephoneInvalide

# Indicatif pays par défaut pour un numéro national (Côte d'Ivoire).
INDICATIF_DEFAUT = "225"

# Bornes E.164 : un numéro comporte au plus 15 chiffres (indicatif inclus) ; on
# fixe un plancher prudent pour rejeter les saisies manifestement incomplètes.
_MIN_CHIFFRES = 8
_MAX_CHIFFRES = 15

# Séparateurs de présentation tolérés en entrée (espaces, points, tirets,
# parenthèses) — retirés avant analyse.
_SEPARATEURS = re.compile(r"[\s.\-()]")


def normaliser_telephone(brut: str, *, indicatif_defaut: str = INDICATIF_DEFAUT) -> str:
    """Retourne la forme canonique **E.164** (`+` suivi de 8 à 15 chiffres).

    Lève `TelephoneInvalide` si l'entrée est vide, contient des caractères non
    numériques ou tombe hors des bornes E.164. La sortie est déterministe et
    **idempotente** : `normaliser_telephone(normaliser_telephone(x)) == x`.
    """

    if not isinstance(brut, str):
        raise TelephoneInvalide("Le numéro de téléphone est requis.")

    nettoye = _SEPARATEURS.sub("", brut.strip())
    if not nettoye:
        raise TelephoneInvalide("Le numéro de téléphone est requis.")

    # Préfixe international composé « 00 » → « + » (équivalents E.164).
    if nettoye.startswith("00"):
        nettoye = "+" + nettoye[2:]

    if nettoye.startswith("+"):
        chiffres = nettoye[1:]
    else:
        # Numéro national : on préfixe l'indicatif pays sans altérer les chiffres
        # saisis (un éventuel « 0 » de tête est conservé — cf. docstring module).
        chiffres = indicatif_defaut + nettoye

    if not chiffres.isdigit():
        raise TelephoneInvalide(
            "Le numéro de téléphone contient des caractères non autorisés."
        )
    if not (_MIN_CHIFFRES <= len(chiffres) <= _MAX_CHIFFRES):
        raise TelephoneInvalide("La longueur du numéro de téléphone est invalide.")

    return "+" + chiffres


__all__ = ["normaliser_telephone", "INDICATIF_DEFAUT"]
