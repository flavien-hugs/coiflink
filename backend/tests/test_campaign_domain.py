"""Tests unitaires — domaine `campaign` (US-7.5, #49).

Couvre les règles de validation pures :
- `validate_campaign_title` : trim, vide, trop long, non-chaîne ;
- `validate_campaign_message` : trim, vide, trop long, non-chaîne ;
- `normalize_campaign_type` : valeurs valides, invalide, non-chaîne ;
- `normalize_campaign_segment` : valeurs valides, invalide, non-chaîne ;
- `segment_to_customer_filter` : mappage segment → `CustomerFilter` (joignabilité SMS,
  genre) ;
- `build_campaign` : assemblage, `status = PENDING`, aucun champ destinataire ;
- Messages d'erreur neutres (ne reprennent jamais le corps soumis).

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from coiflink_api.domain.campaign import (
    CAMPAIGN_MESSAGE_MAX_LENGTH,
    CAMPAIGN_TITLE_MAX_LENGTH,
    CampaignToCreate,
    build_campaign,
    normalize_campaign_segment,
    normalize_campaign_type,
    segment_to_customer_filter,
    validate_campaign_message,
    validate_campaign_title,
)
from coiflink_api.domain.enums import CampaignSegment, CampaignStatus, CampaignType
from coiflink_api.domain.errors import (
    InvalidCampaignMessage,
    InvalidCampaignSegment,
    InvalidCampaignTitle,
    InvalidCampaignType,
)

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_ACTOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# validate_campaign_title
# ---------------------------------------------------------------------------


class TestValidateCampaignTitle:
    def test_valid_title_returned(self) -> None:
        assert validate_campaign_title("Promotion de la rentrée") == "Promotion de la rentrée"

    def test_leading_trailing_whitespace_trimmed(self) -> None:
        assert validate_campaign_title("  Promo  ") == "Promo"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidCampaignTitle):
            validate_campaign_title("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidCampaignTitle):
            validate_campaign_title("   ")

    def test_non_string_int_raises(self) -> None:
        with pytest.raises(InvalidCampaignTitle):
            validate_campaign_title(42)  # type: ignore[arg-type]

    def test_non_string_none_raises(self) -> None:
        with pytest.raises(InvalidCampaignTitle):
            validate_campaign_title(None)  # type: ignore[arg-type]

    def test_title_at_max_length_accepted(self) -> None:
        title = "A" * CAMPAIGN_TITLE_MAX_LENGTH
        assert validate_campaign_title(title) == title

    def test_title_over_max_length_raises(self) -> None:
        with pytest.raises(InvalidCampaignTitle):
            validate_campaign_title("A" * (CAMPAIGN_TITLE_MAX_LENGTH + 1))

    def test_trimmed_title_at_max_length_accepted(self) -> None:
        padded = " " + "A" * CAMPAIGN_TITLE_MAX_LENGTH + " "
        assert validate_campaign_title(padded) == "A" * CAMPAIGN_TITLE_MAX_LENGTH

    def test_single_character_accepted(self) -> None:
        assert validate_campaign_title("X") == "X"

    def test_error_message_does_not_contain_title(self) -> None:
        """Non-fuite §11.3 : le titre soumis n'apparaît jamais dans le message d'erreur."""
        secret_title = "MON_TITRE_SECRET_UNIQUE_XYZ"
        try:
            validate_campaign_title(secret_title * 1000)
        except InvalidCampaignTitle as exc:
            assert secret_title not in str(exc)


# ---------------------------------------------------------------------------
# validate_campaign_message
# ---------------------------------------------------------------------------


class TestValidateCampaignMessage:
    def test_valid_message_returned(self) -> None:
        assert validate_campaign_message("Venez profiter de nos offres.") == "Venez profiter de nos offres."

    def test_leading_trailing_whitespace_trimmed(self) -> None:
        assert validate_campaign_message("  Corps  ") == "Corps"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidCampaignMessage):
            validate_campaign_message("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidCampaignMessage):
            validate_campaign_message("   ")

    def test_non_string_int_raises(self) -> None:
        with pytest.raises(InvalidCampaignMessage):
            validate_campaign_message(42)  # type: ignore[arg-type]

    def test_non_string_none_raises(self) -> None:
        with pytest.raises(InvalidCampaignMessage):
            validate_campaign_message(None)  # type: ignore[arg-type]

    def test_message_at_max_length_accepted(self) -> None:
        msg = "A" * CAMPAIGN_MESSAGE_MAX_LENGTH
        assert validate_campaign_message(msg) == msg

    def test_message_over_max_length_raises(self) -> None:
        with pytest.raises(InvalidCampaignMessage):
            validate_campaign_message("A" * (CAMPAIGN_MESSAGE_MAX_LENGTH + 1))

    def test_error_message_does_not_contain_body(self) -> None:
        """Non-fuite §11.3 : le corps soumis n'apparaît jamais dans le message d'erreur."""
        secret_body = "MON_CORPS_SECRET_UNIQUE_99999"
        try:
            validate_campaign_message(secret_body * 2000)
        except InvalidCampaignMessage as exc:
            assert secret_body not in str(exc)


# ---------------------------------------------------------------------------
# normalize_campaign_type
# ---------------------------------------------------------------------------


class TestNormalizeCampaignType:
    def test_reminder_accepted(self) -> None:
        assert normalize_campaign_type("REMINDER") == "REMINDER"

    def test_promotion_accepted(self) -> None:
        assert normalize_campaign_type("PROMOTION") == "PROMOTION"

    def test_exceptional_closure_accepted(self) -> None:
        assert normalize_campaign_type("EXCEPTIONAL_CLOSURE") == "EXCEPTIONAL_CLOSURE"

    def test_all_enum_values_accepted(self) -> None:
        for member in CampaignType:
            assert normalize_campaign_type(member.value) == member.value

    def test_unknown_value_raises(self) -> None:
        with pytest.raises(InvalidCampaignType):
            normalize_campaign_type("UNKNOWN")

    def test_lowercase_value_raises(self) -> None:
        with pytest.raises(InvalidCampaignType):
            normalize_campaign_type("reminder")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidCampaignType):
            normalize_campaign_type("")

    def test_non_string_none_raises(self) -> None:
        with pytest.raises(InvalidCampaignType):
            normalize_campaign_type(None)  # type: ignore[arg-type]

    def test_whitespace_around_valid_value_stripped(self) -> None:
        assert normalize_campaign_type("  REMINDER  ") == "REMINDER"


# ---------------------------------------------------------------------------
# normalize_campaign_segment
# ---------------------------------------------------------------------------


class TestNormalizeCampaignSegment:
    def test_all_accepted(self) -> None:
        assert normalize_campaign_segment("ALL") == "ALL"

    def test_female_accepted(self) -> None:
        assert normalize_campaign_segment("FEMALE") == "FEMALE"

    def test_male_accepted(self) -> None:
        assert normalize_campaign_segment("MALE") == "MALE"

    def test_other_accepted(self) -> None:
        assert normalize_campaign_segment("OTHER") == "OTHER"

    def test_all_enum_values_accepted(self) -> None:
        for member in CampaignSegment:
            assert normalize_campaign_segment(member.value) == member.value

    def test_unknown_value_raises(self) -> None:
        with pytest.raises(InvalidCampaignSegment):
            normalize_campaign_segment("INACTIVE")

    def test_lowercase_value_raises(self) -> None:
        with pytest.raises(InvalidCampaignSegment):
            normalize_campaign_segment("all")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidCampaignSegment):
            normalize_campaign_segment("")

    def test_non_string_none_raises(self) -> None:
        with pytest.raises(InvalidCampaignSegment):
            normalize_campaign_segment(None)  # type: ignore[arg-type]

    def test_whitespace_around_valid_value_stripped(self) -> None:
        assert normalize_campaign_segment("  ALL  ") == "ALL"


# ---------------------------------------------------------------------------
# segment_to_customer_filter
# ---------------------------------------------------------------------------


class TestSegmentToCustomerFilter:
    def test_all_segment_has_phone_true(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.ALL.value)
        assert f.has_phone is True

    def test_all_segment_no_gender_constraint(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.ALL.value)
        assert f.gender is None

    def test_female_segment_gender_is_female(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.FEMALE.value)
        assert f.gender == "FEMALE"

    def test_female_segment_has_phone_true(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.FEMALE.value)
        assert f.has_phone is True

    def test_male_segment_gender_is_male(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.MALE.value)
        assert f.gender == "MALE"

    def test_male_segment_has_phone_true(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.MALE.value)
        assert f.has_phone is True

    def test_other_segment_gender_is_other(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.OTHER.value)
        assert f.gender == "OTHER"

    def test_other_segment_has_phone_true(self) -> None:
        f = segment_to_customer_filter(CampaignSegment.OTHER.value)
        assert f.has_phone is True

    def test_unknown_segment_raises(self) -> None:
        with pytest.raises(InvalidCampaignSegment):
            segment_to_customer_filter("BOGUS")

    def test_filter_has_no_extra_constraints(self) -> None:
        """Le filtre ALL ne pose aucune contrainte de date ni de texte."""
        f = segment_to_customer_filter(CampaignSegment.ALL.value)
        assert f.q is None
        assert f.created_from is None
        assert f.created_to is None


# ---------------------------------------------------------------------------
# build_campaign
# ---------------------------------------------------------------------------


class TestBuildCampaign:
    def _build(self, **overrides: object) -> CampaignToCreate:
        defaults: dict = dict(
            salon_id=_SALON_ID,
            created_by=_ACTOR_ID,
            type="REMINDER",
            segment="ALL",
            channel="SMS",
            title="Rappel de votre RDV",
            message="N'oubliez pas votre rendez-vous de demain.",
            recipient_count=5,
        )
        defaults.update(overrides)
        return build_campaign(**defaults)  # type: ignore[arg-type]

    def test_status_is_pending(self) -> None:
        assert self._build().status == CampaignStatus.PENDING.value

    def test_salon_id_preserved(self) -> None:
        assert self._build().salon_id == _SALON_ID

    def test_created_by_preserved(self) -> None:
        assert self._build().created_by == _ACTOR_ID

    def test_type_normalized(self) -> None:
        assert self._build(type="PROMOTION").type == "PROMOTION"

    def test_segment_normalized(self) -> None:
        assert self._build(segment="FEMALE").segment == "FEMALE"

    def test_title_trimmed_and_preserved(self) -> None:
        assert self._build(title="  Promo  ").title == "Promo"

    def test_message_trimmed_and_preserved(self) -> None:
        assert self._build(message="  Corps.  ").message == "Corps."

    def test_recipient_count_preserved(self) -> None:
        assert self._build(recipient_count=42).recipient_count == 42

    def test_channel_preserved(self) -> None:
        assert self._build(channel="SMS").channel == "SMS"

    def test_no_recipient_phone_field(self) -> None:
        """Non-fuite : `CampaignToCreate` ne porte aucun champ téléphone destinataire."""
        campaign = self._build()
        assert not hasattr(campaign, "phone")
        assert not hasattr(campaign, "recipient_phone")

    def test_no_recipient_id_field(self) -> None:
        """Non-fuite : `CampaignToCreate` ne porte aucun identifiant de destinataire."""
        campaign = self._build()
        assert not hasattr(campaign, "recipient_id")
        assert not hasattr(campaign, "customer_id")

    def test_invalid_type_raises_before_construction(self) -> None:
        with pytest.raises(InvalidCampaignType):
            self._build(type="BOGUS")

    def test_invalid_segment_raises_before_construction(self) -> None:
        with pytest.raises(InvalidCampaignSegment):
            self._build(segment="BOGUS")

    def test_empty_title_raises_before_construction(self) -> None:
        with pytest.raises(InvalidCampaignTitle):
            self._build(title="")

    def test_empty_message_raises_before_construction(self) -> None:
        with pytest.raises(InvalidCampaignMessage):
            self._build(message="")

    def test_title_over_max_length_raises(self) -> None:
        with pytest.raises(InvalidCampaignTitle):
            self._build(title="A" * (CAMPAIGN_TITLE_MAX_LENGTH + 1))

    def test_message_over_max_length_raises(self) -> None:
        with pytest.raises(InvalidCampaignMessage):
            self._build(message="A" * (CAMPAIGN_MESSAGE_MAX_LENGTH + 1))

    def test_frozen_dataclass_immutable(self) -> None:
        """`CampaignToCreate` est `frozen=True` — toute mutation doit lever."""
        campaign = self._build()
        with pytest.raises(dataclasses.FrozenInstanceError):
            campaign.status = "SENT"  # type: ignore[misc]
