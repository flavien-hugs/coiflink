"""Tests unitaires — cas d'usage SearchSalons (application/catalog.py, #18).

Couvre :
- invariant §8.3 : seuls les salons ACTIVE sont renvoyés (INACTIVE/SUSPENDED exclus) ;
- recherche par nom (text), filtre par ville/commune ;
- résolution du logo en URL signée (avec et sans MediaStorage) ;
- projection publique : owner_id, status, opening_hours, phone absents de PublicSalonView ;
- is_bookable : vrai si ACTIVE + opening_hours, faux sinon ;
- pagination : limit, offset, total cohérents ;
- escape_like : métacaractères LIKE (%, _, \\) correctement échappés.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import escape_like
from coiflink_api.application.catalog import SearchSalons
from coiflink_api.application.ports.salon_catalog_repository import SalonSearchQuery
from coiflink_api.domain.enums import SalonStatus
from coiflink_api.domain.salon import Salon

from .conftest import FakeMediaStorage, FakeSalonCatalogRepository

_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_OWNER_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")


def _make_salon(
    *,
    name: str = "Salon Test",
    status: str = SalonStatus.ACTIVE.value,
    city: str | None = "Abidjan",
    commune: str | None = "Cocody",
    logo_object_key: str | None = None,
    opening_hours: dict | None = None,
) -> Salon:
    return Salon(
        id=uuid.uuid4(),
        owner_id=_OWNER_ID,
        name=name,
        description="Description test.",
        phone="+2250700000000",
        address="Rue des Jardins",
        city=city,
        commune=commune,
        latitude=decimal.Decimal("5.36"),
        longitude=decimal.Decimal("-3.99"),
        logo_object_key=logo_object_key,
        status=status,
        opening_hours=opening_hours,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


# ---------------------------------------------------------------------------
# §8.3 — seuls les salons ACTIVE sont renvoyés
# ---------------------------------------------------------------------------


def test_only_active_salons_returned() -> None:
    active = _make_salon(name="Salon Actif")
    inactive = _make_salon(name="Salon Inactif", status=SalonStatus.INACTIVE.value)
    suspended = _make_salon(name="Salon Suspendu", status=SalonStatus.SUSPENDED.value)
    repo = FakeSalonCatalogRepository([active, inactive, suspended])

    page = SearchSalons(repo).execute(SalonSearchQuery())

    assert len(page.items) == 1
    assert page.items[0].name == "Salon Actif"
    assert page.total == 1


def test_inactive_salon_excluded() -> None:
    repo = FakeSalonCatalogRepository(
        [_make_salon(name="Inactif", status=SalonStatus.INACTIVE.value)]
    )
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert page.items == ()
    assert page.total == 0


def test_suspended_salon_excluded() -> None:
    repo = FakeSalonCatalogRepository(
        [_make_salon(name="Suspendu", status=SalonStatus.SUSPENDED.value)]
    )
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert page.items == ()
    assert page.total == 0


# ---------------------------------------------------------------------------
# Recherche par nom
# ---------------------------------------------------------------------------


def test_text_search_filters_by_name() -> None:
    s1 = _make_salon(name="Salon Élégance")
    s2 = _make_salon(name="Coiffure Moderne")
    repo = FakeSalonCatalogRepository([s1, s2])

    page = SearchSalons(repo).execute(SalonSearchQuery(text="élég"))

    assert len(page.items) == 1
    assert page.items[0].name == "Salon Élégance"


def test_text_search_no_match_returns_empty() -> None:
    repo = FakeSalonCatalogRepository([_make_salon(name="Salon Test")])
    page = SearchSalons(repo).execute(SalonSearchQuery(text="introuvable"))
    assert page.items == ()
    assert page.total == 0


def test_text_search_inactive_salon_not_returned_even_if_name_matches() -> None:
    repo = FakeSalonCatalogRepository(
        [_make_salon(name="Salon Élégan Inactif", status=SalonStatus.INACTIVE.value)]
    )
    page = SearchSalons(repo).execute(SalonSearchQuery(text="Élégan"))
    assert page.items == ()


# ---------------------------------------------------------------------------
# Filtre de zone
# ---------------------------------------------------------------------------


def test_city_filter_returns_matching_city_only() -> None:
    s_abidjan = _make_salon(name="Salon Abidjan", city="Abidjan")
    s_yopo = _make_salon(name="Salon Yopougon", city="Yopougon")
    repo = FakeSalonCatalogRepository([s_abidjan, s_yopo])

    page = SearchSalons(repo).execute(SalonSearchQuery(city="Abidjan"))

    assert len(page.items) == 1
    assert page.items[0].name == "Salon Abidjan"


def test_commune_filter_returns_matching_commune_only() -> None:
    s_cocody = _make_salon(name="Salon Cocody", commune="Cocody")
    s_plateau = _make_salon(name="Salon Plateau", commune="Plateau")
    repo = FakeSalonCatalogRepository([s_cocody, s_plateau])

    page = SearchSalons(repo).execute(SalonSearchQuery(commune="Plateau"))

    assert len(page.items) == 1
    assert page.items[0].name == "Salon Plateau"


# ---------------------------------------------------------------------------
# Résolution du logo
# ---------------------------------------------------------------------------


def test_logo_url_resolved_via_media_storage() -> None:
    salon = _make_salon(logo_object_key="salons/logo.jpg")
    repo = FakeSalonCatalogRepository([salon])

    page = SearchSalons(repo, FakeMediaStorage()).execute(SalonSearchQuery())

    assert page.items[0].logo_url == (
        "https://fake-bucket.local/download/salons/logo.jpg?sig=fake"
    )


def test_logo_url_null_when_no_object_key() -> None:
    salon = _make_salon(logo_object_key=None)
    repo = FakeSalonCatalogRepository([salon])

    page = SearchSalons(repo, FakeMediaStorage()).execute(SalonSearchQuery())

    assert page.items[0].logo_url is None


def test_logo_url_null_when_no_storage_configured() -> None:
    salon = _make_salon(logo_object_key="salons/logo.jpg")
    repo = FakeSalonCatalogRepository([salon])

    page = SearchSalons(repo, None).execute(SalonSearchQuery())

    assert page.items[0].logo_url is None


# ---------------------------------------------------------------------------
# Projection publique — champs de gestion absents de PublicSalonView
# ---------------------------------------------------------------------------


def test_public_view_has_no_owner_id_attribute() -> None:
    repo = FakeSalonCatalogRepository([_make_salon()])
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert not hasattr(page.items[0], "owner_id")


def test_public_view_has_no_status_attribute() -> None:
    repo = FakeSalonCatalogRepository([_make_salon()])
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert not hasattr(page.items[0], "status")


def test_public_view_has_no_opening_hours_attribute() -> None:
    repo = FakeSalonCatalogRepository([_make_salon()])
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert not hasattr(page.items[0], "opening_hours")


def test_public_view_has_no_phone_attribute() -> None:
    repo = FakeSalonCatalogRepository([_make_salon()])
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert not hasattr(page.items[0], "phone")


# ---------------------------------------------------------------------------
# is_bookable (§8.3)
# ---------------------------------------------------------------------------


def test_is_bookable_false_when_no_opening_hours() -> None:
    salon = _make_salon(opening_hours=None)
    repo = FakeSalonCatalogRepository([salon])
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert page.items[0].is_bookable is False


def test_is_bookable_false_when_opening_hours_empty_dict() -> None:
    salon = _make_salon(opening_hours={})
    repo = FakeSalonCatalogRepository([salon])
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert page.items[0].is_bookable is False


def test_is_bookable_true_when_opening_hours_set() -> None:
    salon = _make_salon(opening_hours={"monday": {"open": "09:00", "close": "18:00"}})
    repo = FakeSalonCatalogRepository([salon])
    page = SearchSalons(repo).execute(SalonSearchQuery())
    assert page.items[0].is_bookable is True


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_limit_respected() -> None:
    salons = [_make_salon(name=f"Salon {i:02d}") for i in range(10)]
    repo = FakeSalonCatalogRepository(salons)

    page = SearchSalons(repo).execute(SalonSearchQuery(limit=3, offset=0))

    assert len(page.items) == 3
    assert page.limit == 3
    assert page.offset == 0


def test_pagination_offset_skips_first_results() -> None:
    salons = [_make_salon(name=f"Salon {chr(65 + i)}") for i in range(5)]
    repo = FakeSalonCatalogRepository(salons)

    page = SearchSalons(repo).execute(SalonSearchQuery(limit=2, offset=2))

    assert len(page.items) == 2
    assert page.items[0].name == "Salon C"
    assert page.items[1].name == "Salon D"


def test_total_counts_all_matching_regardless_of_page() -> None:
    salons = [_make_salon(name=f"Salon {i:02d}") for i in range(15)]
    repo = FakeSalonCatalogRepository(salons)

    page = SearchSalons(repo).execute(SalonSearchQuery(limit=5, offset=0))

    assert len(page.items) == 5
    assert page.total == 15


def test_total_excludes_inactive_even_without_pagination() -> None:
    salons = [
        _make_salon(name="A"),
        _make_salon(name="B", status=SalonStatus.INACTIVE.value),
        _make_salon(name="C"),
    ]
    repo = FakeSalonCatalogRepository(salons)

    page = SearchSalons(repo).execute(SalonSearchQuery(limit=50, offset=0))

    assert page.total == 2
    assert len(page.items) == 2


# ---------------------------------------------------------------------------
# escape_like
# ---------------------------------------------------------------------------


def test_escape_like_percent() -> None:
    assert "\\%" in escape_like("50%")


def test_escape_like_underscore() -> None:
    assert "\\_" in escape_like("hello_world")


def test_escape_like_backslash_escaped_before_others() -> None:
    # "a\b" (one backslash) → "a\\b" (two backslashes)
    assert escape_like("a\\b") == "a\\\\b"


def test_escape_like_combined_metacharacters() -> None:
    # "100%_done" → "100\%\_done"
    assert escape_like("100%_done") == "100\\%\\_done"


def test_escape_like_no_metacharacters_unchanged() -> None:
    assert escape_like("hello") == "hello"


def test_escape_like_empty_string() -> None:
    assert escape_like("") == ""
