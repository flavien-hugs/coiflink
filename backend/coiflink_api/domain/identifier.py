"""Classement d'un **identifiant de connexion** : e-mail ou téléphone (ADR-0008).

À la connexion (#10), un utilisateur fournit un **unique** identifiant qui est
soit son e-mail, soit son numéro de téléphone. Ce module (domaine pur, sans
dépendance framework/I/O) tranche entre les deux et **normalise** la valeur pour
qu'elle vise le **même** compte que celui créé à l'inscription (#8/#9) :

- présence d'un `@` → **e-mail** (on se contente de `strip` ; la casse n'est
  **pas** modifiée pour rester cohérent avec le stockage de l'inscription, qui ne
  met pas l'e-mail en minuscules — cf. ADR-0013, normalisation insensible à la
  casse différée) ;
- sinon → **téléphone**, normalisé en E.164 via `normalize_phone` (garantit que
  `0700…` et `+2250700…` visent le même compte, comme à l'inscription).

`classify_identifier` suppose une entrée **déjà** débarrassée de ses espaces de
bord (`strip`) et **non vide** : l'appelant (le cas d'usage) filtre ces cas en
amont pour ne jamais divulguer *pourquoi* un identifiant est refusé (anti-énumération).
"""

from __future__ import annotations

from dataclasses import dataclass

from coiflink_api.domain.phone import normalize_phone

EMAIL = "email"
PHONE = "phone"


@dataclass(frozen=True)
class LoginIdentifier:
    """Identifiant de connexion classé et normalisé.

    `kind` vaut `"email"` ou `"phone"` ; `value` est la forme normalisée servant
    à la recherche du compte (e-mail `strip`é ou téléphone E.164).
    """

    kind: str
    value: str


def classify_identifier(raw: str) -> LoginIdentifier:
    """Classe un identifiant **non vide** en e-mail ou téléphone (normalisé).

    Lève `domain.errors.InvalidPhone` si l'entrée, prise pour un téléphone (pas
    de `@`), n'est pas un numéro exploitable. Ne valide pas le **format** de
    l'e-mail : un e-mail introuvable est traité comme identifiant invalide par le
    cas d'usage (même réponse générique), sans énumération de comptes.
    """

    cleaned = raw.strip()
    if "@" in cleaned:
        return LoginIdentifier(EMAIL, cleaned)
    return LoginIdentifier(PHONE, normalize_phone(cleaned))


__all__ = ["LoginIdentifier", "classify_identifier", "EMAIL", "PHONE"]
