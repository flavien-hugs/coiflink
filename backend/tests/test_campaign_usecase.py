"""Tests unitaires — cas d'usage `CreateCampaign` / `ListSalonCampaigns` (US-7.5, #49).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base, pas de réseau.
Couvre :
- `CreateCampaign` :
  - `salon_id` imposé par l'argument de portée, jamais par la commande ;
  - `created_by = actor_user_id` (jamais du corps) ;
  - `recipient_count` résolu via `count_for_salon` salon-scopé + filtre segment SMS ;
  - fiches sans téléphone exclues de l'effectif (joignabilité SMS, Risks §4) ;
  - campagne `status = PENDING`, canal SMS ;
  - audit `CAMPAIGN_CREATED` : action, acteur, salon, `entity_type`, `entity_id` corrects,
    `metadata` **non-PII** (type + segment + effectif — **jamais** le corps du message,
    **jamais** un numéro) ;
  - validation échouée (type/segment/titre/message invalides) → 0 campagne, 0 audit
    (exception levée avant toute écriture) ;
- `ListSalonCampaigns` : page + total salon-scopés, limit/offset.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.application.campaigns import (
    CampaignCommand,
    CreateCampaign,
    ListSalonCampaigns,
)
from coiflink_api.domain.audit import ENTITY_TYPE_CAMPAIGN, AuditAction
from coiflink_api.domain.campaign import CampaignToCreate
from coiflink_api.domain.customer import CustomerToCreate
from coiflink_api.domain.enums import CampaignStatus, NotificationChannel
from coiflink_api.domain.errors import (
    InvalidCampaignMessage,
    InvalidCampaignSegment,
    InvalidCampaignTitle,
    InvalidCampaignType,
)

from .conftest import FakeAuditLog, FakeCampaignRepository, FakeCustomerRepository

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ACTOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

_VALID_COMMAND = CampaignCommand(
    type="REMINDER",
    segment="ALL",
    title="Rappel de rendez-vous",
    message="Bonjour, n'oubliez pas votre rendez-vous.",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_customer_repo_with_phones(salon_id: uuid.UUID, count: int) -> FakeCustomerRepository:
    """Pré-charge `count` fiches **avec téléphone** dans `salon_id`."""
    repo = FakeCustomerRepository()
    for i in range(count):
        repo.create(CustomerToCreate(
            salon_id=salon_id,
            full_name=f"Client {i}",
            phone=f"+2250700{i:06d}",
            gender=None,
            notes=None,
        ))
    return repo


def _make_campaign_repo_with(salon_id: uuid.UUID, count: int) -> FakeCampaignRepository:
    repo = FakeCampaignRepository()
    for i in range(count):
        repo.create(CampaignToCreate(
            salon_id=salon_id,
            created_by=_ACTOR_ID,
            type="REMINDER",
            segment="ALL",
            channel="SMS",
            title=f"Campagne {i}",
            message="Corps.",
            recipient_count=i,
            status=CampaignStatus.PENDING.value,
        ))
    return repo


# ---------------------------------------------------------------------------
# CreateCampaign — résultat
# ---------------------------------------------------------------------------


class TestCreateCampaignResult:
    def test_campaign_salon_id_from_scope(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=2)
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.salon_id == _SALON_ID

    def test_created_by_is_actor_user_id(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.created_by == _ACTOR_ID

    def test_status_is_pending(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.status == CampaignStatus.PENDING.value

    def test_channel_is_sms(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.channel == NotificationChannel.SMS.value

    def test_recipient_count_matches_count_for_salon(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=4)
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.recipient_count == 4

    def test_command_has_no_salon_id_field(self) -> None:
        """Anti-élévation : la commande ne déclare pas de champ `salon_id`."""
        assert not hasattr(_VALID_COMMAND, "salon_id")

    def test_command_has_no_created_by_field(self) -> None:
        """Anti-élévation : la commande ne déclare pas de champ `created_by`."""
        assert not hasattr(_VALID_COMMAND, "created_by")


# ---------------------------------------------------------------------------
# CreateCampaign — isolation salon et segment
# ---------------------------------------------------------------------------


class TestCreateCampaignSalonScope:
    def test_recipient_count_is_salon_scoped(self) -> None:
        """L'effectif ne compte que les fiches du salon de la portée, pas des autres."""
        repo = FakeCampaignRepository()
        customers = FakeCustomerRepository()
        for i in range(3):
            customers.create(CustomerToCreate(
                salon_id=_SALON_ID, full_name=f"A{i}", phone=f"+2250700000{i:03d}",
                gender=None, notes=None,
            ))
        for i in range(2):
            customers.create(CustomerToCreate(
                salon_id=_OTHER_SALON_ID, full_name=f"B{i}", phone=f"+2250700001{i:03d}",
                gender=None, notes=None,
            ))
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.recipient_count == 3

    def test_customers_without_phone_excluded_from_count(self) -> None:
        """Joignabilité SMS (Risks §4) : fiches sans téléphone exclues de l'effectif."""
        repo = FakeCampaignRepository()
        customers = FakeCustomerRepository()
        customers.create(CustomerToCreate(
            salon_id=_SALON_ID, full_name="Avec 1", phone="+2250700000001",
            gender=None, notes=None,
        ))
        customers.create(CustomerToCreate(
            salon_id=_SALON_ID, full_name="Avec 2", phone="+2250700000002",
            gender=None, notes=None,
        ))
        customers.create(CustomerToCreate(
            salon_id=_SALON_ID, full_name="Sans téléphone", phone=None,
            gender=None, notes=None,
        ))
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.recipient_count == 2

    def test_gender_segment_filters_correctly(self) -> None:
        """Segment FEMALE : seules les fiches FEMALE joignables sont comptées."""
        repo = FakeCampaignRepository()
        customers = FakeCustomerRepository()
        for i in range(2):
            customers.create(CustomerToCreate(
                salon_id=_SALON_ID, full_name=f"F{i}", phone=f"+2250700000{i:03d}",
                gender="FEMALE", notes=None,
            ))
        customers.create(CustomerToCreate(
            salon_id=_SALON_ID, full_name="M1", phone="+2250700000099",
            gender="MALE", notes=None,
        ))
        audit = FakeAuditLog()
        cmd = CampaignCommand(type="PROMOTION", segment="FEMALE", title="Promo femmes", message="Offre.")
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, cmd, actor_user_id=_ACTOR_ID
        )
        assert campaign.recipient_count == 2
        assert campaign.segment == "FEMALE"

    def test_zero_recipient_count_accepted(self) -> None:
        """Un salon sans fiche joignable peut émettre une campagne (effectif 0 valide)."""
        repo = FakeCampaignRepository()
        customers = FakeCustomerRepository()
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert campaign.recipient_count == 0
        assert campaign.status == CampaignStatus.PENDING.value


