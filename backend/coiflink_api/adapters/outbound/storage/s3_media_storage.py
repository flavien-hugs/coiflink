"""Adapter sortant : stockage objet **S3-compatible** via boto3 (ADR-0005, #15).

Implémente le port `MediaStorage` sur un client boto3 configuré par variables
d'environnement (`config.MediaConfig`). **Agnostique du fournisseur** : un
`endpoint_url` explicite vise MinIO en local ou tout service S3-compatible en
production — aucune ligne ne suppose un prestataire (contrainte ADR-0005).

Invariants de sécurité (ADR-0005, §11.3) :
- **bucket privé** : aucun objet public ; tout accès passe par une **URL signée**
  à durée limitée (`MediaConfig.url_ttl_seconds`) ;
- une **URL signée est un secret porteur** → jamais journalisée ;
- les **clés d'accès S3** viennent de l'environnement, jamais du dépôt, jamais
  journalisées.

**Deux clients boto3, un seul jeu d'identifiants** : `_client` (opérationnel,
`endpoint_url`) exécute les vrais appels réseau du backend (`delete_object`) et
vise l'hôte fiable du réseau Docker interne ; `_presign_client`
(`presign_endpoint_url`) ne fait *aucun* appel réseau — `generate_presigned_url`
est une signature locale (HMAC), pas une requête HTTP — et n'a d'autre rôle que
d'incorporer un hôte **joignable par le client final** (navigateur, mobile) dans
le texte de l'URL renvoyée. Un signataire S3v4 inclut l'en-tête `Host` dans la
requête canonique : les deux clients doivent donc chacun garder leur hôte
cohérent de bout en bout (jamais mélanger la signature de l'un avec l'hôte de
l'autre).

`boto3` est importé **paresseusement** (dans le constructeur) : l'assemblage
(`main.py`) ne crée cet adapter que si la configuration S3 est complète, et les
tests unitaires utilisent une `FakeMediaStorage` — `pytest` ne requiert donc ni
boto3 ni conteneur.
"""

from __future__ import annotations

from coiflink_api.application.ports.media_storage import PresignedUpload
from coiflink_api.config import MediaConfig


class S3MediaStorage:
    """Stockage objet S3-compatible (boto3) — implémente `MediaStorage`."""

    def __init__(self, config: MediaConfig) -> None:
        if not config.is_configured:
            raise ValueError(
                "Configuration de stockage objet incomplète (bucket/clés absents)."
            )
        try:  # Import paresseux : boto3 n'est requis que si le stockage est câblé.
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as exc:  # pragma: no cover - dépend de l'environnement
            raise RuntimeError(
                "boto3 est requis pour le stockage objet S3-compatible."
            ) from exc

        self._config = config
        self._bucket = config.bucket
        self._ttl = config.url_ttl_seconds
        boto_config = BotoConfig(signature_version="s3v4")
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url or None,
            region_name=config.region,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            # Signature v4 : requise par la plupart des services S3-compatibles.
            config=boto_config,
        )
        presign_endpoint = config.presign_endpoint_url
        # Même hôte que `_client` (cas courant, ex. AWS S3 pur ou domaine public en
        # prod) : pas besoin d'un second client, `generate_presigned_url` donnerait
        # de toute façon un résultat identique.
        self._presign_client = (
            self._client
            if presign_endpoint == (config.endpoint_url or "")
            else boto3.client(
                "s3",
                endpoint_url=presign_endpoint or None,
                region_name=config.region,
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
                config=boto_config,
            )
        )

    def presign_upload(self, object_key: str, content_type: str) -> PresignedUpload:
        """URL signée de **téléversement** (`PUT`) figeant le `Content-Type`.

        Le client (navigateur) doit envoyer le même `Content-Type` : la signature
        le couvre, ce qui borne le type côté serveur (pas seulement le front).
        """

        url = self._presign_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=self._ttl,
        )
        return PresignedUpload(
            url=url,
            object_key=object_key,
            method="PUT",
            headers={"Content-Type": content_type},
            expires_in=self._ttl,
        )

    def presign_download(self, object_key: str) -> str:
        """URL signée de **lecture** à durée limitée (jamais d'URL publique)."""

        return self._presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=self._ttl,
        )

    def delete(self, object_key: str) -> None:
        """Supprime l'objet du bucket (idempotent côté S3 : absent ⇒ succès)."""

        self._client.delete_object(Bucket=self._bucket, Key=object_key)


__all__ = ["S3MediaStorage"]
