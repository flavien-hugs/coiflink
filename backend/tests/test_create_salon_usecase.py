"""Tests unitaires — cas d'usage `CreateSalon` et compagnons (US-2.1, #15).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base, pas de réseau.
Couvre :
- `CreateSalon` : owner_id imposé par l'appelant, jamais lu du corps (anti-élévation) ;
  status=ACTIVE et opening_hours=None garantis à la création ; téléphone normalisé ;
  validation (nom, coordonnées) **avant** toute écriture au dépôt ;
- `_ensure_key_prefix` / `_build_object_key` via les cas d'usage médias :
  clé hors préfixe du salon → `MediaKeyMismatch` ;
- `AddSalonPhoto` : limite `max_photos` → `PhotoLimitExceeded` ;
- `AttachSalonLogo` : revalide le préfixe ; nettoie l'ancien objet (best-effort) ;
- `RemoveSalonPhoto` : suppression best-effort de l'objet du stockage ;
- `IssueMediaUploadUrl` : clé sans PII, content_type invalide → `InvalidMediaType` ;
- `GetSalon` : `SalonNotFound` si absent ; URLs signées résolues ;
  sans stockage (None) → logo_url/photos à None ;
- `ListOwnSalons` : filtre par owner_id.
"""

from __future__ import annotations

import decimal
import uuid

import pytest

from coiflink_api.application.salons import (
    AddSalonPhoto,
    AttachSalonLogo,
    CreateSalon,
    CreateSalonCommand,
    GetSalon,
    IssueMediaUploadUrl,
    ListOwnSalons,
    RemoveSalonPhoto,
    UpdateSalon,
    UpdateSalonCommand,
)
from coiflink_api.domain.audit import AuditAction, AuditEntry
from coiflink_api.domain.enums import SalonStatus
from coiflink_api.domain.errors import (
    InvalidLocation,
    InvalidMediaType,
    InvalidSalonName,
    MediaKeyMismatch,
    PhotoLimitExceeded,
    SalonNotFound,
)

from .conftest import FakeAuditLog, FakeMediaStorage, FakeSalonRepository

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_OWNER_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_OWNER_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")

_VALID_COMMAND = CreateSalonCommand(
    name="Salon Élégance",
    description="Coiffure afro et tresses.",
    phone="0700000000",
    address="Rue des Jardins, Cocody",
    city="Abidjan",
    commune="Cocody",
    latitude=decimal.Decimal("5.359952"),
    longitude=decimal.Decimal("-3.996643"),
)


# ---------------------------------------------------------------------------
# CreateSalon
# ---------------------------------------------------------------------------


