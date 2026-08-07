# CoifLink

> **Plateforme digitale de gestion pour salons de coiffure.**
> Marché cible : Afrique de l'Ouest, priorité Côte d'Ivoire. Produit SaaS métier.
> Plateformes : application mobile client · interface web salon · interface admin.

CoifLink ambitionne de devenir la plateforme de référence pour la digitalisation des salons de
coiffure en Afrique de l'Ouest. Les salons y gèrent **rendez-vous, clients, prestations,
encaissements, employés et statistiques** depuis une interface simple ; les clients y **trouvent un
salon, consultent les disponibilités, réservent et reçoivent des rappels** pour réduire l'attente.

Ce dépôt est actuellement à l'état **greenfield** : le produit est entièrement spécifié (PRD),
découpé en backlog livrable et outillé pour une livraison agentique (pipeline ADW). Le code
applicatif sera produit issue par issue à partir du backlog.

📄 Spécification complète : **[prd-coiflink.md](./prd-coiflink.md)** · Backlog livrable : **[BACKLOG.md](./BACKLOG.md)**

---

## 1. Le problème

De nombreux salons fonctionnent encore au carnet papier / WhatsApp / appels : rendez-vous mal
organisés, files d'attente imprévisibles, clients oubliés, écarts de caisse, aucun historique
client, faible visibilité sur les revenus. CoifLink centralise la gestion du salon dans une solution
numérique simple, rapide et adaptée au terrain.

## 2. Utilisateurs

| Rôle | Description | Ce qu'il fait |
| --- | --- | --- |
| **Client** | Utilisateur final | Réserve, modifie, annule, consulte son historique, reçoit des rappels |
| **Gérant** | Responsable du salon | Gère salon, employés, prestations, rendez-vous, caisse, statistiques |
| **Coiffeur** | Employé (optionnel au MVP) | Voit son planning, confirme les prestations, met à jour les statuts |
| **Admin CoifLink** | Super-administrateur plateforme | Supervise salons, support, abonnements, KPI globaux |

## 3. Périmètre du MVP

7 modules (cf. PRD §3) :

