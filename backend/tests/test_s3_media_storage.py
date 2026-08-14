"""Tests unitaires pour `S3MediaStorage` (adapter sortant, ADR-0005, #15).

`generate_presigned_url` est une signature **locale** (HMAC), sans appel
réseau — ces tests instancient l'adapter avec des identifiants factices et
n'exigent ni MinIO ni conteneur.

Portée : le couple `endpoint_url` (appels réseau internes) /
`public_endpoint_url` (hôte incorporé dans l'URL renvoyée aux clients) —
introduit pour corriger un défaut d'accessibilité des images depuis un client
qui ne vit pas sur le réseau Docker interne (navigateur hors machine de dev,
application mobile). Voir `MediaConfig.presign_endpoint_url`.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from coiflink_api.adapters.outbound.storage.s3_media_storage import S3MediaStorage
from coiflink_api.config import MediaConfig

_BASE_KWARGS = {
    "bucket": "coiflink-media",
    "region": "us-east-1",
    "access_key_id": "coiflink-dev",
    "secret_access_key": "s3cret-dev-value",
}


def _host(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class TestPresignDownload:
    def test_uses_endpoint_url_when_no_public_endpoint_configured(self) -> None:
        storage = S3MediaStorage(MediaConfig(endpoint_url="http://minio:9000", **_BASE_KWARGS))
        url = storage.presign_download("services/abc/photo.jpg")
        assert _host(url) == "http://minio:9000"

    def test_uses_public_endpoint_url_when_configured(self) -> None:
        storage = S3MediaStorage(
            MediaConfig(
                endpoint_url="http://minio:9000",
                public_endpoint_url="http://192.168.1.128:9000",
                **_BASE_KWARGS,
            )
        )
        url = storage.presign_download("services/abc/photo.jpg")
        assert _host(url) == "http://192.168.1.128:9000"

    def test_object_key_and_bucket_appear_in_the_url(self) -> None:
        storage = S3MediaStorage(
            MediaConfig(
                endpoint_url="http://minio:9000",
                public_endpoint_url="http://192.168.1.128:9000",
                **_BASE_KWARGS,
            )
        )
        url = storage.presign_download("services/abc/photo.jpg")
        assert "/coiflink-media/services/abc/photo.jpg" in url


class TestPresignUpload:
    def test_uses_public_endpoint_url_when_configured(self) -> None:
        storage = S3MediaStorage(
            MediaConfig(
                endpoint_url="http://minio:9000",
                public_endpoint_url="http://192.168.1.128:9000",
                **_BASE_KWARGS,
            )
        )
        presigned = storage.presign_upload("services/abc/photo.jpg", "image/jpeg")
        assert _host(presigned.url) == "http://192.168.1.128:9000"
        assert presigned.method == "PUT"
        assert presigned.object_key == "services/abc/photo.jpg"
        assert presigned.headers == {"Content-Type": "image/jpeg"}

    def test_falls_back_to_endpoint_url_by_default(self) -> None:
        storage = S3MediaStorage(MediaConfig(endpoint_url="http://minio:9000", **_BASE_KWARGS))
        presigned = storage.presign_upload("services/abc/photo.jpg", "image/jpeg")
        assert _host(presigned.url) == "http://minio:9000"


class TestSameEndpointOptimisation:
    """Quand `public_endpoint_url` coïncide avec `endpoint_url` (ou est absent),
    aucun second client boto3 n'est nécessaire — comportement observable
    identique, vérifié ici plutôt que l'implémentation interne."""

    def test_identical_endpoints_produce_the_same_host(self) -> None:
        storage = S3MediaStorage(
            MediaConfig(
                endpoint_url="http://minio:9000",
                public_endpoint_url="http://minio:9000",
                **_BASE_KWARGS,
            )
        )
        url = storage.presign_download("k")
        assert _host(url) == "http://minio:9000"