class TestCreateSalon:
    def test_salon_created_with_correct_owner(self) -> None:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert salon.owner_id == _OWNER_ID

    def test_salon_created_with_active_status(self) -> None:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert salon.status == SalonStatus.ACTIVE.value

    def test_salon_created_with_null_opening_hours(self) -> None:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert salon.opening_hours is None

    def test_salon_is_not_bookable_at_creation(self) -> None:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert salon.is_bookable is False

    def test_salon_name_stored_trimmed(self) -> None:
        repo = FakeSalonRepository()
        cmd = CreateSalonCommand(name="  Mon Salon  ")
        salon = CreateSalon(repo).execute(cmd, owner_id=_OWNER_ID)
        assert salon.name == "Mon Salon"

    def test_phone_normalized_to_e164(self) -> None:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert salon.phone == "+2250700000000"

    def test_phone_none_tolerated(self) -> None:
        repo = FakeSalonRepository()
        cmd = CreateSalonCommand(name="Salon X", phone=None)
        salon = CreateSalon(repo).execute(cmd, owner_id=_OWNER_ID)
        assert salon.phone is None

    def test_coordinates_stored(self) -> None:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert salon.latitude == decimal.Decimal("5.359952")
        assert salon.longitude == decimal.Decimal("-3.996643")

    def test_command_has_no_owner_id_field(self) -> None:
        """Invariant anti-élévation : la commande ne déclare pas de champ owner_id."""
        assert not hasattr(_VALID_COMMAND, "owner_id")

    def test_different_owner_ids_produce_different_owners(self) -> None:
        repo = FakeSalonRepository()
        s1 = CreateSalon(repo).execute(CreateSalonCommand(name="A"), owner_id=_OWNER_ID)
        s2 = CreateSalon(repo).execute(CreateSalonCommand(name="B"), owner_id=_OTHER_OWNER_ID)
        assert s1.owner_id == _OWNER_ID
        assert s2.owner_id == _OTHER_OWNER_ID

    def test_repository_receives_correct_owner_id(self) -> None:
        repo = FakeSalonRepository()
        CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert len(repo.created) == 1
        assert repo.created[0].owner_id == _OWNER_ID

    def test_repository_not_called_when_name_invalid(self) -> None:
        """Validation précède toute écriture : dépôt non sollicité sur nom vide."""
        repo = FakeSalonRepository()
        with pytest.raises(InvalidSalonName):
            CreateSalon(repo).execute(
                CreateSalonCommand(name=""), owner_id=_OWNER_ID
            )
        assert repo.created == []

    def test_repository_not_called_when_coordinates_invalid(self) -> None:
        repo = FakeSalonRepository()
        with pytest.raises(InvalidLocation):
            CreateSalon(repo).execute(
                CreateSalonCommand(
                    name="Valide",
                    latitude=decimal.Decimal("5"),
                    longitude=None,
                ),
                owner_id=_OWNER_ID,
            )
        assert repo.created == []

    def test_empty_description_stored_as_none(self) -> None:
        repo = FakeSalonRepository()
        cmd = CreateSalonCommand(name="Salon X", description="")
        salon = CreateSalon(repo).execute(cmd, owner_id=_OWNER_ID)
        assert salon.description is None

    def test_salon_has_no_logo_at_creation(self) -> None:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        assert salon.logo_object_key is None


# ---------------------------------------------------------------------------
# UpdateSalon
# ---------------------------------------------------------------------------


