"""Couche domaine : entités, objets-valeur et règles métier.

Cœur de l'hexagone. Zéro dépendance vers un framework ou un moyen d'I/O
(ni FastAPI, ni base de données, ni réseau). Vide au démarrage (#2/ADR-0008) ;
se remplit avec les fonctionnalités M1→.
"""
