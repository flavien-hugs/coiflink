"""Couche application : cas d'usage orchestrant le domaine.

Dépend du `domaine`, jamais des `adapters`. Déclare ses besoins externes sous
forme de **ports** (voir `ports/`) que les adapters sortants implémentent.
Vide au démarrage (#2/ADR-0008).
"""
