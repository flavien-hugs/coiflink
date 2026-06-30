# ADR-0005 : Stockage de fichiers — objet S3-compatible

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10.2 (stockage fichiers), §11.3 (données personnelles), §11.4 (journalisation)

## Contexte et problème

CoifLink doit stocker des **fichiers binaires** : logos et photos de salons (§10.2), et plus tard
d'autres médias. Stocker ces binaires en base de données est inadapté (poids, coût, scalabilité,
diffusion). Le PRD recommande un « stockage objet **S3 compatible** ou stockage cloud sécurisé ».
La plateforme d'hébergement concrète n'est pas encore décidée (rattachée à #4/#5) : il faut une
décision qui **n'enferme pas** le projet chez un fournisseur précis.

## Options envisagées

- **Option A — API objet S3-compatible**, via une bibliothèque cliente standard (p. ex. boto3),
  en restant **agnostique du fournisseur** (AWS S3, MinIO auto-hébergé, Cloudflare R2, bucket de la
  plateforme d'hébergement…).
- **Option B — stockage des binaires en base** (PostgreSQL/bytea ou large objects). Écarté : gonfle
  la base, complique les sauvegardes, mauvais pour la diffusion/CDN.
- **Option C — système de fichiers local du serveur applicatif.** Écarté : non portable, non
  scalable, incompatible avec plusieurs instances et avec un déploiement conteneurisé.

## Décision

Les fichiers sont stockés dans un **stockage objet exposant une API S3-compatible**, accédé via une
bibliothèque cliente standard. L'ADR fixe **l'interface (S3-compatible)**, pas le fournisseur.

## Justification (compromis)

- **Ne pas stocker les binaires en base** : meilleure scalabilité, sauvegardes plus simples, coût
  maîtrisé.
- **Compatibilité CDN** et URLs d'objets : diffusion efficace des médias publics (logos, photos).
- **Portabilité** : l'API S3 est un standard de fait ; cibler l'interface plutôt qu'un fournisseur
  évite le verrouillage et permet de choisir le prestataire au moment du déploiement.
- **Compromis accepté** : le **fournisseur concret reste à choisir** au déploiement (#4/#5) ; tant
  qu'il ne l'est pas, on développe et teste contre un service S3-compatible (p. ex. MinIO en local).

## Conséquences

- **Positives** : binaires hors base, portabilité fournisseur, diffusion CDN-friendly.
- **Négatives / risques** : dépendance à un service externe à provisionner ; un fournisseur devra
  être arrêté en phase de déploiement.
- **Sécurité (renvoi §11.3)** — contraintes à respecter par l'implémentation (M2+) :
  - **buckets privés par défaut** ; accès via **URLs signées à durée limitée** ;
  - **aucune PII dans les noms d'objets / chemins** (pas de numéro de téléphone, nom client, etc.) ;
  - **identifiants d'accès (clés S3) gérés hors dépôt**, injectés par l'environnement (#5) — jamais
    committés ni journalisés.
- **Suivi / à confirmer (non bloquant)** :
  - **fournisseur concret** (AWS S3 / MinIO / R2 / bucket de la plateforme) → décision de
    déploiement #4/#5 ;
  - bibliothèque cliente précise (p. ex. boto3) → #2/#3.
