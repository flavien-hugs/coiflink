# ADR-0015 : Autorisation & RBAC — deny-by-default, permissions par rôle, isolation par salon

- **Statut** : Accepté
- **Date** : 2026-07-12
- **Décideurs** : équipe CoifLink
- **Issue** : #12 (Middleware d'autorisation & RBAC)
- **Référence PRD** : §4 / §4.1 (permissions par rôle), §11.2 (autorisation & isolation),
  §11.4 (journalisation), §18 (Sprint 1 — « Middleware permissions »)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0013](./0013-connexion-jwt-refresh-anti-bruteforce.md) (JWT/claims — **consommation** des
  claims côté serveur), [ADR-0003](./0003-backend-fastapi.md) (FastAPI, OpenAPI).

## Contexte et problème

Après #8/#9/#10/#11, le backend sait **authentifier** mais **n'autorise rien** : aucune route ne lit
l'en-tête `Authorization`, `JwtTokenService.decode()` n'est appelé qu'au rafraîchissement, et
**toutes** les routes montées sont publiques par construction. Le modèle de rôles du PRD §4.1
n'existe que comme énumération et comme claim `role` dans le JWT ; l'isolation multi-salons du
§11.2 n'est garantie qu'**en base** (FK composites `(salon_id, id)`), pas au niveau applicatif.

Sans couche d'autorisation commune, chaque issue métier (#13, #15, #21, #28…) réinventerait ses
contrôles d'accès — avec un risque élevé d'oubli et de **fuite inter-salons**. Il faut donc trancher,
**avant d'exposer la moindre ressource métier** : où vit la décision d'accès, comment une route
devient protégée, et qui fait autorité sur le rôle.

## Options envisagées

- **Option A — Middleware ASGI** (Starlette `BaseHTTPMiddleware`) qui inspecte le chemin et rejette.
  Simple à « brancher partout », mais : la décision vit **hors** du système de dépendances (donc
  non surchargeable en test), le middleware ne connaît pas les paramètres de chemin typés
  (`salon_id`), et **rien n'apparaît dans OpenAPI**.
- **Option B — [retenue] Dépendances FastAPI** : une dépendance **globale**
  (`FastAPI(dependencies=[...])`) pour le deny-by-default, et des **gardes de route** composables
  (`get_current_principal`, `require_roles`, `require_permission`, `require_salon_scope`).
- **Option C — Contrôles ad hoc dans chaque handler.** Écarté : c'est exactement le risque d'oubli
  que l'issue #12 existe pour supprimer.

## Décision

Nous adoptons l'**option B**, avec cinq décisions structurantes.

**(a) L'autorisation est appliquée par des dépendances FastAPI**, pas par un middleware ASGI :
testable, injectable (`app.dependency_overrides`), typée (le `salon_id` du chemin est déjà converti
en `uuid.UUID`), et **documentée dans OpenAPI** (bouton « Authorize » via `HTTPBearer`).

**(b) Deny-by-default par liste blanche explicite.** `require_authenticated` est une dépendance
**globale** ; une route n'est publique que si son chemin figure dans
`security.PUBLIC_ROUTE_PATHS` (`/health`, `/auth/register*`, `/auth/login`, `/auth/refresh`,
`/auth/password/reset/*`). Une route ajoutée demain sans rien déclarer est **fermée**, pas ouverte.
L'invariant est **exécutable** : un test énumère les routes de l'application et échoue si l'une
n'est ni publique-listée ni porteuse d'une garde de `Principal`.

**(c) Le JWT n'est pas une source d'autorité sur le rôle.** Le claim `role` est **informatif** ; le
rôle et le statut qui autorisent sont **relus en base à chaque requête protégée**
(`get_current_principal`). Une rétrogradation ou une suspension prend donc effet **immédiatement**,
sans attendre l'expiration du jeton d'accès (15 min). Corollaire : `verify_access` exige
`type == "access"` — un *refresh token* (TTL 30 j) ne peut **jamais** ouvrir une ressource protégée.

**(d) Codes HTTP et messages.** `401` (non authentifié : jeton absent, invalide, expiré, de mauvais
type, compte introuvable) + `WWW-Authenticate: Bearer` ; `403` (rôle insuffisant, permission absente,
**accès inter-salons**, compte non `ACTIVE`) ; `503` (`JWT_SECRET` non configuré — cohérent avec
`/auth/login`). Les messages sont **constants et génériques** : le `403` d'un accès inter-salons est
**identique** à celui d'un rôle insuffisant, et ne nomme jamais le salon visé.

