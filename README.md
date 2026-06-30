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

1. **Authentification** — comptes client/gérant/employé, connexion JWT, rôles
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
| Base de données | PostgreSQL + Redis (cache/queue) | [0004](./docs/adr/0004-donnees-postgresql-redis.md) |
| Fichiers | Stockage objet S3-compatible | [0005](./docs/adr/0005-stockage-objet-s3-compatible.md) |
| Notifications | Firebase Cloud Messaging + SMS (WhatsApp en V2) | [0006](./docs/adr/0006-notifications-fcm-sms.md) |
| Déploiement | Docker · CI/CD GitHub Actions | _à figer par l'ADR de déploiement (#4/#5)_ |

**Versions de référence** (figées par #2 — voir [ADR-0007](./docs/adr/0007-arborescence-monorepo-versions.md)) :
Flutter **stable** / Dart **^3.12**, Node **≥ 20 (LTS)**, Python **≥ 3.12** ; pour mémo (runtime, hors
code en #2) PostgreSQL **16**, Redis **7**. Le `web-dashboard/` est **une seule application Next.js** à
zones protégées par rôle (`/gerant`, `/admin`).

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
├── docs/adr/                  # Architecture Decision Records (stack & socle)
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

> Le **test gate** agrégé du pipeline (`MX_AGENT_TEST_CMD`) reste à câbler en #6 ; #2 garantit que ces
> commandes par paquet sont réelles et passent sur le squelette.

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

**Prochaine étape :** exécuter le pipeline issue par issue, en commençant par l'**ADR de stack (#1)**,
puis l'initialisation du dépôt (#2) et le socle (M0) avant les fonctionnalités (M1→M5) et le
durcissement (M6).

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

> Le **test gate** du pipeline est défini par `MX_AGENT_TEST_CMD` dans `scripts/adw.env`
> (ex. `flutter test` côté mobile — cf. [ADR-0001](./docs/adr/0001-app-mobile-flutter.md) ; `pytest`
> côté backend — cf. [ADR-0003](./docs/adr/0003-backend-fastapi.md)). La stack étant tranchée par les
> ADR (#1), le câblage concret du gate reste à faire en #6 ; tant qu'il est vide, le gate est ignoré
> (traité comme vert).

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
