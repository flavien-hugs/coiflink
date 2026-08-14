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
from coiflink_api.domain.service import Service, ServicePhoto

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


def _service_photo(
    service: Service, *, object_key: str = "services/salon-id/photo.png", position: int = 0
) -> ServicePhoto:
    return ServicePhoto(
        id=uuid.uuid4(),
        salon_id=service.salon_id,
        service_id=service.id,
        object_key=object_key,
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
# URL signée des prestations — ADR-0005 (#158)
# ---------------------------------------------------------------------------


def test_service_image_url_signed_when_key_set_and_storage_configured() -> None:
    # Une couverture (position 0) + FakeMediaStorage → image_url est l'URL signée.
    salon = _salon()
    svc = _service(salon.id)
    photo = _service_photo(svc, object_key="services/salon-id/photo.png")
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [svc]}, service_photos={svc.id: [photo]}
    )

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)
    service = view.services[0]

    expected_url = FakeMediaStorage().presign_download("services/salon-id/photo.png")
    assert service.image_url == expected_url
    assert "?" in service.image_url  # URL signée, pas clé brute
    assert service.image_url != "services/salon-id/photo.png"


def test_service_image_url_none_when_no_photo() -> None:
    # Aucune photo → image_url is None, même avec un stockage configuré.
    salon = _salon()
    svc = _service(salon.id)
    repo = FakeSalonCatalogRepository([salon], services={salon.id: [svc]})

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)

    assert view.services[0].image_url is None


def test_service_image_url_none_without_storage_even_with_photo() -> None:
    # Stockage non configuré → image_url is None même si une photo existe.
    # La règle de résilience (spec §Security) : jamais d'exception 5xx, image_url=null.
    salon = _salon()
    svc = _service(salon.id)
    photo = _service_photo(svc, object_key="services/salon-id/photo.png")
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [svc]}, service_photos={svc.id: [photo]}
    )

    view = GetPublicSalon(repo, media_storage=None).execute(salon.id)

    assert view.services[0].image_url is None


def test_service_view_image_object_key_not_in_fields() -> None:
    # ADR-0005 / spec §A.4 : la clé d'objet brute ne doit jamais franchir la
    # frontière publique — PublicServiceView ne porte pas image_object_key.
    salon = _salon()
    svc = _service(salon.id)
    photo = _service_photo(svc, object_key="services/salon-id/photo.png")
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [svc]}, service_photos={svc.id: [photo]}
    )

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)
    field_names = {f.name for f in dataclasses.fields(view.services[0])}

    assert "image_object_key" not in field_names
    # Vérification complémentaire : le champ exposé est bien image_url (URL signée).
    assert "image_url" in field_names


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


# ---------------------------------------------------------------------------
# Anti N+1 — une seule requête groupée pour les photos de TOUTES les prestations
# ---------------------------------------------------------------------------


def test_service_photos_fetched_in_a_single_call_regardless_of_service_count() -> None:
    # Régression : list_service_photos(salon_id) doit être appelée UNE SEULE
    # fois par exécution, jamais une fois par prestation (anti N+1).
    salon = _salon()
    services = [_service(salon.id, name=f"Prestation {i}") for i in range(5)]
    photos = {
        services[0].id: [_service_photo(services[0])],
        services[2].id: [_service_photo(services[2]), _service_photo(services[2], position=1)],
    }
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: services}, service_photos=photos
    )

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)

    assert repo.list_service_photos_calls == [salon.id]
    by_name = {sv.name: sv for sv in view.services}
    assert by_name["Prestation 0"].image_url is not None
    assert by_name["Prestation 2"].image_url is not None
    assert by_name["Prestation 1"].image_url is None


# ---------------------------------------------------------------------------
# Galerie complète (pas seulement la couverture) — client borne kiosque
# ---------------------------------------------------------------------------


def test_service_view_exposes_the_full_photo_gallery_not_only_the_cover() -> None:
    # La borne kiosque parcourt TOUTES les photos, pas seulement image_url.
    salon = _salon()
    svc = _service(salon.id)
    photo0 = _service_photo(svc, object_key="services/salon-id/a.png", position=0)
    photo1 = _service_photo(svc, object_key="services/salon-id/b.png", position=1)
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [svc]}, service_photos={svc.id: [photo0, photo1]}
    )

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)
    service = view.services[0]

    assert len(service.photos) == 2
    assert service.photos[0].url == service.image_url  # couverture = photos[0]
    assert all(p.url is not None and "?" in p.url for p in service.photos)


def test_service_view_photos_empty_list_when_no_photo() -> None:
    salon = _salon()
    svc = _service(salon.id)
    repo = FakeSalonCatalogRepository([salon], services={salon.id: [svc]})

    view = GetPublicSalon(repo, FakeMediaStorage()).execute(salon.id)

    assert view.services[0].photos == ()