> **`403` plutôt que `404` sur l'accès inter-salons.** Un `404` masquerait l'*existence* de la
> ressource d'autrui (anti-oracle), mais complexifie chaque handler. Le risque résiduel du `403` est
> faible : les `salon_id` sont des **UUID** (non énumérables). Choix **uniforme** — toutes les issues
> suivantes doivent l'appliquer.

**(e) Portée du coiffeur dérivée des rendez-vous assignés.** Le schéma n'a **pas** de table
d'appartenance employé↔salon (elle appartient à #13). En attendant, `SqlSalonScopeRepository` dérive
la portée d'un `HAIRDRESSER` de `DISTINCT appointments.salon_id WHERE hairdresser_id = …` — lecture
littérale du §11.2 (« son planning ou les rendez-vous qui lui sont assignés »), **sans migration**.
La portée d'un `MANAGER` vient de `salons.owner_id` (rattachement réel, déjà en base).

La matrice §4.1 vit dans le **domaine** (`domain/permissions.py`), pure et **fermée** : un rôle absent
de la table n'a **aucune** permission, et l'`ADMIN` **n'est pas un joker implicite** — ses permissions
de supervision sont listées comme celles des autres rôles, donc auditables.

## Justification (compromis)

- **La décision vit dans le domaine, l'application l'orchestre, l'adapter la traduit** (ADR-0008) :
  les règles §4.1/§11.2 sont testables **sans base ni HTTP**, et une route métier ne réimplémente
  jamais un contrôle d'accès — elle déclare une garde.
- **L'invariant deny-by-default est vérifié par une machine, pas par une revue** : c'est la seule
  garantie qui résiste à l'ajout distrait d'une route par une issue ultérieure.
- **Coût de la relecture en base** : une lecture indexée `users` par clé primaire par requête
  protégée (et une requête `salons.owner_id` pour les routes à portée salon). Négligeable devant le
  budget §12.1 (API < 3 s) — et le prix d'une révocation **immédiate**, que des claims figés dans un
  jeton de 15 min ne peuvent pas offrir.
- **Compromis assumé** : hors `/auth/me`, les gardes n'ont pas encore de consommateur de production
  (les ressources métier arrivent en #15+). C'est la raison d'être d'une issue « middleware » qui
  **précède** les ressources ; le risque d'API spéculative est mitigé par des tests unitaires et API
  complets.

## Conséquences

- **Positives** : toute route future est protégée par défaut ; l'isolation inter-salons est appliquée
  **côté serveur** en un point unique (`AccessPolicy.require_salon`), jamais dérivée d'un paramètre
  client ; le contrat HTTP (`401`/`403`/`503`, `GET /auth/me`) est stable pour le dashboard (#14) et
  l'app mobile ; aucune migration, **aucun nouveau secret** ni variable d'environnement.
- **Négatives / limites** :
  - un **coiffeur sans aucun RDV assigné** a une portée **vide** : il ne voit rien. Sûr
    (deny-by-default), mais insuffisant à terme — **plan de sortie** : quand #13 livrera la table
    d'appartenance, **seule** la requête de `SqlSalonScopeRepository` change ; le port et les gardes
    restent identiques ;
  - `salons.owner_id` n'a **pas** d'index explicite. La colonne devient un chemin chaud avec
    `require_salon_scope`. Volumétrie MVP faible → impact marginal ; **suivi** : ajouter
    `ix_salons_owner_id` avec la première migration de #15 (création de salon) ;
  - une route montée **hors** du système de dépendances (`app.add_route`, sous-application ASGI)
    échapperait à la garde globale. Le test d'invariant échoue explicitement sur ce cas.
- **Suivis** :
  - **table d'appartenance employé↔salon** → **#13** (remplace la portée dérivée des RDV) ;
  - **invalidation des jetons déjà émis après un *reset* de mot de passe** → reste **ouverte**
    (suivi [ADR-0014](./0014-reinitialisation-mot-de-passe-otp.md) : `password_changed_at` /
    `token_version`). La relecture du statut en base couvre désormais la **suspension** d'un compte,
    **pas** le changement de mot de passe. `get_current_principal` est le point d'accroche naturel
    (comparer `claims.iat` à `password_changed_at`) ;
  - **journalisation d'audit des accès sensibles** (PRD §11.4) → **#52**. #12 ne journalise **aucun**
    jeton, mot de passe, téléphone, e-mail ni nom ;
  - **aucun chemin de création d'un compte `ADMIN`** n'existe (l'inscription fixe `CLIENT` ou
    `MANAGER` côté serveur) : les gardes `ADMIN` sont testables mais inatteignables en production
    tant qu'une procédure d'amorçage n'existe pas → à traiter comme une issue d'exploitation.
