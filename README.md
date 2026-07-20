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
5. **Encaissement** — paiements, journal de caisse
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
| `backend` | `ruff check` · `pytest` · round-trip Alembic contre **PostgreSQL 16** · `python -m build` | `backend-dist` (wheel + sdist) |
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
la visibilité §8.3 : un salon désactivé reste absent du catalogue même après modification). La
**réservation** elle-même reste **#21+** (Épic 3) : la fiche en est le point d'entrée, le flux n'est
pas encore construit.

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
- [adw_sdlc/README.md](./adw_sdlc/README.md) — usage du pipeline ADW
- [adw_sdlc/PLAN.md](./adw_sdlc/PLAN.md) — architecture du pipeline