1. **Authentification & autorisation** — comptes client/gérant/employé, connexion JWT, rôles.
   Le **RBAC est livré** (#12) : API **fermée par défaut**, permissions par rôle (PRD §4.1) et
   **isolation par salon** (§11.2 — un gérant ne voit que son salon, un coiffeur que son planning, un
   client que ses RDV) — voir [ADR-0015](./docs/adr/0015-autorisation-rbac-deny-by-default.md).
   La **création de comptes employés (coiffeurs)** par un gérant est livrée (#13) :
   `POST /salons/{salon_id}/employees` rattache le coiffeur au salon (table d'appartenance), qui se
   connecte ensuite avec un **périmètre restreint** — voir
   [ADR-0016](./docs/adr/0016-comptes-employes-appartenance-salon.md).
   Le **shell du dashboard gérant** est livré (#14) : zone protégée `/gerant` (layout, navigation 7
   sections §7.2, garde `deny-by-default` — cookie `httpOnly` + BFF + vérification `GET /auth/me`
   côté serveur) — voir [`web-dashboard/README.md`](./web-dashboard/README.md).
2. **Gestion des salons** — salon, horaires, prestations
3. **Rendez-vous** — réservation, statuts, planning, anti double-réservation
4. **Gestion clients** — fiches, historique
5. **Encaissement** — paiements, journal de caisse, reçu numérique client
6. **Tableau de bord** — KPI gérant et admin
7. **Notifications** — confirmation, rappel, annulation

Hors MVP (V2+) : Mobile Money automatisé, borne intelligente, IA de recommandation, gestion de
stock, multi-salons avancé, fidélité (cf. PRD §16, §21).

## 4. Architecture & stack

Stack **figée par les ADR** (`docs/adr/` — source de vérité, voir l'[index](./docs/adr/README.md)),
issue de la recommandation du PRD (§10) tranchée par l'issue #1. Le tableau ci-dessous est un résumé ;
chaque décision et son compromis sont détaillés dans l'ADR lié.

| Couche | Décision | ADR |
| --- | --- | --- |
| Mobile client | Flutter (Android prioritaire) | [0001](./docs/adr/0001-app-mobile-flutter.md) |
| Web gérant / admin | Next.js (React, TypeScript) | [0002](./docs/adr/0002-web-gerant-admin-nextjs.md) |
| Backend | Python FastAPI · API REST · JWT · jobs async | [0003](./docs/adr/0003-backend-fastapi.md) |
| Autorisation | RBAC **deny-by-default** · permissions par rôle (§4.1) · isolation par salon (§11.2) | [0015](./docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Base de données | PostgreSQL + Redis (cache/queue) | [0004](./docs/adr/0004-donnees-postgresql-redis.md) |
| Fichiers | Stockage objet S3-compatible | [0005](./docs/adr/0005-stockage-objet-s3-compatible.md) |
| Notifications | Firebase Cloud Messaging + SMS (WhatsApp en V2) | [0006](./docs/adr/0006-notifications-fcm-sms.md) |
| Déploiement | Docker · CI/CD GitHub Actions · **Railway** (hébergement, environnements, secrets, sauvegardes) | [0010](./docs/adr/0010-ci-cd-docker-packaging.md) (CI/CD + Docker, #4) · [0011](./docs/adr/0011-deploiement-environnements-secrets.md) (hébergement/région, secrets, sauvegardes, #5) |

**Versions de référence** (figées par #2 — voir [ADR-0007](./docs/adr/0007-arborescence-monorepo-versions.md)) :
Flutter **stable** / Dart **^3.12**, Node **≥ 20 (LTS)**, Python **≥ 3.12**. **PostgreSQL 16** est figée
par #3 (schéma de données initial — voir [ADR-0009](./docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)) ;
Redis **7** pour mémo (runtime, câblé ultérieurement). Le `web-dashboard/` est **une seule application
Next.js** à zones protégées par rôle (`/gerant`, `/admin`).

## 5. Structure du dépôt

```
coiflink/
├── prd-coiflink.md            # PRD — source de vérité produit
├── BACKLOG.md                 # 55 issues (M0–M6) dérivées du PRD
├── README.md                  # ce fichier
├── LICENSE                    # licence propriétaire (Tous droits réservés)
├── CONTRIBUTING.md            # conventions de commits & de contribution
├── app-mobile/                # application mobile client (Flutter — ADR-0001)
├── web-dashboard/             # interface web gérant / admin (Next.js — ADR-0002)
├── backend/                   # API backend (FastAPI — ADR-0003)
├── deploy/                    # topologie non secrète : docker-compose + config Railway (#5)
├── docs/adr/                  # Architecture Decision Records (stack & socle)
├── docs/environnements-et-secrets.md  # environnements, politique de secrets, sauvegardes (#5)
├── docs/guides/               # guides utilisateur (gérant & client) — parcours Must (#53)
├── specs/                     # specs de planification du pipeline ADW
├── adw_sdlc/                  # pipeline ADW (control plane TypeScript) — voir adw_sdlc/README.md
├── adw/                       # contrat d'état inter-langage (state.schema.json + fixtures)
├── .claude/commands/          # prompts de phases (runner claude)
├── .pi/prompts/               # prompts de phases (runners pi/codex/opencode)
├── .github/workflows/         # CI du pipeline (adw-sdlc.yml)
└── scripts/
    ├── run-issue.sh           # wrapper : lance le pipeline sur une issue
    ├── create-backlog-issues.sh  # pousse BACKLOG.md en issues GitHub
    └── adw.env.example        # gabarit de config locale (à copier en adw.env, gitignoré)
```

Licence : **[LICENSE](./LICENSE)** (propriétaire). Conventions de contribution & de commits :
**[CONTRIBUTING.md](./CONTRIBUTING.md)**.

### Build & test par paquet

Chaque paquet expose une commande de **build** et de **test** réelle (squelette runnable, sans
fonctionnalité métier) ; voir le `README.md` du paquet pour les prérequis et le détail.

| Paquet | Stack (ADR) | Build | Test |
| --- | --- | --- | --- |
| [`app-mobile/`](./app-mobile/README.md) | Flutter ([0001](./docs/adr/0001-app-mobile-flutter.md)) | `flutter build apk` | `flutter test` |
| [`web-dashboard/`](./web-dashboard/README.md) | Next.js ([0002](./docs/adr/0002-web-gerant-admin-nextjs.md)) | `npm run build` | `npm test` |
| [`backend/`](./backend/README.md) | FastAPI ([0003](./docs/adr/0003-backend-fastapi.md)) | `pip install -e .` | `pytest` |

> Le **test gate** agrégé du pipeline (`MX_AGENT_TEST_CMD`) est **câblé** (#6) sur
> [`scripts/test-gate.sh`](./scripts/test-gate.sh), qui enchaîne ces mêmes commandes par paquet (parité
> CI). Stratégie et « quoi tourne où » : **[docs/strategie-de-tests.md](./docs/strategie-de-tests.md)**.

### CI applicative (#4)

Le workflow **[`.github/workflows/ci.yml`](./.github/workflows/ci.yml)** s'exécute **à chaque pull
request** (et sur `push` vers `main`), distinct de `adw-sdlc.yml` (control plane). Décisions tracées
dans **[ADR-0010](./docs/adr/0010-ci-cd-docker-packaging.md)**. Il exécute des **jobs séparés
mobile / web / backend** — lint + tests + build par paquet — plus un scan de dépendances et le build
des images Docker :

| Job | Contenu | Artefact produit |
| --- | --- | --- |
| `backend` | `ruff check` · `pytest` (unitaire + intégration **+ e2e des parcours critiques §5** (#50) **+ sécurité §11** (#51)) · round-trip Alembic contre **PostgreSQL 16** · `python -m build` | `backend-dist` (wheel + sdist) |
| `web` | `npm run lint` · `npm test` · `npm run build` (sortie **standalone**) | `web-dashboard-build` |
| `mobile` | `flutter analyze` · `flutter test` · `flutter build apk` | `app-mobile-apk` (APK Android) |
| `dependency-scan` | `pip-audit` · `npm audit` · `osv-scanner` (**informatif**, complété par Dependabot) | — |
| `docker-backend` | build de l'image `backend/Dockerfile` (**build-seul**) + smoke test `GET /health` | image `coiflink-backend:ci` |
| `docker-web` | build de l'image `web-dashboard/Dockerfile` (**build-seul**) + smoke test page d'accueil | image `coiflink-web:ci` |

- **CI verte obligatoire avant merge** : les **status checks requis** sont `backend`, `web`,
  `mobile`, `docker-backend`, `docker-web` (`dependency-scan` reste informatif). L'activation de la
  **protection de branche `main`** correspondante est un **réglage dépôt** (non versionné), à
  appliquer par un administrateur (cf. ADR-0010).
- **Images Docker** : construites en CI (**build-seul**) ; l'hébergement est **Railway**
  (**deploy-from-source** — **ADR-0011**) ; le **push vers un registre** reste différé (évolution
  optionnelle). Aucun secret n'entre en CI ni dans les images (config par variables d'environnement ;
  utilisateur non-root).
- **Mises à jour automatisées** : **[Dependabot](./.github/dependabot.yml)** (`pip`, `npm`, `pub`,
  `github-actions`).

### Environnements & secrets (#5)

Les environnements **dev / staging / prod**, la **politique de secrets** (inventaire, rotation,
conduite en cas de fuite, non-journalisation), le **runbook `staging` reproductible** et les
**sauvegardes** sont décrits dans **[docs/environnements-et-secrets.md](./docs/environnements-et-secrets.md)**
(décision de socle : **[ADR-0011](./docs/adr/0011-deploiement-environnements-secrets.md)** — Railway,
région `europe-west4`). **Aucun secret n'est committé** : les secrets réels vivent hors dépôt (magasin
de la plateforme / GitHub Environments), injectés par variables d'environnement. La topologie non
secrète (parité locale/staging) est versionnée sous **[`deploy/`](./deploy/)** :

```bash
cp deploy/.env.example deploy/.env      # gitignoré ; renseigner localement (aucun secret committé)
docker compose -f deploy/docker-compose.yml up --build   # backend + web + PostgreSQL 16 + Redis 7
```

---

## 6. Démarche — comment on est arrivé à cette étape

Le projet est construit selon un flux **spécification → backlog → issues → livraison agentique**.
Étapes franchies jusqu'ici :

1. **Rédaction du PRD** — [prd-coiflink.md](./prd-coiflink.md) : vision, personas, périmètre MVP,
   épics & user stories (§6), modèle de données (§9), architecture (§10), sécurité (§11), roadmap
   par sprints (§18), priorisation MoSCoW (§22).

2. **Dérivation du backlog** — [BACKLOG.md](./BACKLOG.md) : le PRD est réorganisé en **55 items
   livrables** regroupés en 7 jalons **M0–M6** (alignés sur les sprints 0–6). Règle de découpage :
   *1 issue par user story*, plus les items de socle (Sprint 0) et de durcissement (Sprint 6).
   Chaque item porte priorité (MoSCoW), effort (S/M/L), labels, **critères d'acceptation** (= la
   *definition of done*) et une ligne **« Dépend de #N »** dérivée des règles métier (§8) et des
   permissions (§11).

3. **Création des issues GitHub** — [scripts/create-backlog-issues.sh](./scripts/create-backlog-issues.sh)
   crée les **labels**, les **7 milestones** et les **issues #1–#55** dans l'ordre. Un garde-fou
   refuse de tourner si le dépôt n'est pas vierge, pour que les numéros GitHub correspondent
   exactement aux références « Dépend de #N » du backlog.

4. **Mise en place du pipeline ADW** — [adw_sdlc/](./adw_sdlc/) : control plane TypeScript qui
   conduit une issue à travers un cycle de vie phasé (`setup → classify → plan → implement → tests
   → resolve → e2e → review → patch → document → finalize → ci-fix → merge → report`).
   L'orchestrateur détient **tout git/gh** et retient les secrets de l'agent (`GH_TOKEN` jamais
   exposé). Détails : [adw_sdlc/README.md](./adw_sdlc/README.md) et [adw_sdlc/PLAN.md](./adw_sdlc/PLAN.md).

5. **Établissement du tronc** — la branche `main` est créée comme branche par défaut ; le pipeline
   forke ses branches de travail depuis `main` et y ouvre une PR par issue.

6. **Vérification** — outillage `adw_sdlc` au vert (typecheck, tests, garde de rétention des
   secrets) ; *dry-run* du pipeline validé sur l'issue #1.

Issues **M0** (#1–#6 — socle : ADR de stack, initialisation du dépôt, schéma de données, CI/CD,
environnements & secrets, stratégie de tests & test gate) et **M1** (#8–#14 — inscription gérant,
connexion JWT, OTP, RBAC deny-by-default, comptes employés, shell dashboard gérant) livrées par le
pipeline. **M2 en cours** : la **création d'un salon** (#15, `POST /salons`) est livrée — un gérant
crée un salon **rattaché à son compte** (nom, logo, description, téléphone, localisation, photos) et le
consulte depuis la section **Paramètres** du dashboard. La **configuration des horaires d'ouverture**
est livrée (#16, voir [ADR-0018](./docs/adr/0018-configuration-horaires-salon.md)) :
`PUT /salons/{id}/opening-hours` enregistre les horaires par jour, jours fermés, pauses et jours
exceptionnels ; le gérant les édite depuis **Paramètres**. Règle §8.3 : un salon **sans horaire n'est
pas réservable** (`is_bookable=false`) — **enregistrer des horaires valides rend le salon réservable**
(`is_bookable=true`). La **gestion des prestations** est livrée (#17, voir
[ADR-0019](./docs/adr/0019-journalisation-audit-et-prestations.md)) : le CRUD par salon
(`/salons/{id}/services`, durée et prix **obligatoires**) depuis la section **Prestations** du
dashboard, la « suppression » étant une **désactivation** (soft-delete). Les **modifications sont
journalisées** (§11.4) dans une table `audit_logs` — première matérialisation du mécanisme d'audit,
réutilisable par les actions §11.4 suivantes. Le **catalogue client** est livré (#18, voir
[ADR-0020](./docs/adr/0020-catalogue-salons-cote-client.md)) : `GET /catalog/salons` liste/recherche
les salons **`ACTIVE` uniquement** (§8.3 — un salon désactivé n'apparaît **jamais**), en **lecture
seule** et **sans authentification**, avec une projection de vitrine (nom, localisation, logo signé,
`is_bookable`) **sans** `owner_id` ni donnée de gestion ; côté application mobile, l'écran de
**recherche/liste** (§7.1) et la première couche réseau du paquet Flutter accompagnent cette route.
La **consultation d'un salon** est livrée (#19, voir
[ADR-0021](./docs/adr/0021-consultation-salon-cote-client.md)) :
`GET /catalog/salons/{salon_id}` renvoie la **fiche publique** d'un salon **`ACTIVE`** (§8.3 — 404
sinon, sans oracle d'existence) agrégeant sa localisation complète (`phone` compris), ses **horaires**
(#16), ses **prestations actives** avec prix et durée (#17), ses médias signés et l'indicateur
`is_bookable` — sans `owner_id`, `status` ni donnée de gestion ; côté application mobile, l'**écran de
fiche** (horaires, prestations, badge de disponibilité et **point d'entrée** de la réservation) et la
**navigation depuis la liste** accompagnent cette route. La **modification des informations du salon**
est livrée (#20, voir [ADR-0022](./docs/adr/0022-modification-informations-salon.md)) : le gérant met à
jour les informations générales de son salon (nom, description, téléphone, localisation) via
`PUT /salons/{id}` depuis la section **Paramètres** — modification **journalisée** (§11.4,
`SALON_UPDATED`, diff neutre) réutilisant le chemin d'écriture livré avec #15, `status`/`owner_id`/
`opening_hours` restant non éditables par cette route. Ces changements sont **reflétés côté client**
(catalogue #18 / fiche #19) **à la lecture suivante** — le catalogue relit les mêmes lignes `salons`,
sans cache — garantie **verrouillée par un test e2e** (`backend/tests/test_salon_update_e2e.py`, dont
la visibilité §8.3 : un salon désactivé reste absent du catalogue même après modification). Le
**moteur de disponibilité & l'anti double-réservation** sont livrés (#21, voir
[ADR-0023](./docs/adr/0023-moteur-disponibilite-anti-double-reservation.md)) :
`GET /catalog/salons/{salon_id}/availability` expose les créneaux **libres** (endpoint **public**,
exclut les passés, fuseau Africa/Abidjan UTC+0) ; `POST /salons/{salon_id}/appointments` crée le RDV
au statut **`PENDING`** (client `APPOINTMENT_BOOK`), lié à ≥ 1 prestation, avec une contrainte
d'**exclusion PostgreSQL** comme seule garantie anti double-réservation. Le **tunnel de réservation
client** est livré (#22, **M3 en cours**, voir [ADR-0024](./docs/adr/0024-reservation-cote-client.md))
: le bouton « Réserver » de la fiche salon ouvre désormais le parcours guidé (prestation → date →
créneau → commentaire → confirmation) consommant les endpoints #21 — sans modifier le backend. La
couche d'authentification cliente minimale (`POST /auth/login`, `TokenStore` en mémoire au MVP) est
livrée dans ce même périmètre ; statut initial **« En attente »** affiché depuis la réponse du `POST`.
L'historique « Mes rendez-vous », la modification et l'annulation côté client (#23/#24), le cycle de
statuts gérant (#25) et le planning salon/coiffeur (#26/#27) sont livrés — **M3 achevé**. **M4 est
amorcé** avec la **création d'une fiche client** (#28, voir
[ADR-0026](./docs/adr/0026-fiche-client-portee-salon.md)) : le gérant crée une fiche rattachée à son
salon (nom, téléphone optionnel normalisé E.164, genre optionnel, notes internes) via
`POST /salons/{salon_id}/customers` — permission `CUSTOMER_MANAGE`, **isolation par salon** (§11.2),
unicité du téléphone **dans le salon** garantie en base, création **journalisée** (§11.4/§11.3) sans
aucune PII au journal ; la section **Clients** du dashboard gérant est ouverte. **L'historique des
visites d'un client** (#29) est livré : `GET /salons/{salon_id}/customers/{customer_id}/appointments`
liste les RDV **terminés** (`COMPLETED`) de la fiche avec prestations nommées et montants figés
(`price_at_booking`, XOF), plus un résumé dérivé en lecture (nombre de visites, dernière visite,
total) — lecture salon-scopée et fiche-scopée, lien fiche ↔ compte encapsulé (anti-oracle ADR-0026),
rendu par la page de détail `/gerant/clients/{id}`. **L'historique de prestations côté client** (#30,
US-4.4) est livré : `GET /appointments/history` liste en lecture seule les RDV **terminés** (`COMPLETED`)
du client authentifié (filtre `CLIENT_HISTORY_STATUSES` forcé serveur, route d'**appartenance** sans
portée salon, `APPOINTMENT_READ_OWN`) avec leurs prestations et montants figés (`price_at_booking`,
FCFA) — du plus récent au plus ancien ; l'écran **« Mon historique »** de l'application mobile consomme
ce chemin, distinct de « Mes rendez-vous » (actifs). **Les prestations préférées d'un client** (#31,
US-4.3) sont livrées : `GET /salons/{salon_id}/customers/{customer_id}/stats` classe les prestations les
**plus fréquentes** de la fiche — nombre d'occurrences et montant cumulé (`price_at_booking` figé, XOF) —
de la plus à la moins fréquente, **dérivé en lecture** des mêmes visites `COMPLETED` que #29 (aucun
nouvel accès base), lecture salon-scopée et fiche-scopée (`CUSTOMER_MANAGE`, anti-oracle ADR-0026),
rendu par un panneau **« Prestations préférées »** sur la page `/gerant/clients/{id}`. **La note client
privée éditable** (#32, US-4.5) est livrée : `PUT /salons/{salon_id}/customers/{customer_id}/notes`
remplace la note interne d'une fiche existante (préférences, allergies, habitudes ; `null`/vide
**efface** la note) — permission `CUSTOMER_MANAGE`, **isolation par salon** (§11.2), édition
**journalisée** (`CUSTOMER_NOTE_UPDATED`, §11.4/§11.3) sans aucune PII au journal ; la note reste
**interne au salon**, jamais visible du client, et devient éditable via un panneau **« Note privée »**
sur la page `/gerant/clients/{id}`. **L'enregistrement d'un paiement** (#33, US-5.1) est livré :
`POST /salons/{salon_id}/payments` crée un paiement **`VALIDATED`** lié à un RDV/prestation, dont le
**montant est vérifié cohérent** avec la prestation liée (§5.3/§8.2 — somme des `price_at_booking` d'un
RDV, ou `Service.price` d'une prestation active ; égalité stricte, tout écart → `422` sans écriture),
inscrit au **journal de caisse** (ligne `PAYMENT`) et **journalisé** (`PAYMENT_RECORDED`, `metadata` vide,
§11.4) dans la même unité de travail — permission `PAYMENT_RECORD` (seul le gérant), **isolation par
salon** (§11.2). La section **Encaissements** du dashboard gérant est ouverte : montant **pré-rempli** au
prix de la prestation, mode de paiement et référence optionnelle. Le journal de caisse consultable et la
correction par ajustement (#34, US-5.3) sont livrés côté backend. **L'historique des transactions
filtrable** (#35, US-5.2) est livré : `GET /salons/{salon_id}/payments` liste les paiements du salon **du
plus récent au plus ancien**, paginé et **filtrable côté serveur** par **date, client, montant et mode de
paiement** (filtres combinés en `ET`, plage de dates en jour civil `Africa/Abidjan`) — permission
`CASH_JOURNAL_READ` (seul le gérant), **isolation par salon** (§11.2 ; un `client_id` étranger → liste
vide, sans oracle), **lecture seule** et **cohérente avec le journal de caisse** (même source de vérité
`payments` : montants, horodatages et auteurs concordent, un paiement corrigé apparaît `ADJUSTED`). La
section **Encaissements** du dashboard gérant enrichit le formulaire d'une vue **Historique** (barre de
filtres + liste read-only, filtrage serveur via `searchParams`). **La supervision agrégée des transactions**
(#37, US-5.6) est livrée côté backend : `GET /admin/transactions/summary` renvoie, **par salon**, des
**agrégats** de transactions (nombre de paiements, nombre de corrections, **montant net** encaissé et
devise) et l'identité métier du salon (id + nom), paginés et **filtrables par plage de dates** (jour civil
`Africa/Abidjan`) — permission `STATS_READ_PLATFORM` (**seul l'admin**), lecture **plateforme** (inter-salons,
sans `require_salon_scope`), **lecture seule** et **sans PII de paiement** (§11.3 : aucun `client_id`,
`reference`, `recorded_by` ni ligne de paiement). Le **montant net** dérive de la même source de vérité que
le journal de caisse (#34 : somme signée des lignes `cash_journal`, un paiement corrigé fait baisser le net).
Le **reçu numérique de paiement côté client** (#38, US-5.5) est livré côté backend : `GET /me/receipts` et
`GET /me/receipts/{payment_id}` renvoient au **client authentifié** ses reçus — **projection en lecture
seule** dérivée du paiement (#33 : montant, mode, statut, référence, horodatage, identité **publique** du
salon et prestations figées), **générée** et **récupérable** dès l'enregistrement — permission
`PAYMENT_READ_OWN` (**seul le client**), route d'**appartenance** sans portée salon (`client_id =
principal.id` imposé serveur ; reçu d'un tiers/inexistant → `404` neutre), **sans écriture, sans migration
ni PII tierce**. La **remise proactive** (push/SMS) reste différée en M5 (Épic 7, ADR-0006) : #38 **génère**
un reçu, il n'**envoie** rien (voir [ADR-0030](./docs/adr/0030-recu-numerique-remise-differee.md)).
**M5 est amorcé** avec le **tableau de bord gérant** (Épic 6). Le **décompte des RDV du jour par statut**
(#39, US-6.1) est livré : `GET /salons/{salon_id}/appointments/daily-summary` renvoie, pour un jour civil
`Africa/Abidjan`, le nombre de RDV par statut (calcul `GROUP BY status` en base, sans PII), rendu en tuiles
**Total/Confirmés/Annulés/Terminés/Absents** sur `/gerant` — première mise en service de la permission
`STATS_READ_SALON` (§4.1, **seul le `MANAGER`**). Le **chiffre d'affaires jour/semaine/mois** (#40, US-6.2)
est livré : `GET /salons/{salon_id}/revenue/summary` renvoie, pour une **date de référence**, le CA du salon
sur **trois périodes** (le **jour**, la **semaine** civile **lundi → dimanche** et le **mois** civil qui la
contiennent) — permission `STATS_READ_SALON` (**deuxième** consommateur) + portée salon (§11.2). Le CA dérive
du **montant net** du journal de caisse (#34 : somme signée des lignes `PAYMENT`/`ADJUSTMENT`, un paiement
corrigé le fait **baisser**) ; **« annulés exclus »** (§8.1) est vrai **par construction** (un RDV `CANCELLED`
n'a ni paiement ni ligne de journal). Calcul **en base** (`SUM` sur intervalle indexé), **sans écriture, sans
migration ni PII** (§11.3) — la réponse ne porte que des montants, des dates et la devise. Le dashboard
`/gerant` affiche les **tuiles CA Jour/Semaine/Mois** (FCFA) **sous** le décompte RDV du jour. Les
**prestations les plus demandées** (#41, US-6.3) sont livrées : `GET /salons/{salon_id}/service-demand`
renvoie les prestations du salon **classées par volume et par revenu** (deux ordres, mêmes entrées) —
permission `STATS_READ_SALON` (**troisième** consommateur) + portée salon (§11.2). Le classement dérive des
RDV **`COMPLETED`** : par prestation, le **volume** (nombre d'occurrences) et le **revenu** (somme des
`price_at_booking` figés, XOF) ; une grandeur **distincte** du CA #40 (journal de caisse net). Calcul **en
base** (`GROUP BY service_id`), **sans écriture, sans migration ni PII** — la réponse ne porte que des
libellés de prestation, des compteurs, des montants et la période. Le dashboard `/gerant` ajoute un panneau
**« Prestations les plus demandées »** (bascule Volume/Revenu) **sous** les tuiles CA. Les **clients actifs**
(#42, US-6.4) sont livrés : `GET /salons/{salon_id}/active-clients` **segmente les clients du salon** sur une
période (défaut = mois civil courant) en **trois compteurs** — **nouveaux** (première visite sur la période),
**récurrents** (vus dans la période **et** avant) et **inactifs** (vus avant, silencieux sur la période) —
permission `STATS_READ_SALON` (**quatrième** consommateur) + portée salon (§11.2). La segmentation dérive des
**comptes** ayant des RDV **`COMPLETED`** (une « visite », #29 ; une fiche walk-in sans compte ne pèse pas) ;
calcul **en base** (`GROUP BY client_id`, `client_id` **jamais émis**), **sans écriture, sans migration ni
PII** — la réponse ne porte que des compteurs et des dates. Le dashboard `/gerant` ajoute un panneau
**« Clients actifs »** (Nouveaux/Récurrents/Inactifs) **sous** les prestations les plus demandées. La
**performance des coiffeurs** (#43, US-6.5) est livrée : `GET /salons/{salon_id}/hairdresser-performance`
renvoie, pour une période (défaut = mois civil courant), **une ligne par coiffeur** assigné à ≥ 1 RDV du
salon — **prestations réalisées** (occurrences des RDV `COMPLETED`), **CA généré** et **taux d'annulation**
(RDV `CANCELLED` / RDV assignés) — permission `STATS_READ_SALON` (**cinquième** consommateur) + portée salon
(§11.2). Chaque indicateur est **cohérent avec son autorité** (critère d'acceptation) : prestations & taux
dérivent **du planning** (`appointments` assignés), le CA dérive **de la caisse** (net `cash_journal`
**attribué** via `payments → appointments.hairdresser_id`, net des corrections #34). Calcul **en base**
(deux `GROUP BY hairdresser_id`), **sans écriture, sans migration** ; c'est le **seul** KPI stats
**nominatif** — il émet le nom d'affichage de l'employé (`users.full_name`, convention #34), **jamais** son
contact ni aucune PII client (§11.3, voir
[ADR-0031](./docs/adr/0031-performance-des-coiffeurs.md)). Le dashboard `/gerant` ajoute un panneau
**« Performance des coiffeurs »** (une ligne par coiffeur) **sous** les clients actifs. Les **KPI
globaux de la plateforme** (#44, US-6.6) sont livrés côté backend : `GET /admin/kpis` renvoie un
**instantané unique** (non paginé) de **scalaires globaux consolidés** sur toute la plateforme —
**salons inscrits** (`salons_total`) et **actifs** (`salons_active`), **clients inscrits**
(`clients_total`, comptes `CLIENT` uniquement), **rendez-vous** (`appointments_total` = **volume créé,
tous statuts** ; `appointments_this_month` = RDV du mois civil courant sur `appointment_date`) et
**revenus plateforme** (`revenue_total` + `revenue_this_month`) — permission `STATS_READ_PLATFORM`
(**deuxième** consommateur après #37, **seul l'admin**), lecture **plateforme** (inter-entités, sans
`require_salon_scope`). Le **revenu** dérive de la même source de vérité que le journal de caisse (#34 :
somme signée des lignes `cash_journal`, un paiement corrigé fait baisser le net) — c'est le **flux net
encaissé par les salons**, **pas** un revenu d'abonnement. La fenêtre mensuelle réutilise
`month_bounds` (#40) ; `reference_date` optionnel (défaut = jour courant `Africa/Abidjan`). Calcul **en
base** (`COUNT`/`SUM`, garde de coût §12.1), **sans écriture, sans migration ni audit** ; **non-PII
renforcée** (§11.3) — la réponse ne porte que des scalaires globaux, **aucune** identité d'entité (ni
`salon_id`, `salon_name`, `client_id`, `owner_id`), contrairement à #37. Le **KPI « abonnements »** du
backlog est **volontairement absent** : aucun modèle de données d'abonnement/facturation n'existe (épic
distinct, hors M5) — aucun nombre n'est inventé, `salons_active` couvre le besoin au libellé près (voir
[ADR-0032](./docs/adr/0032-kpi-globaux-plateforme-admin.md)). La zone web `/admin` n'existe pas encore
(livraison **backend-first**, comme #37). La **notification de confirmation de RDV** (#45, US-7.1) est
livrée côté backend : à la **création d'un RDV** (`POST /salons/{salon_id}/appointments`, #21), une
confirmation `CONFIRMATION` est **émise/tracée** dans la table `notifications` (`user_id` client,
`salon_id`, `appointment_id`, canal résolu « selon disponibilité », `status=PENDING`) **dans la même
unité de travail** que la réservation — première écriture applicative dans `notifications`, satisfaisant
le traçage de la notification critique (§8.4/§11.4) **sans** migration (l'enum `CONFIRMATION` existe
depuis la migration `0001`). Le canal est résolu par une fonction pure **PUSH → SMS → IN_APP**
(WhatsApp exclu, V2) ; au MVP, faute de registre de jetons d'appareil, le canal effectif est **SMS**.
La **remise proactive** (push/SMS via file Redis) reste **différée M5+** (Épic 7,
[ADR-0006](./docs/adr/0006-notifications-fcm-sms.md)) : #45 **émet/trace** la confirmation, il n'**envoie**
rien (`sent_at` reste `NULL`) — cohérent avec la non-remise du reçu #38 (ADR-0030), voir
[ADR-0033](./docs/adr/0033-notification-confirmation-rdv.md). Le **rappel automatique avant RDV** (#46,
US-7.2) est livré à la suite : à la création d'un RDV, `BookAppointment` **planifie** jusqu'à **3 rappels**
`REMINDER` `PENDING` (`scheduled_for = début − 24h/2h/30min`, une ligne par échéance encore future) dans
`notifications`, **même unité de travail** que la réservation — **migration `0006`** requise (colonne
`scheduled_for` + statut `NotificationStatus.CANCELLED`, absents du schéma initial). L'**annulation du
RDV annule ses rappels** (§8.4/§11.4, AC) : annulation client (#24) et refus gérant (#25) marquent
`CANCELLED` les rappels `PENDING` du RDV, dans la même transaction que le changement de statut ; une
**modification** (#23) les **re-planifie** sur le nouveau créneau. Comme #45, la **remise proactive**
(push/SMS) et l'**ordonnanceur** qui interrogera les rappels dus restent **différés M5+** (ADR-0006) —
rien n'est réellement envoyé, `sent_at` reste `NULL`, voir
[ADR-0034](./docs/adr/0034-rappel-automatique-avant-rdv.md). La **notification au salon à la réservation**
(#47, US-7.3) est livrée à la suite côté backend : à la création d'un RDV, en plus des notifications
**client** (#45/#46), `BookAppointment` **notifie le salon** — **une** ligne `notifications`
(`type = NEW_BOOKING`, `channel = IN_APP`, `status = PENDING`) est **émise/tracée** vers le **gérant**
(`user_id = salon.owner_id`), rattachée au salon et au RDV, dans la **même unité de travail** que la
réservation (une réservation échouée n'en laisse aucune). **Migration `0007`** requise : valeur d'enum
`NotificationType.NEW_BOOKING` + régénération du `CHECK` `type` (patron du `CHECK` `status` de `0006`). Le
canal « dashboard » est `IN_APP` ; l'**option** de remise proactive email/SMS au gérant reste **différée
M5+** (ADR-0006, `sent_at` reste `NULL`). Le périmètre est **strict** (création uniquement — l'annulation/
la modification au client comme au salon relèvent de #48, US-7.4) ; l'endpoint de **lecture** salon-scopé
qui afficherait ces notifications est **différé** (parité #45), voir
[ADR-0035](./docs/adr/0035-notification-salon-a-la-reservation.md). La **notification d'annulation/
modification** (#48, US-7.4) est livrée à la suite côté backend : « un changement de statut déclenche la
notification aux parties concernées » (§8.4). Sur **toute** transition `→ CANCELLED` (annulation client
#24 ou refus gérant #25), **deux** lignes `notifications` (`type = CANCELLATION`) sont **émises/tracées** —
au **client** (canal résolu, SMS au MVP) **et** au **salon** (`user_id = salon.owner_id`, canal `IN_APP`),
comme l'exige §8.4 ; sur les **autres** changements de statut gérant (`CONFIRMED`/`COMPLETED`/`NO_SHOW`) le
**client** est notifié, et sur une **modification** (#23) le **salon** l'est, via `type = APPOINTMENT_UPDATE`.
Le cœur « annulation » **n'exige aucune migration** (`CANCELLATION` existe depuis `0007`) ; le reste ajoute
la **migration `0008`** (valeur d'enum `APPOINTMENT_UPDATE` + régénération du `CHECK` `type`). Toutes sont
persistées dans la **même unité de travail** que le changement de statut (un changement échoué n'en laisse
aucune). Comme #45/#46/#47, la **remise proactive** (push/SMS/email) reste **différée M5+** (ADR-0006,
`sent_at` reste `NULL`) et la **lecture** est différée (parité #45/#47), voir
[ADR-0036](./docs/adr/0036-notification-annulation-modification.md). Les **campagnes/messages aux
clients** (#49, US-7.5) closent l'Épic 7 côté émission/trace : le gérant crée une campagne
(`POST /salons/{salon_id}/campaigns`, rappel/promotion/fermeture exceptionnelle) ciblant un **segment**
salon-scopé de ses fiches clients (#28) — **émise/tracée** dans une table dédiée `campaigns` (migration
`0009`), avec un **effectif** snapshot **non-PII** (`recipient_count`, `COUNT` des fiches joignables du
segment) et `status = PENDING`, dans la **même unité de travail** que l'audit `CAMPAIGN_CREATED`. La
**remise** (fan-out SMS) reste **différée M5+** (ADR-0006, `sent_at` reste `NULL`) — aucun numéro n'est
matérialisé ni journalisé, voir [ADR-0037](./docs/adr/0037-campagnes-messages-clients.md).
**M6 est amorcé** : les **tests e2e des parcours critiques** sont livrés (#50) — les trois parcours
Must du PRD §5 (réservation client §5.1, gestion RDV gérant §5.2, encaissement §5.3) sont exercés de
bout en bout dans [`backend/tests/test_critical_journeys_e2e.py`](./backend/tests/test_critical_journeys_e2e.py)
au **niveau HTTP du backend** (`TestClient` → routers → cas d'usage → dépôts SQL → PostgreSQL).
Chaque parcours enchaîne les endpoints réels sur des entités partagées (un même salon, un même client,
un même RDV) et vérifie la **continuité inter-modules** qu'aucune suite par-fonctionnalité ne couvre —
par exemple qu'un RDV `COMPLETED` apparaît bien dans l'historique client, qu'un paiement fait monter
le CA du dashboard et qu'un reçu est récupérable dès l'encaissement. La suite intègre la CI **sans
modification du workflow** (job `backend` de `ci.yml`, où `DATABASE_URL` est défini et `alembic upgrade
head` précède `pytest`) — sa réussite est une **condition de merge**. Dans la foulée, les **tests de
sécurité** (#51, §11) consolident le socle authz/JWT/brute-force/journalisation « comme un tout », du
point de vue d'un attaquant, sur toute la surface d'API montée : une **matrice rôle × route réelle**
dérivée de `ROLE_PERMISSIONS` (rôle non habilité → `403` générique, sans jeton → `401`), les propriétés
**JWT/refresh** (`alg=none`, confusion d'algorithme, signature altérée, claims manquants, expiration,
mauvais `type`, `503` sans secret), la **non-divulgation** (`PUBLIC_ROUTE_PATHS`, aucun secret dans les
schémas de réponse) — volet rapide dans le gate ADW ; puis, en e2e (PostgreSQL requis), l'**isolation
inter-salons** sur routes réelles (lecture/écriture inter-salons → `403` sans écriture, anti-oracle,
filtre `client_id` étranger → vide, révocation immédiate, rotation du refresh), le **brute-force** HTTP de
`POST /auth/login` (`429` + `Retry-After`, `401` générique identique, succès qui réinitialise) et la
**journalisation** §11.3/§11.4 (présence des entrées sensibles, atomicité échec → 0 entrée, **invariant de
non-fuite** balayant `audit_logs`). La suite **teste l'existant** : les actions §11.4 non encore câblées
(`Connexion`, `Création rendez-vous`, `Création employé`, `Désactivation salon`) sont documentées comme
gap, pas assertées présentes.
Enfin, les **tests de performance** (#52, §12.1) mesurent la latence des **endpoints critiques** sous
**charge nominale** contre un **serveur réel** (uvicorn + PostgreSQL 16 peuplée) : recherche salon
(`< 2 s`), création de rendez-vous (`< 3 s`), dashboard gérant agrégé (`< 3 s`) et échantillon d'API
générale (`< 3 s`). Le harnais vit sous [`backend/perf/`](./backend/perf/README.md) (hors package de prod,
hors image Docker, extra `perf` opt-in) ; il produit un **rapport** p50/p95/p99 confronté aux budgets §12.1
(PASS/WARN/FAIL en CSV/JSON/Markdown). La suite est **informative** et tourne dans un **job CI dédié
opt-in** ([`perf.yml`](./.github/workflows/perf.yml), `workflow_dispatch`/nocturne) — **hors** du test gate
ADW et **hors** des status checks requis (la variabilité des runners partagés rendrait un seuil dur flaky) ;
le verdict **de référence** vise **staging** via `PERF_TARGET_URL`. #52 **mesure** sans modifier le code de
production : un dépassement se **documente** (issue d'optimisation dédiée), il ne se corrige pas ici.
Enfin, la **documentation utilisateur** est livrée (#53) : deux guides pas à pas en français sous
**[docs/guides/](./docs/guides/README.md)** — un **[guide gérant](./docs/guides/guide-gerant.md)**
(interface web) et un **[guide client](./docs/guides/guide-client.md)** (application mobile) — couvrant
les **parcours Must** (§5.1/§5.2/§5.3) tels qu'ils sont réellement livrés, avec des encadrés « À venir »
pour les étapes pas encore exposées à l'interface (notifications non remises, reçu/inscription mobiles,
journal de caisse/zone admin/employés côté web).

---

## 7. Démarrer

### Prérequis

- Node ≥ 20.19 et npm
- `gh` (GitHub CLI) authentifié sur le dépôt
- Une clé runner pour le pipeline (ex. `ANTHROPIC_API_KEY` pour le runner `claude`)

### Configuration locale

```bash
cp scripts/adw.env.example scripts/adw.env   # gitignoré — renseigner la clé runner et le test gate
(cd adw_sdlc && npm install)                 # dépendances du control plane
```

### (Re)générer les issues GitHub depuis le backlog

> Déjà effectué : les issues #1–#55 existent. À ne relancer que sur un dépôt vierge.

```bash
scripts/create-backlog-issues.sh --dry-run   # aperçu (aucune écriture)
scripts/create-backlog-issues.sh             # création réelle
```

### Lancer le pipeline sur une issue

```bash
scripts/run-issue.sh 1 --dry-run             # prévisualiser le plan (ne consomme rien)
scripts/run-issue.sh 1 --yes                 # exécution réelle (code, commit, PR ; --yes peut auto-merger)
scripts/run-issue.sh --help                  # liste complète des options
```

> Le **test gate** du pipeline est défini par `MX_AGENT_TEST_CMD` dans `scripts/adw.env`. Il est **câblé**
> (#6) sur le wrapper [`scripts/test-gate.sh`](./scripts/test-gate.sh), qui exécute les tests unitaires des
> trois paquets (`pytest` / `npm test` / `flutter test`, parité CI) avec un code de sortie agrégé — cf.
> **[docs/strategie-de-tests.md](./docs/strategie-de-tests.md)**. Restreindre les paquets via
> `TEST_GATE_PACKAGES` ; laissé vide, `MX_AGENT_TEST_CMD` désactive le gate (traité comme vert).

---

## 8. Roadmap (jalons)

| Jalon | Sprint | Objectif | Issues |
| --- | --- | --- | --- |
| **M0** | 0 | Socle : stack (ADR), dépôt, schéma de données, CI, environnements | #1–#7 |
| **M1** | 1 | Authentification, RBAC, squelette dashboard | #8–#14 |
| **M2** | 2 | Salons & prestations, consultation client | #15–#20 |
| **M3** | 3 | Rendez-vous : réservation, statuts, planning | #21–#27 |
| **M4** | 4 | Clients, encaissement & journal de caisse | #28–#38 |
| **M5** | 5 | Tableau de bord & notifications | #39–#49 |
| **M6** | 6 | Tests, durcissement, déploiement, pilote | #50–#55 |

Chemin critique : **M0 → M1 → M2 → M3 → M4/M5 → M6**.

## 9. Références

- [prd-coiflink.md](./prd-coiflink.md) — exigences produit (source de vérité)
- [BACKLOG.md](./BACKLOG.md) — backlog livrable (55 issues, M0–M6)
- [docs/guides/](./docs/guides/README.md) — guides utilisateur (parcours Must) : [guide gérant](./docs/guides/guide-gerant.md) · [guide client](./docs/guides/guide-client.md)
- [adw_sdlc/README.md](./adw_sdlc/README.md) — usage du pipeline ADW
- [adw_sdlc/PLAN.md](./adw_sdlc/PLAN.md) — architecture du pipeline
