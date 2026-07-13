# ADR-0017 : Création d'un salon — rattachement au gérant, médias par URL signée & réservabilité

- **Statut** : Accepté
- **Date** : 2026-07-13
- **Décideurs** : équipe CoifLink
- **Issue** : #15 (US-2.1 — Création d'un salon)
- **Référence PRD** : §6 (Épic 2, US-2.1), §4.1 (permissions `SALON_*`), §7.2 (Paramètres :
  informations / horaires / photos / localisation), §8.3 (réservabilité : « sans horaire ⇒ non
  réservable »), §9.2 (schéma salon), §11.2 (isolation par salon), §11.3 (PII, non-journalisation)
- **S'appuie sur** : [ADR-0005](./0005-stockage-objet-s3-compatible.md) (stockage objet
  S3-compatible, bucket privé, URLs signées, clés sans PII), [ADR-0008](./0008-architecture-hexagonale.md)
  (hexagonal), [ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md) (SQLAlchemy 2.0 + Alembic),
  [ADR-0011](./0011-deploiement-environnements-secrets.md) (secrets hors dépôt, région
  `europe-west4`), [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default),
  [ADR-0016](./0016-comptes-employes-appartenance-salon.md) (anti-élévation `owner`/`role` côté serveur)

## Contexte et problème

