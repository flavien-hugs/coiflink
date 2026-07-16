# ADR-0019 : Journalisation d'audit §11.4 (table persistée) & gestion des prestations

- **Statut** : Accepté
- **Date** : 2026-07-16
- **Décideurs** : équipe CoifLink
- **Issue** : #17 (US-2.3 — Ajout & gestion des prestations)
- **Référence PRD** : §6 (Épic 2, US-2.3), §4.1 (permissions `SERVICE_MANAGE` / `SERVICE_READ`), §7
  (« Ajouter / Modifier / **Désactiver** une prestation »), §9.3 (table `services`), §11.2 (isolation
  par salon), §11.3 (journalisation des accès sensibles, non-fuite PII), §11.4 (liste des actions
  journalisées), §12 (budget latence/stockage)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal — validation dans le
  domaine, ports/adapters), [ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md) (ORM + Alembic),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default),
  [ADR-0017](./0017-creation-salon-medias-et-reservabilite.md) (isolation par salon, FK composites)

## Contexte et problème

La tranche salon est livrée (#15/#16). La table `services` existe déjà au schéma (§9.3, migration
`0001`) avec tous les champs de US-2.3 (`name`, `description`, `price`, `duration_minutes`, `category`,
`is_active`) et ses contraintes (`CHECK price >= 0`, `CHECK duration_minutes > 0`), mais **aucune
route, cas d'usage ni dépôt** ne permet de gérer les prestations. Les permissions `SERVICE_MANAGE` /
`SERVICE_READ` (§4.1) ne sont câblées sur aucune route.

US-2.3 exige : **(1)** CRUD des prestations **par salon** ; **(2)** durée et prix **obligatoires** ;
**(3)** **modification journalisée (§11.4)**. Le troisième critère est le point réellement nouveau :
**aucune infrastructure de journalisation §11.4 n'existe** dans le dépôt. #17 est la première issue
dont un critère l'exige — il faut donc **établir le mécanisme**, réutilisable par les actions §11.4
suivantes (modification RDV, paiement, correction de caisse, désactivation salon).

Deux écarts à trancher : (a) « suppression » (issue) vs « désactiver » (PRD §7) alors que la FK
`appointment_services → services` est `ON DELETE RESTRICT` ; (b) journal §11.4 **persisté** vs **log
structuré éphémère**.

## Décision

1. **Tranche verticale hexagonale des prestations** calquée sur #15/#16 : `domain/service.py` (pur —
   entités + validation `validate_price`/`validate_duration`/`validate_service_name`/
   `normalize_category`), `application/services.py` (cas d'usage dépendant **uniquement** de ports),
   `adapters/inbound/services.py` (router), `adapters/outbound/persistence/service_repository.py`
   (SQLAlchemy). **Aucune migration `services`** (table déjà au schéma).

2. **Validation dans le domaine pur** (ADR-0008), les `CHECK` SQL restant un filet de sécurité : prix
   **requis**, `>= 0`, ≤ `NUMERIC(12,2)`, au plus 2 décimales ; durée **requise**, entière `> 0`,
   ≤ 24 h ; nom non vide ≤ 255 ; catégorie **libre** bornée ≤ 128 (pas d'énumération figée au MVP).

3. **Routes imbriquées & protégées** sous `/salons/{salon_id}/services` pour hériter de
   `require_salon_scope` (isolation §11.2, `403` générique hors périmètre). Mutations
   (`POST`/`PUT`/`DELETE`) gardées par `require_permission(SERVICE_MANAGE)` ; lectures (`GET`) par
   `require_permission(SERVICE_READ)`. **Aucune** route publique, **aucun** ajout à
   `PUBLIC_ROUTE_PATHS`, **aucune** permission nouvelle. `PUT` a une sémantique **replace** (prix/durée
   restent requis) ; le dépôt filtre systématiquement sur le couple `(salon_id, id)`.

4. **« Suppression » = désactivation (soft-delete)** : `DELETE …/services/{id}` passe `is_active=false`
   (et non une suppression physique). Motif : la FK `RESTRICT` interdit de supprimer une prestation
   déjà réservée, et la désactivation préserve l'historique (`price_at_booking` des RDV passés) et
   correspond au PRD §7. Une réactivation (`is_active=true`) est possible et journalisée.

5. **Journal §11.4 : table persistée** (`audit_logs`), et non un log éphémère. Une table est durable,
   requêtable et sert de socle à la supervision (§11.3) et aux actions §11.4 suivantes. Le vocabulaire
   vit dans le **domaine** (`domain/audit.py` : `AuditAction` fermé, `AuditEntry` neutre) ; l'écriture
   est un **port** (`application/ports/audit_log.py`) implémenté par `SqlAuditLog`. Chaque mutation
   (create/update/deactivate/reactivate) journalise ; la **modification** l'exige, les autres l'ont
   pour une traçabilité cohérente. `metadata` ne porte que la **liste des champs modifiés**
   (`{"changed": [...]}`), jamais les valeurs.

6. **Atomicité même-`Session`** : l'entrée d'audit est écrite dans la **même unité de travail** que la
   mutation métier (`flush()` sans `commit()`, commit/rollback piloté par `get_session`, patron
   `CreateEmployee` #13). Pas d'audit « fantôme » sur un métier rollbacké, ni de mutation sans trace.

7. **Non-fuite (invariant §11.3/§11.4)** : aucune ligne d'audit ne porte de secret ni de PII —
   `actor_user_id` est un UUID **opaque**, `metadata` est neutre. FK `actor_user_id`/`salon_id` en
   `ON DELETE RESTRICT` : le journal ne perd pas ses lignes quand un compte/salon disparaît.

## Conséquences

- **Nouvelle table `audit_logs`** (modèle ORM `models.AuditLog` — source de vérité — + migration
  `0004_audit_logs.py`, `down_revision = "0003"`, `downgrade()` réversible). Table neuve, aucune donnée
  à migrer. L'attribut ORM est nommé `event_metadata` (le nom `metadata` étant réservé par SQLAlchemy)
  mais la **colonne SQL** reste `metadata`.
- **Mécanisme réutilisable, câblé uniquement sur les prestations dans #17** : les actions §11.4 futures
  ajouteront leurs valeurs à `AuditAction` et réutiliseront le port sans ré-architecturer. La
  **consultation** du journal (route de lecture, écran de supervision) relève de M5/M6 — **hors
  périmètre** ici.
- **Parité front/back** : un validateur TypeScript miroir (`web-dashboard/src/domain/service`) reproduit
  les règles prix/durée/nom pour l'UX ; le **backend reste l'autorité**. Risque de divergence mitigé
  par des tests de parité. La section **Prestations** du dashboard passe de `coming-soon` à
  `available`.
- **Limites assumées** : pas de suppression physique au MVP (désactivation uniquement) ; `metadata`
  minimal (pas de diff avant/après) ; catégorie libre (pas d'énumération) ; le dashboard suppose 0 ou 1
  salon (héritage #15). La **consultation client / catalogue public** (#18/#19) et la **réservation**
  (#21+) restent hors périmètre.
