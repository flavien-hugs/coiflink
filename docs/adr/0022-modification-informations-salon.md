# ADR-0022 : Modification des informations du salon — réutilisation du chemin d'écriture #15 & garantie de réflexion côté client sans cache

- **Statut** : Accepté
- **Date** : 2026-07-20
- **Décideurs** : équipe CoifLink
- **Issue** : #20 (US-2.5 — Modification des informations du salon)
- **Référence PRD** : §6 (US-2.5, critère : « Le gérant met à jour son salon ; les changements sont
  reflétés côté client »), §8.3 (visibilité : un salon inactif n'est jamais visible côté client),
  §11.2/§11.3/§11.4 (isolation, PII, audit)
- **S'appuie sur** : [ADR-0017](./0017-creation-salon-medias-et-reservabilite.md) (création de salon,
  `owner_id` imposé serveur), [ADR-0020](./0020-catalogue-salons-cote-client.md) et
  [ADR-0021](./0021-consultation-salon-cote-client.md) (catalogue/fiche `ACTIVE`-only, projection de
  vitrine), [ADR-0019](./0019-journalisation-audit-et-prestations.md) (journal d'audit §11.4),
  [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal), [ADR-0004](./0004-donnees-postgresql-redis.md)
  (Redis, câblé ultérieurement)

## Contexte et problème

Un gérant doit pouvoir **modifier à tout moment** les informations générales de son salon (nom,
description, téléphone, adresse, ville, commune, coordonnées GPS) et ces changements doivent
**apparaître côté client** (catalogue #18 / fiche #19) sans étape manuelle.

Le **chemin d'écriture est déjà livré** avec la tranche #15 : `PUT /salons/{salon_id}` →
cas d'usage `UpdateSalon` → journal `SALON_UPDATED`, avec le BFF Next.js et l'UI d'édition
correspondants. Le point non prouvé de #20 était le **second membre du critère** — la réflexion côté
client — vraie « par construction » (le catalogue et la fiche relisent les **mêmes lignes** de la
table `salons`, sans couche de cache) mais **couverte par aucun test bout-en-bout**.

## Décision

1. **Réutiliser** le chemin d'écriture existant `PUT /salons/{salon_id}` (sémantique *replace*,
   `name` requis) — **aucune ré-implémentation**. La route reste gardée par
   `require_permission(SALON_UPDATE)` **et** `require_salon_scope` (isolation §11.2 → `403` générique
   hors périmètre) et journalise `SALON_UPDATED` avec un diff **neutre** (`metadata.changed` = noms de
   champs uniquement, jamais de valeurs/PII, §11.4), de façon **atomique** avec la mutation.

2. **Champs non éditables conservés** : `owner_id`, `status` et `opening_hours` n'apparaissent pas
   dans `UpdateSalonRequest` — un corps qui les contient est **ignoré** (anti-élévation de privilège,
   miroir de la création #15). Le changement de statut et les horaires ont leurs propres chemins
   (#16), les médias les leurs (#15).

3. **Garantie de réflexion sans cache** : le catalogue (`GET /catalog/salons`, #18) et la fiche
   (`GET /catalog/salons/{salon_id}`, #19) projettent les mêmes lignes `salons` **à la lecture** ; une
   modification est donc reflétée **à la prochaine lecture**. Aucune invalidation n'est requise tant
   qu'aucun cache (Redis/CDN) n'est câblé devant `/catalog`.

4. **Verrou de non-régression par test e2e** (`backend/tests/test_salon_update_e2e.py`) : après un
   `PUT /salons/{id}` réussi, les nouvelles valeurs apparaissent en liste/recherche **et** en fiche ;
   la projection publique n'expose jamais `owner_id`/`status`/clé d'objet brute ; l'audit
   `SALON_UPDATED` est neutre ; un salon non `ACTIVE` reste **absent** du catalogue et sa fiche renvoie
   **404** (§8.3, la réflexion n'ouvre pas de fuite de visibilité) ; l'isolation inter-gérants renvoie
   `403`.

5. **Fraîcheur `updated_at`** : la colonne `salons.updated_at` n'a pas d'`onupdate` au niveau ORM
   (seulement `server_default = now()`). `SqlSalonRepository.update` **bump désormais explicitement**
   `updated_at = func.now()` au flush, pour que la modification soit observable. C'est **le seul
   correctif de code produit** de #20 ; il n'implique **aucune migration** (comportement ORM au flush).

**Aucune migration Alembic, aucune nouvelle surface d'API ni de schéma.** L'action `SALON_UPDATED` et
la table `audit_logs` existaient déjà (#17/ADR-0019).

## Conséquences

- **Positives** : le critère « reflété côté client » est **verrouillé par des tests** (garde-fou si un
  cache/dénormalisation est introduit plus tard) ; les invariants de sécurité (isolation, champs non
  éditables, audit neutre, projection sans donnée de gestion, §8.3) sont réassertés bout-en-bout ;
  `updated_at` devient une donnée de fraîcheur fiable.
- **Négatives / suivis** : concurrence multi-éditeurs en **last-write-wins** (pas de verrouillage
  optimiste `If-Match`/`version`) — acceptable au MVP (un seul `owner` édite), **différé** ;
  **invalidation de cache** à prévoir **le jour où** Redis/CDN est placé devant `/catalog` (le test
  e2e signalera la régression) ; aucune preuve automatisée côté Flutter (la réflexion suppose un
  re-fetch à l'affichage des écrans #18/#19, sans changement de code mobile).