# ---------------------------------------------------------------------------
# CreateCampaign — persistance
# ---------------------------------------------------------------------------


class TestCreateCampaignPersistence:
    def test_exactly_one_campaign_persisted(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert len(repo.created) == 1

    def test_persisted_campaign_has_pending_status(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert repo.created[0].status == CampaignStatus.PENDING.value

    def test_persisted_campaign_has_correct_salon_id(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert repo.created[0].salon_id == _SALON_ID

    def test_persisted_campaign_has_correct_created_by(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert repo.created[0].created_by == _ACTOR_ID


# ---------------------------------------------------------------------------
# CreateCampaign — audit
# ---------------------------------------------------------------------------


class TestCreateCampaignAudit:
    def test_exactly_one_audit_entry_recorded(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert len(audit.recorded) == 1

    def test_audit_action_is_campaign_created(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert audit.recorded[0].action == AuditAction.CAMPAIGN_CREATED.value

    def test_audit_actor_is_actor_user_id(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert audit.recorded[0].actor_user_id == _ACTOR_ID

    def test_audit_salon_id_is_scope_salon(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert audit.recorded[0].salon_id == _SALON_ID

    def test_audit_entity_type_is_campaign(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert audit.recorded[0].entity_type == ENTITY_TYPE_CAMPAIGN

    def test_audit_entity_id_matches_campaign_id(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        campaign = CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert audit.recorded[0].entity_id == campaign.id

    def test_audit_metadata_contains_type(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert audit.recorded[0].metadata.get("type") == "REMINDER"

    def test_audit_metadata_contains_segment(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert "segment" in audit.recorded[0].metadata

    def test_audit_metadata_contains_recipient_count(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=3)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert audit.recorded[0].metadata.get("recipient_count") == 3

    def test_audit_metadata_does_not_contain_message(self) -> None:
        """Non-fuite §11.3 : le corps du message n'entre jamais au journal d'audit."""
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        meta = audit.recorded[0].metadata
        assert "message" not in meta
        assert _VALID_COMMAND.message not in str(meta)

    def test_audit_metadata_does_not_contain_phone(self) -> None:
        """Non-fuite §11.3 : aucun numéro de téléphone n'entre au journal d'audit."""
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=2)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        meta = audit.recorded[0].metadata
        assert "phone" not in meta
        assert "+225" not in str(meta)

    def test_audit_metadata_does_not_contain_title(self) -> None:
        """Non-fuite §11.3 : le titre composé n'entre pas dans les metadata d'audit."""
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        CreateCampaign(repo, customers, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        meta = audit.recorded[0].metadata
        assert "title" not in meta
        assert _VALID_COMMAND.title not in str(meta)


# ---------------------------------------------------------------------------
# CreateCampaign — validation échouée (atomicité)
# ---------------------------------------------------------------------------


class TestCreateCampaignValidationFailure:
    def test_invalid_type_no_campaign_no_audit(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        cmd = CampaignCommand(type="BOGUS", segment="ALL", title="X", message="Y")
        with pytest.raises(InvalidCampaignType):
            CreateCampaign(repo, customers, audit).execute(
                _SALON_ID, cmd, actor_user_id=_ACTOR_ID
            )
        assert len(repo.created) == 0
        assert len(audit.recorded) == 0

    def test_invalid_segment_no_campaign_no_audit(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        cmd = CampaignCommand(type="REMINDER", segment="UNKNOWN", title="X", message="Y")
        with pytest.raises(InvalidCampaignSegment):
            CreateCampaign(repo, customers, audit).execute(
                _SALON_ID, cmd, actor_user_id=_ACTOR_ID
            )
        assert len(repo.created) == 0
        assert len(audit.recorded) == 0

    def test_empty_title_no_campaign_no_audit(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        cmd = CampaignCommand(type="REMINDER", segment="ALL", title="", message="Corps valide.")
        with pytest.raises(InvalidCampaignTitle):
            CreateCampaign(repo, customers, audit).execute(
                _SALON_ID, cmd, actor_user_id=_ACTOR_ID
            )
        assert len(repo.created) == 0
        assert len(audit.recorded) == 0

    def test_empty_message_no_campaign_no_audit(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        cmd = CampaignCommand(type="REMINDER", segment="ALL", title="Titre valide", message="")
        with pytest.raises(InvalidCampaignMessage):
            CreateCampaign(repo, customers, audit).execute(
                _SALON_ID, cmd, actor_user_id=_ACTOR_ID
            )
        assert len(repo.created) == 0
        assert len(audit.recorded) == 0

    def test_whitespace_only_title_no_campaign_no_audit(self) -> None:
        repo = FakeCampaignRepository()
        customers = _make_customer_repo_with_phones(_SALON_ID, count=1)
        audit = FakeAuditLog()
        cmd = CampaignCommand(type="REMINDER", segment="ALL", title="   ", message="Corps valide.")
        with pytest.raises(InvalidCampaignTitle):
            CreateCampaign(repo, customers, audit).execute(
                _SALON_ID, cmd, actor_user_id=_ACTOR_ID
            )
        assert len(repo.created) == 0
        assert len(audit.recorded) == 0


# ---------------------------------------------------------------------------
# ListSalonCampaigns
# ---------------------------------------------------------------------------


class TestListSalonCampaigns:
    def test_returns_page_and_total(self) -> None:
        repo = _make_campaign_repo_with(_SALON_ID, 5)
        page, total = ListSalonCampaigns(repo).execute(_SALON_ID, limit=10, offset=0)
        assert len(page) == 5
        assert total == 5

    def test_limit_applied(self) -> None:
        repo = _make_campaign_repo_with(_SALON_ID, 5)
        page, _ = ListSalonCampaigns(repo).execute(_SALON_ID, limit=2, offset=0)
        assert len(page) == 2

    def test_offset_applied(self) -> None:
        repo = _make_campaign_repo_with(_SALON_ID, 5)
        page, _ = ListSalonCampaigns(repo).execute(_SALON_ID, limit=10, offset=4)
        assert len(page) == 1

    def test_empty_salon_returns_empty_page(self) -> None:
        repo = FakeCampaignRepository()
        page, total = ListSalonCampaigns(repo).execute(_SALON_ID, limit=10, offset=0)
        assert len(page) == 0
        assert total == 0

    def test_salon_scoped_only(self) -> None:
        """La liste ne renvoie que les campagnes du salon de la portée."""
        repo = _make_campaign_repo_with(_SALON_ID, 3)
        # Campagnes dans un autre salon (ajoutées dans le même repo fake).
        for i in range(2):
            repo.create(CampaignToCreate(
                salon_id=_OTHER_SALON_ID,
                created_by=_ACTOR_ID,
                type="PROMOTION",
                segment="ALL",
                channel="SMS",
                title=f"Autre salon {i}",
                message="Corps.",
                recipient_count=0,
                status=CampaignStatus.PENDING.value,
            ))
        page, total = ListSalonCampaigns(repo).execute(_SALON_ID, limit=10, offset=0)
        assert all(c.salon_id == _SALON_ID for c in page)
        assert total == 3
