"""Tests unitaires — cas d'usage `GetPublicSalon` (fiche client, US-2.4, #19).

Exerce l'agrégation de la fiche publique **sans base ni réseau** (fakes de
conftest). Couvre les invariants portés par le cas d'usage (spec §Testing) :

- salon `ACTIVE` → détail complet ; `INACTIVE`/`SUSPENDED`/inconnu → `SalonNotFound` ;
- `services` ne contient **que** les prestations `is_active=True` ;
- `opening_hours` remontés tels quels ; `None` si non configuré → `is_bookable=False` ;
- `logo_url`/`photos` signés via `FakeMediaStorage` ; `None`/`[]` si stockage absent ;
- la projection **n'expose pas** `owner_id`/`status`/`is_active`/`salon_id`/timestamps.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import uuid

import pytest

from coiflink_api.application.catalog import (
    GetPublicSalon,
    PublicSalonDetailView,
    PublicServiceView,
)
from coiflink_api.domain.enums import SalonStatus
from coiflink_api.domain.errors import SalonNotFound
from coiflink_api.domain.salon import Salon, SalonPhoto
from coiflink_api.domain.service import Service

from .conftest import FakeMediaStorage, FakeSalonCatalogRepository

_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

_OPENING_HOURS = {
    "version": 1,
    "timezone": "Africa/Abidjan",
    "weekly": {"mon": [{"start": "08:00", "end": "18:00"}]},
    "exceptions": [],
}


def _salon(
    *,
    salon_id: uuid.UUID | None = None,
    status: str = SalonStatus.ACTIVE.value,
    opening_hours: dict | None = None,
    logo_object_key: str | None = None,
) -> Salon:
    return Salon(
        id=salon_id or uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Salon Élégance",
        description="Coiffure afro et tresses.",
        phone="+2250700000000",
        address="Rue des Jardins, Cocody",
        city="Abidjan",
        commune="Cocody",
        latitude=decimal.Decimal("5.359952"),
        longitude=decimal.Decimal("-3.996643"),
        logo_object_key=logo_object_key,
        status=status,
        opening_hours=opening_hours,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _service(
    salon_id: uuid.UUID,
    *,
    name: str = "Coupe homme",
    is_active: bool = True,
) -> Service:
    return Service(
        id=uuid.uuid4(),
        salon_id=salon_id,
        name=name,
        description="Coupe aux ciseaux.",
        price=decimal.Decimal("5000.00"),
        duration_minutes=30,
        category="Coupe",
        is_active=is_active,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _photo(salon_id: uuid.UUID, *, position: int = 0) -> SalonPhoto:
    return SalonPhoto(
        id=uuid.uuid4(),
        salon_id=salon_id,
        object_key=f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg",
        position=position,
        created_at=_CREATED_AT,
    )


# ---------------------------------------------------------------------------
# Visibilité §8.3 — seul un salon ACTIVE a une fiche
# ---------------------------------------------------------------------------


def test_active_salon_returns_detail_view() -> None:
    salon = _salon(opening_hours=_OPENING_HOURS)
    repo = FakeSalonCatalogRepository([salon])

    view = GetPublicSalon(repo).execute(salon.id)

    assert isinstance(view, PublicSalonDetailView)
    assert view.id == salon.id
    assert view.name == "Salon Élégance"
    assert view.phone == "+2250700000000"
    assert view.opening_hours == _OPENING_HOURS
    assert view.is_bookable is True


@pytest.mark.parametrize(
    "status",
    [SalonStatus.INACTIVE.value, SalonStatus.SUSPENDED.value],
)
def test_non_active_salon_raises_not_found(status: str) -> None:
    salon = _salon(status=status)
    repo = FakeSalonCatalogRepository([salon])

    with pytest.raises(SalonNotFound):
        GetPublicSalon(repo).execute(salon.id)


def test_unknown_salon_raises_not_found() -> None:
    repo = FakeSalonCatalogRepository([_salon()])

    with pytest.raises(SalonNotFound):
        GetPublicSalon(repo).execute(uuid.uuid4())


# ---------------------------------------------------------------------------
# Prestations — actives seulement
# ---------------------------------------------------------------------------


def test_services_exclude_inactive() -> None:
    salon = _salon()
    services = {
        salon.id: [
            _service(salon.id, name="Coupe homme", is_active=True),
            _service(salon.id, name="Tresses", is_active=False),
            _service(salon.id, name="Coloration", is_active=True),
        ]
    }
    repo = FakeSalonCatalogRepository([salon], services=services)

    view = GetPublicSalon(repo).execute(salon.id)

    names = {service.name for service in view.services}
    assert names == {"Coupe homme", "Coloration"}
    assert all(isinstance(s, PublicServiceView) for s in view.services)


def test_service_view_exposes_price_and_duration() -> None:
    salon = _salon()
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [_service(salon.id)]}
    )

    view = GetPublicSalon(repo).execute(salon.id)
    service = view.services[0]

    assert service.price == decimal.Decimal("5000.00")
    assert service.duration_minutes == 30
    assert service.category == "Coupe"


def test_service_view_has_no_management_fields() -> None:
    salon = _salon()
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [_service(salon.id)]}
    )

    view = GetPublicSalon(repo).execute(salon.id)
    field_names = {f.name for f in dataclasses.fields(view.services[0])}

    assert "is_active" not in field_names
    assert "salon_id" not in field_names
    assert "created_at" not in field_names
    assert "updated_at" not in field_names


def test_salon_without_services_yields_empty_tuple() -> None:
    salon = _salon()
    repo = FakeSalonCatalogRepository([salon])

    view = GetPublicSalon(repo).execute(salon.id)

    assert view.services == ()


def test_service_view_exposes_name_id_and_description() -> None:
    # `id`, `name` et `description` doivent être présents : le mobile les affiche.
    salon = _salon()
    svc = _service(salon.id, name="Coupe femme")
    repo = FakeSalonCatalogRepository([salon], services={salon.id: [svc]})

    view = GetPublicSalon(repo).execute(salon.id)
    service = view.services[0]

    assert service.id == svc.id
    assert service.name == "Coupe femme"
    assert service.description == "Coupe aux ciseaux."


# ---------------------------------------------------------------------------
# Horaires & disponibilité §8.3
# ---------------------------------------------------------------------------


def test_opening_hours_none_makes_salon_not_bookable() -> None:
    salon = _salon(opening_hours=None)
    repo = FakeSalonCatalogRepository([salon])

    view = GetPublicSalon(repo).execute(salon.id)

    assert view.opening_hours is None
    assert view.is_bookable is False


# ---------------------------------------------------------------------------
# Médias — URLs signées, jamais de clé brute
# ---------------------------------------------------------------------------


def test_logo_and_photos_signed_with_storage() -> None:
    salon = _salon(logo_object_key="salons/logo.jpg")
    photos = {salon.id: [_photo(salon.id, position=0), _photo(salon.id, position=1)]}
    repo = FakeSalonCatalogRepository([salon], photos=photos)

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)

    assert view.logo_url is not None
    assert "salons/logo.jpg" not in view.logo_url or "?" in view.logo_url
    assert len(view.photos) == 2
    assert all(photo.url is not None and "?" in photo.url for photo in view.photos)


def test_logo_and_photos_null_without_storage() -> None:
    salon = _salon(logo_object_key="salons/logo.jpg")
    photos = {salon.id: [_photo(salon.id)]}
    repo = FakeSalonCatalogRepository([salon], photos=photos)

    view = GetPublicSalon(repo, media_storage=None).execute(salon.id)

    assert view.logo_url is None
    assert view.photos[0].url is None


def test_logo_url_none_when_no_object_key_even_with_storage() -> None:
    # _sign(None) → None : même avec un stockage configuré, l'absence de clé
    # donne logo_url=None (invariant ADR-0005 : jamais de clé brute exposée).
    salon = _salon(logo_object_key=None)
    repo = FakeSalonCatalogRepository([salon])

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)

    assert view.logo_url is None


# ---------------------------------------------------------------------------
# Projection — pas de fuite de donnée de gestion
# ---------------------------------------------------------------------------


def test_detail_view_has_no_management_fields() -> None:
    salon = _salon()
    repo = FakeSalonCatalogRepository([salon])

    view = GetPublicSalon(repo).execute(salon.id)
    field_names = {f.name for f in dataclasses.fields(view)}

    assert "owner_id" not in field_names
    assert "status" not in field_names
    assert "created_at" not in field_names
    assert "updated_at" not in field_names
    assert "logo_object_key" not in field_names
