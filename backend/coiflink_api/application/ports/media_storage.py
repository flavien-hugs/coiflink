"""Port de **stockage objet S3-compatible** (`Protocol`, ADR-0005, #15).

Le cas d'usage `application/salons.py` déclare ici son besoin de stockage de
médias (logo, photos) ; l'implémentation concrète vit dans
`adapters/outbound/storage/s3_media_storage.py` (boto3). Conformément à
l'hexagonal (ADR-0008), l'application ne connaît **ni** boto3, **ni** le
fournisseur : l'ADR-0005 fixe l'**interface**, pas le prestataire.

Contraintes de sécurité portées par ce contrat (ADR-0005, §11.3) :

- **bucket privé** : aucun objet n'est lisible publiquement ; tout accès passe
  par une **URL signée à durée limitée** (`presign_upload` / `presign_download`) ;
- **aucune PII dans la clé d'objet** : la clé est fabriquée par le serveur à
  partir d'UUID opaques (jamais le nom de fichier client) — voir `salons.py` ;
- une **URL signée est un secret porteur** (elle contient la signature) : elle
  n'est **jamais** journalisée ni placée dans un message d'erreur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class PresignedUpload:
    """Instructions de téléversement direct navigateur → stockage objet (#15).

    Le navigateur exécute `method url` avec `headers`, sans jamais transiter par
    l'API (le binaire ne consomme aucun budget mémoire/latence de l'API, §12).
    `url` est un **secret porteur** : ne jamais la journaliser.
    """

    url: str
    object_key: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)
    expires_in: int = 900


class MediaStorage(Protocol):
    """Contrat de stockage objet S3-compatible (bucket privé, URLs signées)."""

    def presign_upload(self, object_key: str, content_type: str) -> PresignedUpload:
        """URL signée de **téléversement** (`PUT`) pour cette clé et ce type MIME.

        La politique de l'URL signée borne la taille et fige le `Content-Type` :
        la validation ne repose pas seulement sur le front.
        """
        ...

    def presign_download(self, object_key: str) -> str:
        """URL signée de **lecture** à durée limitée (jamais d'URL publique)."""
        ...

    def delete(self, object_key: str) -> None:
        """Supprime l'objet du bucket (idempotent : absent ⇒ pas d'erreur)."""
        ...


__all__ = ["MediaStorage", "PresignedUpload"]
