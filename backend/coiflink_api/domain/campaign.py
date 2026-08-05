"""Domaine pur des **campagnes/messages aux clients** (US-7.5, #49).

Le domaine définit *ce qu'est* une campagne à créer, *comment se valident* son
type, son segment, son titre et son corps, et *comment un segment se traduit* en
prédicat salon-scopé sur les fiches clients (#28) — sans rien savoir de la
persistance (table `campaigns`) ni de l'acheminement réel (SMS via file Redis,
différé M5+). L'écriture est un port
(`application/ports/campaign_repository.py`) ; l'implémentation vit dans
`adapters/outbound/persistence/campaign_repository.py`. Gabarits directs :
`domain/customer.py` (validations, `CustomerFilter`) et `domain/notification.py`
(`NotificationToCreate` `frozen`, `build_*`).

Différence **structurante** avec #45–#48 : une campagne porte un **texte libre
composé par le gérant** (titre + corps), pas un libellé templaté fixe. Le titre
et le corps sont donc **validés** (non vides, bornés) avant toute écriture, mais
restent du **contenu métier** — jamais une PII client (le message est diffusé à
l'identique à tout le segment, le système n'y injecte aucune donnée d'un client
précis).

Invariant de non-fuite (PRD §11.3/§11.4, ADR-0006) : une `CampaignToCreate` est
**neutre** vis-à-vis des destinataires — elle ne porte **jamais** de téléphone,
de nom ni d'identité de destinataire, seulement un **effectif** (entier). Le
worker de remise (futur) résoudra `segment → customer_profiles.phone` **à
l'envoi** — les numéros ne sont **jamais** copiés dans la campagne. Les messages
d'erreur restent neutres (ils ne reprennent jamais le titre ni le corps soumis).

Aucune de ces règles ne connaît HTTP : l'adapter entrant traduit les erreurs de
domaine en `422` (cf. `adapters/inbound/campaigns.py`).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domain.customer import CustomerFilter, validate_customer_filter
from coiflink_api.domain.enums import (
    CampaignSegment,
    CampaignStatus,
    CampaignType,
    values,
)
from coiflink_api.domain.errors import (
    InvalidCampaignMessage,
    InvalidCampaignSegment,
    InvalidCampaignTitle,
    InvalidCampaignType,
)

# Borne du titre, alignée sur la colonne `String(255)` de `campaigns`.
CAMPAIGN_TITLE_MAX_LENGTH = 255

# Borne du corps du message. La colonne est `TEXT` (non bornée) : cette borne est
# **applicative**, pour ne pas accepter un corps de requête non borné (§12.1).
CAMPAIGN_MESSAGE_MAX_LENGTH = 1000

# Valeurs autorisées, dérivées des énumérations du domaine (source de vérité
# partagée avec les contraintes `CHECK` du schéma `campaigns`).
CAMPAIGN_TYPE_VALUES: tuple[str, ...] = values(CampaignType)
CAMPAIGN_SEGMENT_VALUES: tuple[str, ...] = values(CampaignSegment)


def validate_campaign_title(title: str) -> str:
    """Valide et normalise (trim) le titre de la campagne ; lève `InvalidCampaignTitle`.

    Règles : chaîne non vide après `strip()`, longueur ≤ `CAMPAIGN_TITLE_MAX_LENGTH`.
    Le message d'erreur ne reprend jamais le titre soumis.
    """

    if not isinstance(title, str):
        raise InvalidCampaignTitle("Le titre de la campagne est requis.")
    cleaned = title.strip()
    if not cleaned:
        raise InvalidCampaignTitle("Le titre de la campagne est requis.")
    if len(cleaned) > CAMPAIGN_TITLE_MAX_LENGTH:
        raise InvalidCampaignTitle(
            f"Le titre de la campagne ne doit pas dépasser "
            f"{CAMPAIGN_TITLE_MAX_LENGTH} caractères."
        )
    return cleaned


def validate_campaign_message(message: str) -> str:
    """Valide et normalise (trim) le corps du message ; lève `InvalidCampaignMessage`.

    Règles : chaîne non vide après `strip()`, longueur ≤ `CAMPAIGN_MESSAGE_MAX_LENGTH`.
    Le message d'erreur ne reprend jamais le corps soumis.
    """

    if not isinstance(message, str):
        raise InvalidCampaignMessage("Le message de la campagne est requis.")
    cleaned = message.strip()
    if not cleaned:
        raise InvalidCampaignMessage("Le message de la campagne est requis.")
    if len(cleaned) > CAMPAIGN_MESSAGE_MAX_LENGTH:
        raise InvalidCampaignMessage(
            f"Le message de la campagne ne doit pas dépasser "
            f"{CAMPAIGN_MESSAGE_MAX_LENGTH} caractères."
        )
    return cleaned


def normalize_campaign_type(value: str) -> str:
    """Normalise le type de campagne : valeur **exacte** de `CampaignType`.

    La comparaison porte sur la valeur exacte de l'énumération : rien n'est deviné
    ni corrigé (ni casse, ni synonyme) — une valeur inconnue lève
    `InvalidCampaignType`.
    """

    if not isinstance(value, str):
        raise InvalidCampaignType("Le type de campagne est invalide.")
    cleaned = value.strip()
    if cleaned not in CAMPAIGN_TYPE_VALUES:
        raise InvalidCampaignType("Le type de campagne est invalide.")
    return cleaned


def normalize_campaign_segment(value: str) -> str:
    """Normalise le segment ciblé : valeur **exacte** de `CampaignSegment`.

    Comme le type, la comparaison est stricte (valeur fermée) — une valeur inconnue
    lève `InvalidCampaignSegment`. Le segment est un prédicat **salon-scopé** sur
    les fiches (#28) ; sa traduction en `CustomerFilter` est
    `segment_to_customer_filter`.
    """

    if not isinstance(value, str):
        raise InvalidCampaignSegment("Le segment de la campagne est invalide.")
    cleaned = value.strip()
    if cleaned not in CAMPAIGN_SEGMENT_VALUES:
        raise InvalidCampaignSegment("Le segment de la campagne est invalide.")
    return cleaned


def segment_to_customer_filter(segment: str) -> CustomerFilter:
    """Traduit un segment (valeur de `CampaignSegment`) en `CustomerFilter` salon-scopé.

    - `ALL` → toutes les fiches **joignables** du salon ;
    - `FEMALE`/`MALE`/`OTHER` → fiches joignables du **genre** donné (réutilise la
      brique #28/#35).

    Toutes les traductions imposent la **joignabilité SMS** (`has_phone=True`) : le
    canal effectif au MVP est le SMS (`customer_profiles.phone`), et une fiche sans
    téléphone ne peut recevoir de campagne — l'effectif ne compte donc que les
    destinataires réellement joignables (Goal §Canal, Risks §4).

    Le `CustomerFilter` retourné est produit par `validate_customer_filter`, seul
    constructeur sanctionné — il est donc toujours cohérent. Le `salon_id` n'entre
    **pas** dans le filtre : il est appliqué séparément par le dépôt
    (`count_for_salon(salon_id, filter=...)`), toujours issu de la portée validée
    (§11.2). Un segment inconnu lève `InvalidCampaignSegment` (défense en
    profondeur — `normalize_campaign_segment` l'a déjà rejeté en amont).
    """

    if segment == CampaignSegment.ALL.value:
        return validate_customer_filter(has_phone=True)
    if segment in (
        CampaignSegment.FEMALE.value,
        CampaignSegment.MALE.value,
        CampaignSegment.OTHER.value,
    ):
        return validate_customer_filter(gender=segment, has_phone=True)
    raise InvalidCampaignSegment("Le segment de la campagne est invalide.")


@dataclass(frozen=True)
class CampaignToCreate:
    """Champs à insérer dans `campaigns` — pur, neutre (sans PII de destinataire).

    Miroir des colonnes du modèle ORM `models.Campaign`. `salon_id` et
    `created_by` sont **imposés par le serveur** (portée validée + principal),
    jamais lus du corps de requête. `status` vaut `PENDING` par défaut : on
    **émet** (persiste/trace) la campagne sans l'**acheminer** — le worker M5+
    passera `SENT`/`FAILED` à la remise réelle (ADR-0006). `recipient_count` est un
    **effectif** (entier) snapshot du segment à la création : la liste des
    destinataires (téléphones) n'est **jamais** matérialisée ici.
    """

    salon_id: uuid.UUID
    created_by: uuid.UUID
    type: str
    segment: str
    channel: str
    title: str
    message: str
    recipient_count: int
    status: str = CampaignStatus.PENDING.value


@dataclass(frozen=True)
class Campaign:
    """Campagne persistée, rattachée à un salon (US-7.5, #49).

    `sent_at` reste `None` au MVP (non remise, ADR-0006). Aucune identité de
    destinataire n'est portée par l'entité : la campagne stocke un **effectif**
    (`recipient_count`), pas la liste des fiches ciblées.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    created_by: uuid.UUID
    type: str
    segment: str
    channel: str
    title: str
    message: str
    recipient_count: int
    status: str
    sent_at: datetime.datetime | None
    created_at: datetime.datetime


def build_campaign(
    *,
    salon_id: uuid.UUID,
    created_by: uuid.UUID,
    type: str,
    segment: str,
    channel: str,
    title: str,
    message: str,
    recipient_count: int,
) -> CampaignToCreate:
    """Assemble une `CampaignToCreate` **validée** (`status = PENDING`).

    Gabarit de `build_confirmation_notification` (#45), mais **avec texte libre
    validé** — c'est la différence structurante. Valide (et normalise) le type, le
    segment, le titre et le corps **avant** de construire l'objet : un champ
    invalide lève (aucune campagne n'est assemblée). `channel` et `recipient_count`
    sont fournis par l'appelant (résolus dans le cas d'usage) ; `status` reste
    `PENDING` (non remis). L'objet n'accepte **aucune** donnée de destinataire.
    """

    return CampaignToCreate(
        salon_id=salon_id,
        created_by=created_by,
        type=normalize_campaign_type(type),
        segment=normalize_campaign_segment(segment),
        channel=channel,
        title=validate_campaign_title(title),
        message=validate_campaign_message(message),
        recipient_count=recipient_count,
    )


__all__ = [
    "CAMPAIGN_TITLE_MAX_LENGTH",
    "CAMPAIGN_MESSAGE_MAX_LENGTH",
    "CAMPAIGN_TYPE_VALUES",
    "CAMPAIGN_SEGMENT_VALUES",
    "validate_campaign_title",
    "validate_campaign_message",
    "normalize_campaign_type",
    "normalize_campaign_segment",
    "segment_to_customer_filter",
    "CampaignToCreate",
    "Campaign",
    "build_campaign",
]