class TestUpdateSalon:
    def _create(self, repo: FakeSalonRepository) -> uuid.UUID:
        salon = CreateSalon(repo).execute(_VALID_COMMAND, owner_id=_OWNER_ID)
        return salon.id

    def test_updated_salon_returned(self) -> None:
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        new_cmd = UpdateSalonCommand(name="Nouveau nom", phone="0701020304")
        updated = UpdateSalon(repo, audit).execute(
            salon_id, new_cmd, actor_user_id=_OWNER_ID
        )
        assert updated.name == "Nouveau nom"
        assert updated.phone == "+2250701020304"

    def test_raises_when_salon_not_found(self) -> None:
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        with pytest.raises(SalonNotFound):
            UpdateSalon(repo, audit).execute(
                uuid.uuid4(), UpdateSalonCommand(name="X"), actor_user_id=_OWNER_ID
            )

    def test_repository_not_called_when_name_invalid(self) -> None:
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        with pytest.raises(InvalidSalonName):
            UpdateSalon(repo, audit).execute(
                salon_id, UpdateSalonCommand(name=""), actor_user_id=_OWNER_ID
            )
        assert audit.recorded == []
        unchanged = repo.find_by_id(salon_id)
        assert unchanged is not None
        assert unchanged.name == _VALID_COMMAND.name

    def test_no_repository_call_when_coordinates_invalid(self) -> None:
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        with pytest.raises(InvalidLocation):
            UpdateSalon(repo, audit).execute(
                salon_id,
                UpdateSalonCommand(
                    name="Valide", latitude=decimal.Decimal("5"), longitude=None
                ),
                actor_user_id=_OWNER_ID,
            )
        assert audit.recorded == []

    def test_no_write_when_salon_not_found(self) -> None:
        """La validation précède `find_by_id` : aucune écriture ni audit si absent."""
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        with pytest.raises(SalonNotFound):
            UpdateSalon(repo, audit).execute(
                uuid.uuid4(), UpdateSalonCommand(name="X"), actor_user_id=_OWNER_ID
            )
        assert audit.recorded == []

    def test_audit_entry_recorded_on_update(self) -> None:
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        UpdateSalon(repo, audit).execute(
            salon_id, UpdateSalonCommand(name="Nouveau nom"), actor_user_id=_OWNER_ID
        )
        assert len(audit.recorded) == 1
        entry: AuditEntry = audit.recorded[0]
        assert entry.action == AuditAction.SALON_UPDATED.value

    def test_audit_actor_and_salon_id_correct(self) -> None:
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        UpdateSalon(repo, audit).execute(
            salon_id, UpdateSalonCommand(name="Nouveau nom"), actor_user_id=_OWNER_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.actor_user_id == _OWNER_ID
        assert entry.salon_id == salon_id
        assert entry.entity_id == salon_id

    def test_changed_fields_contains_only_modified_field(self) -> None:
        """Seul `phone` change → `changed == ["phone"]` (ordre de `_DIFF_FIELDS`)."""
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        new_cmd = UpdateSalonCommand(
            name=_VALID_COMMAND.name,
            description=_VALID_COMMAND.description,
            phone="0701020304",
            address=_VALID_COMMAND.address,
            city=_VALID_COMMAND.city,
            commune=_VALID_COMMAND.commune,
            latitude=_VALID_COMMAND.latitude,
            longitude=_VALID_COMMAND.longitude,
        )
        UpdateSalon(repo, audit).execute(
            salon_id, new_cmd, actor_user_id=_OWNER_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.metadata["changed"] == ["phone"]

    def test_no_changed_fields_when_identical(self) -> None:
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        salon = repo.find_by_id(salon_id)
        same_cmd = UpdateSalonCommand(
            name=salon.name,
            description=salon.description,
            phone=salon.phone,
            address=salon.address,
            city=salon.city,
            commune=salon.commune,
            latitude=salon.latitude,
            longitude=salon.longitude,
        )
        UpdateSalon(repo, audit).execute(
            salon_id, same_cmd, actor_user_id=_OWNER_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.metadata["changed"] == []

    def test_metadata_contains_no_field_values(self) -> None:
        """Non-fuite §11.4 : `metadata` ne porte que des noms de champs, jamais leur valeur."""
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon_id = self._create(repo)
        UpdateSalon(repo, audit).execute(
            salon_id,
            UpdateSalonCommand(name="Autre nom", phone="0709080706"),
            actor_user_id=_OWNER_ID,
        )
        entry: AuditEntry = audit.recorded[0]
        assert set(entry.metadata.keys()) == {"changed"}
        assert "Autre nom" not in entry.metadata["changed"]
        assert "+2250709080706" not in entry.metadata["changed"]

    def test_owner_id_not_modifiable(self) -> None:
        """Invariant : la commande ne déclare pas de champ owner_id."""
        assert not hasattr(UpdateSalonCommand(name="X"), "owner_id")

    def test_salon_from_another_owner_still_found(self) -> None:
        """`UpdateSalon` ne filtre pas par owner_id : la portée est validée en amont (HTTP)."""
        repo = FakeSalonRepository()
        audit = FakeAuditLog()
        salon = CreateSalon(repo).execute(
            CreateSalonCommand(name="Salon B"), owner_id=_OTHER_OWNER_ID
        )
        updated = UpdateSalon(repo, audit).execute(
            salon.id, UpdateSalonCommand(name="Renommé"), actor_user_id=_OWNER_ID
        )
        assert updated.name == "Renommé"


# ---------------------------------------------------------------------------
# GetSalon
# ---------------------------------------------------------------------------


class TestGetSalon:
    def _salon_id(self) -> uuid.UUID:
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(CreateSalonCommand(name="Test"), owner_id=_OWNER_ID)
        return salon.id, repo

    def test_raises_salon_not_found_for_unknown_id(self) -> None:
        repo = FakeSalonRepository()
        storage = FakeMediaStorage()
        with pytest.raises(SalonNotFound):
            GetSalon(repo, storage).execute(uuid.uuid4())

    def test_returns_salon_view(self) -> None:
        salon_id, repo = self._salon_id()
        storage = FakeMediaStorage()
        view = GetSalon(repo, storage).execute(salon_id)
        assert view.salon.id == salon_id

    def test_logo_url_none_when_no_logo(self) -> None:
        salon_id, repo = self._salon_id()
        storage = FakeMediaStorage()
        view = GetSalon(repo, storage).execute(salon_id)
        assert view.logo_url is None

    def test_logo_url_resolved_when_logo_exists(self) -> None:
        salon_id, repo = self._salon_id()
        key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        repo.set_logo(salon_id, key)
        storage = FakeMediaStorage()
        view = GetSalon(repo, storage).execute(salon_id)
        assert view.logo_url == f"https://fake-bucket.local/download/{key}?sig=fake"

    def test_logo_url_none_when_storage_not_configured(self) -> None:
        salon_id, repo = self._salon_id()
        key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        repo.set_logo(salon_id, key)
        view = GetSalon(repo, None).execute(salon_id)
        assert view.logo_url is None

    def test_photos_empty_by_default(self) -> None:
        salon_id, repo = self._salon_id()
        view = GetSalon(repo, None).execute(salon_id)
        assert view.photos == ()

    def test_is_bookable_false_at_creation(self) -> None:
        salon_id, repo = self._salon_id()
        view = GetSalon(repo, None).execute(salon_id)
        assert view.is_bookable is False

    def test_photos_urls_resolved_with_storage(self) -> None:
        """GetSalon résout les URLs signées des photos quand le stockage est configuré."""
        salon_id, repo = self._salon_id()
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        repo.add_photo(salon_id, key)
        storage = FakeMediaStorage()
        view = GetSalon(repo, storage).execute(salon_id)
        assert len(view.photos) == 1
        assert view.photos[0].url == f"https://fake-bucket.local/download/{key}?sig=fake"

    def test_photos_urls_none_without_storage(self) -> None:
        """GetSalon retourne url=None pour les photos si le stockage n'est pas configuré."""
        salon_id, repo = self._salon_id()
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        repo.add_photo(salon_id, key)
        view = GetSalon(repo, None).execute(salon_id)
        assert len(view.photos) == 1
        assert view.photos[0].url is None


# ---------------------------------------------------------------------------
# ListOwnSalons
# ---------------------------------------------------------------------------


class TestListOwnSalons:
    def test_returns_empty_for_unknown_owner(self) -> None:
        repo = FakeSalonRepository()
        views = ListOwnSalons(repo, None).execute(_OTHER_OWNER_ID)
        assert views == ()

    def test_returns_only_own_salons(self) -> None:
        repo = FakeSalonRepository()
        CreateSalon(repo).execute(CreateSalonCommand(name="A"), owner_id=_OWNER_ID)
        CreateSalon(repo).execute(CreateSalonCommand(name="B"), owner_id=_OTHER_OWNER_ID)
        views = ListOwnSalons(repo, None).execute(_OWNER_ID)
        assert len(views) == 1
        assert views[0].salon.owner_id == _OWNER_ID

    def test_returns_multiple_own_salons(self) -> None:
        repo = FakeSalonRepository()
        CreateSalon(repo).execute(CreateSalonCommand(name="A"), owner_id=_OWNER_ID)
        CreateSalon(repo).execute(CreateSalonCommand(name="B"), owner_id=_OWNER_ID)
        views = ListOwnSalons(repo, None).execute(_OWNER_ID)
        assert len(views) == 2


# ---------------------------------------------------------------------------
# IssueMediaUploadUrl
# ---------------------------------------------------------------------------


class TestIssueMediaUploadUrl:
    def test_returns_presigned_upload_for_logo(self) -> None:
        storage = FakeMediaStorage()
        salon_id = uuid.uuid4()
        result = IssueMediaUploadUrl(storage).execute(salon_id, "logo", "image/png")
        assert result.method == "PUT"
        assert result.expires_in == 900

    def test_object_key_starts_with_salon_prefix(self) -> None:
        storage = FakeMediaStorage()
        salon_id = uuid.uuid4()
        result = IssueMediaUploadUrl(storage).execute(salon_id, "logo", "image/png")
        assert result.object_key.startswith(f"salons/{salon_id}/logo/")

    def test_object_key_ends_with_mime_extension(self) -> None:
        storage = FakeMediaStorage()
        salon_id = uuid.uuid4()
        result = IssueMediaUploadUrl(storage).execute(salon_id, "photo", "image/jpeg")
        assert result.object_key.endswith(".jpg")

    def test_object_key_for_photos_uses_photos_segment(self) -> None:
        storage = FakeMediaStorage()
        salon_id = uuid.uuid4()
        result = IssueMediaUploadUrl(storage).execute(salon_id, "photo", "image/webp")
        assert "/photos/" in result.object_key

    def test_invalid_content_type_raises(self) -> None:
        storage = FakeMediaStorage()
        with pytest.raises(InvalidMediaType):
            IssueMediaUploadUrl(storage).execute(uuid.uuid4(), "logo", "image/gif")

    def test_object_key_does_not_contain_pii(self) -> None:
        """La clé ne contient ni nom, ni téléphone, ni fichier client."""
        storage = FakeMediaStorage()
        salon_id = uuid.uuid4()
        result = IssueMediaUploadUrl(storage).execute(salon_id, "logo", "image/png")
        # La clé ne doit contenir que des UUID (hex + tirets) et l'extension
        assert "salon" in result.object_key.lower()
        assert "nom" not in result.object_key
        assert "telephone" not in result.object_key

    def test_storage_called_once(self) -> None:
        storage = FakeMediaStorage()
        IssueMediaUploadUrl(storage).execute(uuid.uuid4(), "logo", "image/png")
        assert len(storage.uploads) == 1

    def test_unknown_kind_raises_media_key_mismatch(self) -> None:
        """Nature de média hors liste blanche → `MediaKeyMismatch` (garde-fou applicatif)."""
        storage = FakeMediaStorage()
        with pytest.raises(MediaKeyMismatch):
            IssueMediaUploadUrl(storage).execute(uuid.uuid4(), "video", "image/png")


# ---------------------------------------------------------------------------
# AttachSalonLogo
# ---------------------------------------------------------------------------


class TestAttachSalonLogo:
    def _setup(self):  # type: ignore[no-untyped-def]
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(CreateSalonCommand(name="Salon"), owner_id=_OWNER_ID)
        return repo, salon.id

    def test_valid_key_attached(self) -> None:
        repo, salon_id = self._setup()
        key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        AttachSalonLogo(repo, None).execute(salon_id, key)
        updated = repo.find_by_id(salon_id)
        assert updated is not None
        assert updated.logo_object_key == key

    def test_key_with_wrong_salon_prefix_raises(self) -> None:
        repo, salon_id = self._setup()
        other_id = uuid.uuid4()
        bad_key = f"salons/{other_id}/logo/{uuid.uuid4()}.png"
        with pytest.raises(MediaKeyMismatch):
            AttachSalonLogo(repo, None).execute(salon_id, bad_key)

    def test_unknown_salon_id_raises(self) -> None:
        repo = FakeSalonRepository()
        salon_id = uuid.uuid4()
        key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        with pytest.raises(SalonNotFound):
            AttachSalonLogo(repo, None).execute(salon_id, key)

    def test_old_logo_deleted_from_storage(self) -> None:
        repo, salon_id = self._setup()
        storage = FakeMediaStorage()
        old_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        repo.set_logo(salon_id, old_key)
        new_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        AttachSalonLogo(repo, storage).execute(salon_id, new_key)
        assert old_key in storage.deleted

    def test_no_deletion_when_storage_none(self) -> None:
        repo, salon_id = self._setup()
        old_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        repo.set_logo(salon_id, old_key)
        new_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        # Doit ne pas lever d'exception même sans stockage.
        AttachSalonLogo(repo, None).execute(salon_id, new_key)

    def test_same_key_is_not_deleted_from_storage(self) -> None:
        """Ré-attacher la même clé (idempotent) : l'objet ne doit pas être supprimé."""
        repo, salon_id = self._setup()
        storage = FakeMediaStorage()
        key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        repo.set_logo(salon_id, key)
        AttachSalonLogo(repo, storage).execute(salon_id, key)
        assert key not in storage.deleted


# ---------------------------------------------------------------------------
# AddSalonPhoto
# ---------------------------------------------------------------------------


class TestAddSalonPhoto:
    def _setup(self):  # type: ignore[no-untyped-def]
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(CreateSalonCommand(name="Salon"), owner_id=_OWNER_ID)
        return repo, salon.id

    def test_valid_key_adds_photo(self) -> None:
        repo, salon_id = self._setup()
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        photo = AddSalonPhoto(repo).execute(salon_id, key)
        assert photo.salon_id == salon_id
        assert photo.object_key == key

    def test_key_with_wrong_prefix_raises(self) -> None:
        repo, salon_id = self._setup()
        other_id = uuid.uuid4()
        bad_key = f"salons/{other_id}/photos/{uuid.uuid4()}.jpg"
        with pytest.raises(MediaKeyMismatch):
            AddSalonPhoto(repo).execute(salon_id, bad_key)

    def test_unknown_salon_raises(self) -> None:
        repo = FakeSalonRepository()
        salon_id = uuid.uuid4()
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        with pytest.raises(SalonNotFound):
            AddSalonPhoto(repo).execute(salon_id, key)

    def test_exceeding_max_photos_raises(self) -> None:
        repo, salon_id = self._setup()
        limit = 3
        for _ in range(limit):
            key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
            repo.add_photo(salon_id, key)
        over_key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        with pytest.raises(PhotoLimitExceeded):
            AddSalonPhoto(repo, max_photos=limit).execute(salon_id, over_key)

    def test_at_max_photos_does_not_raise(self) -> None:
        repo, salon_id = self._setup()
        limit = 2
        for _ in range(limit - 1):
            key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
            repo.add_photo(salon_id, key)
        last_key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        # Ne doit pas lever — on est juste en dessous du plafond.
        photo = AddSalonPhoto(repo, max_photos=limit).execute(salon_id, last_key)
        assert photo is not None

    def test_first_photo_has_position_zero(self) -> None:
        """La première photo ajoutée à un salon a `position=0`."""
        repo, salon_id = self._setup()
        key = f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg"
        photo = AddSalonPhoto(repo).execute(salon_id, key)
        assert photo.position == 0

    def test_logo_key_submitted_to_photo_endpoint_raises(self) -> None:
        """Clé de logo soumise à l'endpoint photo → `MediaKeyMismatch` (mauvais segment)."""
        repo, salon_id = self._setup()
        logo_key = f"salons/{salon_id}/logo/{uuid.uuid4()}.png"
        with pytest.raises(MediaKeyMismatch):
            AddSalonPhoto(repo).execute(salon_id, logo_key)


# ---------------------------------------------------------------------------
# RemoveSalonPhoto
# ---------------------------------------------------------------------------


class TestRemoveSalonPhoto:
    def _setup(self):  # type: ignore[no-untyped-def]
        repo = FakeSalonRepository()
        salon = CreateSalon(repo).execute(CreateSalonCommand(name="Salon"), owner_id=_OWNER_ID)
        key = f"salons/{salon.id}/photos/{uuid.uuid4()}.jpg"
        photo = repo.add_photo(salon.id, key)
        return repo, salon.id, photo.id, key

    def test_removes_photo_from_repository(self) -> None:
        repo, salon_id, photo_id, _ = self._setup()
        RemoveSalonPhoto(repo, None).execute(salon_id, photo_id)
        assert repo.count_photos(salon_id) == 0

    def test_deletes_object_from_storage(self) -> None:
        repo, salon_id, photo_id, key = self._setup()
        storage = FakeMediaStorage()
        RemoveSalonPhoto(repo, storage).execute(salon_id, photo_id)
        assert key in storage.deleted

    def test_unknown_photo_raises(self) -> None:
        repo, salon_id, _, _ = self._setup()
        with pytest.raises(SalonNotFound):
            RemoveSalonPhoto(repo, None).execute(salon_id, uuid.uuid4())

    def test_no_storage_call_when_storage_none(self) -> None:
        repo, salon_id, photo_id, _ = self._setup()
        # Doit ne pas lever sans stockage.
        RemoveSalonPhoto(repo, None).execute(salon_id, photo_id)
