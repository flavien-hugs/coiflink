"""Adapters sortants de **stockage objet** (S3-compatible, ADR-0005, #15).

Ce paquet héberge l'implémentation concrète du port
`application.ports.media_storage.MediaStorage`. Il est **agnostique du
fournisseur** : un `endpoint_url` explicite permet de viser MinIO en local ou
n'importe quel service S3-compatible en production (ADR-0005).
"""

from __future__ import annotations

__all__: list[str] = []