Le socle d'authentification/autorisation est livré (M1), mais **aucun salon ne peut être créé** : ni
route, ni cas d'usage, ni dépôt pour l'entité `Salon`. La permission `SALON_CREATE` (§4.1) n'est câblée
sur aucune route, et `SqlSalonScopeRepository` calcule la portée d'un gérant par `salons.owner_id` — or
aucun gérant ne possède de salon, donc sa portée est **toujours vide** (ce qui répond `403` à
`POST /salons/{salon_id}/employees`, #13, et bloque tout M2–M5).

US-2.1 demande la création d'un salon (nom, logo, description, téléphone, localisation, **photos**),
avec pour critères d'acceptation : **(1)** un gérant crée un salon rattaché à son compte ; **(2)** un
salon **sans horaire n'est pas encore réservable** (§8.3).

## Options envisagées

- **Médias via URL signée + table `salon_photos` [retenue]** : le salon est créé d'abord ; le
  navigateur téléverse ensuite **directement** vers le stockage objet via une URL signée ; l'API ne
  relaie aucun binaire.
- **Upload `multipart/form-data` à travers l'API** : plus simple côté client, mais l'API relaie le
  binaire (budget mémoire/latence, PRD §12) et sortirait la clé d'objet du périmètre
  `/salons/{salon_id}/…` couvert par `require_salon_scope`.
- **Photos en JSONB sur `salons`** : évite une table, mais ne permet ni contrainte d'unicité, ni FK, ni
  index, ni suppression ciblée — inadapté à une collection ordonnée de médias.

## Décision

**(a) `owner_id` imposé par le serveur.** `POST /salons` fixe `owner_id = principal.id` ; le corps de
requête **ne déclare aucun** champ `owner_id`/`status`/`opening_hours`. Invariant anti-élévation de
privilège (miroir du `role` absent de `CreateEmployeeRequest`, ADR-0016) : un gérant ne peut pas créer
un salon au nom d'un autre compte. À la création, `status=ACTIVE` et `opening_hours=NULL`.

**(b) `is_bookable` est une règle de domaine dérivée, jamais persistée** :
`is_bookable(status, opening_hours) = (status == ACTIVE) et bool(opening_hours)`. `bool({})` est faux —
un JSONB d'horaires **vide** (écrit plus tard par #16) ne rend pas un salon réservable par accident. Le
prédicat est exposé dans la réponse API et le dashboard ; **aucune** logique de réservation n'est
ajoutée (il n'existe encore aucune route de réservation à bloquer — #21+).

**(c) Médias par URL signée + table `salon_photos`** (migration `0003`, `down_revision="0002"`). Flux :
`POST /salons` → `POST /salons/{id}/media/upload-url` (URL signée `PUT`) → `PUT` navigateur→bucket →
`PUT /salons/{id}/logo` ou `POST /salons/{id}/photos` (`{ object_key }`). Toutes les routes médias
restent sous `/salons/{salon_id}/…`, donc couvertes par `require_salon_scope`. La **clé d'objet est
fabriquée par le serveur** (`salons/{salon_id}/{logo|photos}/{uuid4}.{ext}`) à partir d'UUID opaques,
**sans PII** ni nom de fichier client ; l'extension dérive du **MIME validé** (liste blanche
`image/jpeg|png|webp`). L'`object_key` soumis à l'attachement est **revalidé** contre le préfixe du
salon (règle de sécurité obligatoire : sans quoi l'isolation §11.2 serait contournable par les médias).

**(d) Le logo stocke une clé d'objet, pas une URL.** La colonne `salons.logo_url` est **renommée**
`logo_object_key` (migration `0003`, table vide ⇒ renommage sans risque). L'URL signée est calculée
**à la lecture** (`MediaStorage.presign_download`) : la persister serait un bug (elle expire). Une URL
signée est un **secret porteur** → jamais journalisée.

**(e) Garde composable `require_any_permission(*permissions)`** ajoutée à `security.py` : `403` si le
rôle n'en détient **aucune**. `GET /salons/{salon_id}` l'exige avec `SALON_READ_OWN` **ou**
`SALON_READ_ANY` (l'ADMIN a `_ANY`, pas `_OWN` — §4.1), **en plus** de `require_salon_scope`. Ce n'est
pas un contournement (la portée reste appliquée), seulement un « OU » de permissions, testé pour
lui-même.

**(f) Stockage objet agnostique du fournisseur** (ADR-0005). Adapter `S3MediaStorage` (boto3) configuré
par un `endpoint_url` explicite → MinIO en local (service ajouté à `deploy/docker-compose.yml`,
identifiants de **développement**) ou tout service S3-compatible en prod. Assemblé sur le patron du
`token_service` : si la config S3 est incomplète, `app.state.media_storage = None` et les routes médias
répondent **503**, **sans** casser `GET /health`, l'authentification ni **`POST /salons`** (créer un
salon sans logo reste possible — le critère d'acceptation ne dépend pas du stockage objet).

## Justification (compromis)

- **La création débloque mécaniquement la portée du gérant** (`salons.owner_id`) sans code
  supplémentaire : c'est ce qui fait passer `POST /salons/{id}/employees` (#13) de `403` à `201`.
- **L'URL signée + table dédiée** respecte l'ADR-0005 (bucket privé, accès signé, clés sans PII), garde
  toutes les routes médias sous portée salon, et n'impose aucun budget mémoire/latence à l'API.
- **`is_bookable` dérivé** évite une colonne qui pourrait diverger de l'état réel des horaires, et rend
  la règle §8.3 isolée et testable (table de vérité) sans anticiper la réservation (#21+).

## Conséquences

- **Positives** : premier salon créable et rattaché au gérant ; portée du gérant débloquée (M2–M5) ;
  règle §8.3 matérialisée (réponse API + bandeau dashboard) ; stockage médias conforme ADR-0005 et
  agnostique du fournisseur.
- **Négatives / limites** :
  - **objets orphelins** : un `presign_upload` suivi d'un téléversement mais **sans** appel
    `PUT /logo` / `POST /photos` laisse un objet non référencé — acceptable au MVP, à traiter par une
    **politique de cycle de vie du bucket** (hors périmètre) ;
  - **CORS du bucket** : le téléversement direct navigateur→bucket échoue si le bucket n'autorise pas
    l'origine du dashboard — **configuration d'infrastructure**, à documenter, pas du code ;
  - **résidence des données** (ADR-0011 : `europe-west4`) : si le bucket retenu vit ailleurs, c'est une
    **décision de résidence** à assumer explicitement (photos de salon : donnée peu sensible) ;
  - `boto3` est une **nouvelle dépendance** backend (passe par `pip-audit` / Dependabot / `osv-scanner`).
- **Non couvert (autres issues)** : configuration des horaires (#16), application de §8.3 à la
  réservation (#21+), prestations (#17), catalogue/consultation client (#18/#19), modification des
  informations du salon (#20), désactivation/suspension (M5/M6), plafonnement par plan d'abonnement
  (aucun modèle d'abonnement au MVP → **N salons sans limite**).
- **Suivis** : nettoyage des objets orphelins (politique de bucket) ; fournisseur de stockage de
  production (ADR-0005, toujours ouvert) ; configuration CORS du bucket par environnement.
