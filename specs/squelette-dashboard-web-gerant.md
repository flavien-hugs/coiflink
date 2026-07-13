# Squelette du dashboard web gérant (navigation, layout, garde d'authentification)

> Spécification de planification pour l'issue GitHub **#14 — Squelette du dashboard web gérant**
> (`feature` `ux` · Must · Effort S · PRD §7.2 « Interface web gérant », §18 Sprint 1 « Base du
> dashboard »).
> **Dépend de #10** (connexion téléphone/e-mail → JWT + refresh, livrée) et **#12** (middleware
> d'autorisation & RBAC, `GET /auth/me`, deny-by-default, livrée).
> **Bloque #15** (création d'un salon — première ressource métier consommée depuis le dashboard).
>
> **Cette spec ne produit pas de code.** Elle décrit le shell applicatif du dashboard gérant côté
> `web-dashboard/` (Next.js) : layout, navigation, et surtout la **garde d'authentification** qui
> redirige un visiteur non authentifié et laisse passer un gérant authentifié vers un dashboard
> **vide mais protégé**. L'implémentation est renvoyée à une phase ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, commentaires). Les
> en-têtes de section ci-dessous sont conservés en anglais car attendus par le gabarit du pipeline
> ADW ; le contenu reste en français, hors identifiants techniques (routes, noms de fichiers, enums,
> symboles de code).

## Problem Statement

Le paquet `web-dashboard/` est aujourd'hui un **squelette d'initialisation** (#2) : une seule page
d'accueil neutre (`app/page.tsx`), un `RootLayout` minimal (`app/layout.tsx`), une couche domaine
triviale (`src/domain/site.ts`) et un test d'ancrage (`test/site.test.ts`). **Aucune route
protégée, aucune navigation, aucune notion de session** n'y existe. La commande `page.tsx` documente
elle-même que « les zones gérant (`/gerant`) et admin (`/admin`) seront protégées par rôle (RBAC
backend) dans les issues M1→ ».

Côté backend, la brique nécessaire est **livrée** :

- **#10** émet, à la connexion valide (`POST /auth/login`), un **JWT d'accès** (court, ~15 min) et un
  **refresh token** (long, ~30 j), et permet de rafraîchir (`POST /auth/refresh`) — schéma d'auth
  **Bearer** (`Authorization: Bearer <access_token>`).
- **#12** expose **`GET /auth/me`** : route **protégée** renvoyant `200 UserResponse` (`id`,
  `full_name`, `phone`, `email`, `role`, `status`, `created_at` — **aucun secret**) pour le porteur
  d'un jeton d'accès valide, `401` sans jeton valide (absent/expiré/altéré/refresh présenté comme
  accès), `403` si le compte n'est pas `ACTIVE`, `503` si `JWT_SECRET` n'est pas configuré. Le **rôle
  fait foi en base** (relu à chaque requête), pas le claim.

Le PRD §7.2 décrit le dashboard gérant cible (indicateurs du jour, planning, clients, prestations,
encaissements, employés, paramètres) ; §18 (Sprint 1) prévoit d'en poser la **base**. Il manque donc
le **shell** de cette interface : un layout structurant (barre latérale/haut de page, zone de
contenu), une navigation vers les futures sections (encore vides), et une **garde d'authentification**
qui matérialise l'invariant côté client.

**Besoin de #14 (strictement les critères d'acceptation) :**

- **Un gérant authentifié atteint un dashboard vide mais protégé** — une page sous `/gerant` qui ne
  s'affiche que si une session valide de rôle `MANAGER` existe.
- **Un non-authentifié est redirigé** — toute tentative d'accès à `/gerant*` sans session valide
  renvoie vers un point d'entrée de connexion.

Ce shell devient le **point d'accroche** de toutes les issues M2–M5 (salons, planning, clients,
caisse, stats) qui monteront leurs écrans dans ses sections de navigation.

## Goals

- **Zone protégée `/gerant`** : un groupe de routes Next.js (App Router) portant le **layout du
  dashboard** (shell : en-tête, navigation, zone de contenu) et une **page d'accueil vide**
  (`/gerant`) affichant au minimum un titre et un espace de contenu, **sans donnée métier**.
- **Garde d'authentification (deny-by-default côté client)** : tout accès à `/gerant*` sans session
  valide **redirige** vers l'écran de connexion ; le contenu protégé n'est **jamais** rendu à un
  visiteur non authentifié (pas de « flash » du contenu privé).
- **Vérification de session appuyée sur le backend (source de vérité)** : la validité de la session
  est établie via **`GET /auth/me`** (#12) — la présence d'un jeton ne suffit pas ; c'est la réponse
  `200` (compte `ACTIVE`, jeton d'accès valide) qui autorise l'affichage. Un `401`/`403`/`503`
  conduit à la redirection (ou à un état d'erreur maîtrisé pour `503`).
- **Restriction au rôle gérant** : `/gerant*` n'est destiné qu'au rôle `MANAGER`. Un utilisateur
  authentifié d'un **autre rôle** (`CLIENT`, `HAIRDRESSER`, `ADMIN`) est traité comme non autorisé
  pour cette zone (redirection ou page « accès refusé » dédiée — à trancher, voir Open Questions).
- **Point d'entrée de session** : un écran/route de **connexion** minimal permettant d'établir une
  session (appel `POST /auth/login`) et de **déconnexion** (effacement de la session), suffisant pour
  démontrer de bout en bout le chemin « connexion → dashboard » et « déconnexion → redirection ».
  *(Périmètre exact à confirmer — voir Open Questions : #14 peut se limiter à un login minimal
  technique, l'UX complète de connexion pouvant relever d'une issue distincte.)*
- **Navigation du shell** : une navigation listant les **futures** sections du §7.2 (Tableau de bord,
  Planning, Clients, Prestations, Encaissements, Employés, Paramètres) — liens présents mais menant à
  des pages **vides / « à venir »**, sans logique métier. Objectif : figer la structure de navigation
  que les issues M2–M5 rempliront.
- **Respecter l'architecture hexagonale du paquet (ADR-0008)** : types de session dans `src/domain/`,
  cas d'usage + **ports** dans `src/application/`, client HTTP backend dans `src/adapters/api/`,
  composants React dans `src/adapters/ui/` ; `app/` reste l'**adapter entrant** (routage) et la
  **composition root** du framework. Le domaine ne dépend ni de React ni du réseau.
- **Respecter le budget de perf (§12.1, dashboard < 3 s)** et la politique de secrets (ADR-0011) :
  aucun secret dans le bundle client ; seules les variables `NEXT_PUBLIC_*` sont exposées au
  navigateur.
- **Tester le comportement de garde** : redirection du non-authentifié, rendu du dashboard pour un
  gérant authentifié, refus des autres rôles — via Vitest (test gate `npm test`, #6), les suites
  existantes restant vertes.

## Non-Goals

- **Toute fonctionnalité métier du dashboard (§7.2)** : indicateurs du jour, planning, fiches
  clients, prestations, encaissements, employés, paramètres du salon — ce sont les issues **M2–M5**
  (#15+). #14 ne livre que le **shell vide** et la navigation vers des pages « à venir ».
- **Création/configuration de salon (#15)** : dépend de #14 ; hors périmètre ici.
- **Zone admin `/admin` (§7.3)** : le shell admin (KPI plateforme, supervision) est un travail
  distinct ; #14 se concentre sur `/gerant`. La structure de routes retenue doit toutefois **laisser
  la place** à `/admin` (une application Next.js unique, zones par rôle — ADR-0002 / ADR-0007).
- **Modification du backend** : #14 est **front-only**. Il **consomme** `POST /auth/login`,
  `POST /auth/refresh`, `GET /auth/me` (déjà livrés par #10/#12) sans les changer. Aucun changement
  d'API, de schéma ni d'ADR backend.
- **UX complète de connexion / inscription** (design, validation fine, gestion d'erreurs riche,
  « mot de passe oublié » relié à #11) : #14 se limite au **minimum** nécessaire pour établir/effacer
  une session et démontrer la garde. L'écran de connexion abouti peut relever d'une issue UX dédiée
  *(à confirmer)*.
- **Rafraîchissement automatique du jeton d'accès à expiration** (rotation transparente sur `401`) :
  utile mais au-delà du squelette ; **recommandé en suivi**. #14 peut se contenter de traiter un
  `401` comme « session expirée → redirection connexion ».
- **Internationalisation, thème, responsive avancé, design system** : le shell doit être **lisible et
  responsive de base** (§7.2 « responsive », §12.1) mais l'habillage abouti n'est pas l'objet de #14.
- **Application mobile (`app-mobile/`)** : hors périmètre.
- **Tests end-to-end navigateur (Playwright/Cypress)** : l'infrastructure e2e web n'existe pas encore
  dans le dépôt ; #14 s'appuie sur des tests **Vitest** (unitaires/composants). Un e2e web est un
  suivi possible (cf. issues M6).

## Relevant Repository Context

### Stack (figée — aucune décision de stack ouverte pour ce paquet)

- **Interface web gérant/admin = Next.js (React, TypeScript)** — [ADR-0002](../docs/adr/0002-web-gerant-admin-nextjs.md).
  **Une seule application** Next.js à zones protégées par rôle (`/gerant`, `/admin`) — décision
  d'arborescence tracée dans [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md) (cf.
  README §4 et `web-dashboard/README.md`).
- **Versions figées** (`web-dashboard/package.json`) : **Next.js 16.2.9**, **React 19.2.4**,
  **TypeScript ^5**, **Node ≥ 20**. Tests : **Vitest ^3** (`npm test` → `vitest run`). Lint :
  **ESLint 9** + `eslint-config-next` (`npm run lint`). Build : `npm run build` (sortie
  **`standalone`**, `next.config.ts`).
- **App Router** (répertoire `app/`) : `app/layout.tsx` (RootLayout, `<html lang="fr">`),
  `app/page.tsx` (accueil neutre), `app/globals.css`. **Aucun** `middleware.ts` n'existe encore.
- **Alias d'import** : `@/*` → racine du paquet (`tsconfig.json`).
- **Architecture hexagonale** ([ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) telle que
  décrite dans `web-dashboard/README.md` :

  ```
  src/
    domain/         # entités, règles & config métier (TS pur — ex. site.ts)
    application/    # cas d'usage + ports
    adapters/
      ui/           # composants React (consommés par app/)
      api/          # clients HTTP vers le backend (driven)
  app/              # routage Next.js = adapter entrant + composition root du framework
  ```

  Les répertoires `src/application/`, `src/adapters/ui/`, `src/adapters/api/` existent mais ne
  contiennent qu'un `README.md` (aucun code) — #14 y pose ses premiers modules réels.

### Contrat backend consommé (livré, inchangé par #14)

- **`POST /auth/login`** (public) — corps `{ identifier, password }` ; `200` →
  `{ access_token, refresh_token, token_type: "bearer", expires_in }` ; `401` générique
  (identifiants invalides) ; `429` (+ `Retry-After`) si anti-bruteforce déclenché ; `422` corps
  malformé. (#10 / [ADR-0013](../docs/adr/0013-connexion-jwt-refresh-anti-bruteforce.md).)
- **`POST /auth/refresh`** (public) — corps `{ refresh_token }` ; `200` → nouvelle paire (rotation) ;
  `401` refresh invalide/expiré.
- **`GET /auth/me`** (protégé, Bearer) — `200 UserResponse` (`id`, `full_name`, `phone`, `email`,
  `role`, `status`, `created_at`) ; `401` (jeton absent/invalide/expiré/refresh-en-accès ou compte
  introuvable) ; `403` (compte non `ACTIVE`) ; `503` (`JWT_SECRET` non configuré). (#12.)
- **Rôles** (`domain/enums.Role`, PRD §4.1) : `CLIENT`, `HAIRDRESSER`, `MANAGER`, `ADMIN`. Le **gérant
  = `MANAGER`**. Le rôle est **relu en base** côté backend (autoritatif) ; le front s'y fie via la
  réponse de `/auth/me`.
- **Note d'alignement (#12, Risk 9)** : les clients web/mobile doivent envoyer `Authorization:
  Bearer` et gérer `401` (re-login/refresh) et `403` (accès refusé). #14 est le premier consommateur
  web de ce contrat.

### Configuration & secrets (ADR-0011)

- `web-dashboard/.env.example` documente **`NEXT_PUBLIC_API_BASE_URL`** (NON secret, **exposé au
  navigateur**) — URL de base du backend par environnement. Toute variable `NEXT_PUBLIC_*` est
  intégrée au bundle client : **jamais** de secret. Copier en `.env.local` (gitignoré) en local.
- Aucun secret n'est committé ; les secrets réels vivent hors dépôt (magasin de la plateforme /
  GitHub Environments). Hébergement **Railway**, terminaison **TLS** côté plateforme.

### Conventions

- Conventional Commits ; **aucune signature IA** dans code/commits/PR ; specs à en-têtes anglais /
  contenu français ; docstrings/commentaires en français référençant l'issue et l'ADR.
- Lint `npm run lint` propre ; test gate `npm test` (Vitest) — les suites existantes
  (`test/site.test.ts`) doivent **rester vertes**. Le test gate agrégé (#6, `scripts/test-gate.sh`)
  enchaîne les paquets ; parité CI (`.github/workflows/ci.yml`, job `web` : lint + test + build
  standalone).

## Proposed Implementation

> Approche recommandée pour un agent d'implémentation. Les points marqués *(à confirmer)* renvoient à
> *Risks and Open Questions*. Fil directeur : rester **hexagonal** (domaine/application purs, I/O dans
> les adapters), **deny-by-default côté route**, et **s'appuyer sur `/auth/me` comme source de
> vérité** de la session plutôt que de « faire confiance » à la simple présence d'un jeton.

### Décision structurante n°1 — où vit le jeton et où s'exécute la garde *(à confirmer)*

Deux familles d'implémentation d'une garde d'authentification en Next.js App Router :

- **Option A — BFF via cookie httpOnly + `middleware.ts` (recommandée).** Le web-dashboard agit comme
  **Backend-For-Frontend** : des **Route Handlers** Next.js (`app/api/auth/*`) reçoivent les
  identifiants, appellent le backend (`POST /auth/login`), puis **posent les jetons dans des cookies
  `httpOnly`, `Secure`, `SameSite=Lax`** (jamais accessibles au JS du navigateur). Un
  **`middleware.ts`** intercepte `/gerant/*` et **redirige** vers `/login` si le cookie de session est
  **absent** (garde « bon marché », sans I/O réseau au niveau edge). La **vérification réelle**
  (jeton encore valide + rôle + statut) est faite dans le **layout serveur** de `/gerant` via un appel
  `GET /auth/me` (Server Component), qui redirige en cas de `401`/`403`.
  - *Avantages* : le contenu privé n'est **jamais** envoyé au navigateur pour un non-authentifié
    (garde côté serveur, pas de « flash ») ; les jetons ne sont **pas** exposés au JS (atténue le
    XSS-vol de jeton) ; la source de vérité reste `/auth/me`. Cohérent avec le budget < 3 s (une seule
    vérif réseau côté serveur au premier rendu).
  - *Compromis* : un **hop** supplémentaire (browser → route handler Next → backend) ; deux URL
    backend possibles (voir Décision n°2). Plus de code que l'option B.
- **Option B — jeton en mémoire/`localStorage` + garde côté client.** Le login appelle directement le
  backend depuis le navigateur ; le jeton est stocké côté client ; un composant client (`useEffect` +
  `router.replace`) redirige si absent/invalide.
  - *Avantages* : plus simple, moins de code ; suffisant pour un « squelette ».
  - *Compromis* : **flash** possible du contenu protégé avant redirection ; jeton exposé au JS
    (risque XSS) ; garde **non** applicable au niveau `middleware` (le middleware ne lit pas
    `localStorage`) ; SSR ne peut pas pré-garder. Moins conforme à l'esprit « deny-by-default ».

**Recommandation : Option A** (cookie httpOnly + middleware pour la redirection « présence » +
vérification `/auth/me` dans le layout serveur). Elle satisfait proprement les deux critères
d'acceptation et l'invariant de sécurité, au prix d'un BFF minimal. À **confirmer** avec l'équipe
(l'option B reste acceptable si le squelette doit rester ultra-léger — dans ce cas, documenter la
limite « flash » et le durcissement différé).

### Décision structurante n°2 — URL du backend (navigateur vs serveur) *(à confirmer)*

- En Option A, les Route Handlers et le layout serveur appellent le backend **côté serveur Next**. Si
  le backend n'est joignable que par une **URL interne** (réseau privé Railway), une variable
  **non publique** (`API_BASE_URL`, côté serveur uniquement) peut différer de
  `NEXT_PUBLIC_API_BASE_URL` (URL publique, si des appels navigateur subsistent). Par défaut, garder
  **une seule** URL publique `NEXT_PUBLIC_API_BASE_URL` (déjà documentée) et, si besoin, ajouter
  `API_BASE_URL` **non secrète** pour les appels serveur. **Aucun secret** dans ces variables.
- En Option A, le navigateur ne parle qu'aux Route Handlers de même origine → pas de CORS ni de jeton
  exposé. En Option B, `NEXT_PUBLIC_API_BASE_URL` doit pointer un backend **CORS-autorisé**.

### 1. Domaine — `src/domain/` (TS pur, sans React ni réseau)

- **`auth/role.ts`** — `Role` (union de chaînes ou enum : `"CLIENT" | "HAIRDRESSER" | "MANAGER" |
  "ADMIN"`) alignée sur le backend (PRD §4.1) ; helper `isManager(role)`.
- **`auth/session.ts`** — types de session : `AuthenticatedUser` (`id`, `fullName`, `role`, `status`,
  + champs de `UserResponse` utiles à l'affichage — **jamais** de jeton ni de secret) ; `SessionState`
  (`authenticated` / `unauthenticated`). Fonction pure `canAccessGerant(user): boolean`
  (`role === MANAGER && status === "ACTIVE"`). Ces types sont **agnostiques du transport**.
- **`navigation/sections.ts`** — liste **statique** des sections du shell §7.2 (`{ key, label, href,
  status: "available" | "coming-soon" }`) : Tableau de bord (`/gerant`), Planning, Clients,
  Prestations, Encaissements, Employés, Paramètres — toutes `coming-soon` sauf l'accueil. Source de
  vérité de la navigation, testable sans React.

### 2. Application — `src/application/` (cas d'usage + ports)

- **`ports/auth-gateway.ts`** — port `AuthGateway` (interface TS) :
  `login(identifier, password): Promise<...>`, `getCurrentUser(): Promise<AuthenticatedUser | null>`
  (mappe `/auth/me` : `200` → user, `401`/`403` → `null`), `logout(): Promise<void>`,
  *(optionnel/suivi)* `refresh()`. Le cas d'usage ne connaît **ni fetch ni cookie**.
- **`ports/session-store.ts`** *(Option A)* — port d'écriture/lecture de la session persistée
  (cookies httpOnly), implémenté par un adapter serveur.
- **`use-cases/require-manager-session.ts`** — cas d'usage : appelle `AuthGateway.getCurrentUser()` et
  renvoie une décision `{ allow: true, user } | { allow: false, reason: "unauthenticated" |
  "wrong-role" | "unavailable" }` (via `canAccessGerant`). C'est **le cœur testable** de la garde,
  indépendant de Next. Le layout serveur (adapter entrant) traduit la décision en `redirect()` /
  rendu.

### 3. Adapters — `src/adapters/`

- **`api/http-auth-gateway.ts`** — implémente `AuthGateway` avec `fetch` vers le backend (URL depuis
  la config d'environnement ; en Option A, appels **côté serveur** avec le jeton lu du cookie et
  posé en `Authorization: Bearer`). Mappe les statuts `200/401/403/429/503` en résultats de domaine ;
  **ne journalise jamais** jeton, mot de passe, `Authorization`, ni PII (`phone`/`email`/`full_name`).
- **`ui/dashboard-shell.tsx`** — composant de layout : en-tête (nom du salon/gérant à terme, bouton
  **Déconnexion**), **navigation** (rendue depuis `navigation/sections.ts`, item actif surligné), zone
  de contenu (`children`). Responsive de base (§7.2). Sans logique métier.
- **`ui/nav.tsx`** — la navigation latérale/supérieure (liens `next/link`), items `coming-soon`
  visuellement distincts et non actifs (ou menant à une page « À venir »).
- **`ui/login-form.tsx`** *(client component minimal)* — formulaire `identifier` + `password` qui
  poste vers le Route Handler (`app/api/auth/login`, Option A) ou la gateway (Option B) ; affiche une
  erreur générique sur `401`/`429` (jamais de détail sensible).

### 4. Adapter entrant / composition root — `app/` + `middleware.ts`

- **`middleware.ts`** *(Option A)* — matcher sur `/gerant/:path*` : si le **cookie de session est
  absent**, `NextResponse.redirect(new URL("/login", request.url))`. (Vérification « présence » rapide
  ; la validité réelle est contrôlée au niveau layout serveur.)
- **`app/(gerant)/layout.tsx`** — **Server Component** : exécute `require-manager-session` (→
  `getCurrentUser` via `/auth/me`) ; `unauthenticated` → `redirect("/login")` ; `wrong-role` →
  `redirect("/login")` **ou** page « accès refusé » *(à confirmer)* ; `unavailable` (`503`) → état
  d'erreur maîtrisé (message générique, pas de contenu privé). Si `allow` → rend `<DashboardShell>`
  avec `children`.
- **`app/(gerant)/gerant/page.tsx`** — **dashboard vide protégé** : titre (« Tableau de bord ») +
  espace de contenu vide / message « Bienvenue ». Aucun appel métier.
- **`app/(gerant)/gerant/<section>/page.tsx`** *(optionnel)* — pages « À venir » pour Planning,
  Clients, etc., ou une page générique paramétrée. Peut être **différé** si la nav pointe vers des
  ancres désactivées ; garder minimal.
- **`app/login/page.tsx`** — écran de connexion minimal (`<LoginForm>`), **hors** zone `/gerant`
  (publique). Après login réussi → redirection vers `/gerant`.
- **`app/api/auth/login/route.ts`**, **`app/api/auth/logout/route.ts`** *(Option A)* — Route Handlers
  BFF : `login` proxifie `POST /auth/login` et pose les cookies httpOnly ; `logout` efface les
  cookies. *(optionnel : `app/api/auth/refresh/route.ts` en suivi.)*
- **`app/page.tsx`** — page d'accueil : peut rediriger vers `/gerant` (si session) ou `/login`, ou
  rester une landing neutre avec liens *(à confirmer — garder simple)*.

Le domaine et l'application ne connaissent **ni Next, ni `fetch`, ni cookie** ; toute I/O (réseau,
cookies, redirection) vit dans `adapters/` et `app/`/`middleware.ts`.

## Affected Files / Packages / Modules

**Paquet concerné : `web-dashboard/` uniquement** (backend/mobile hors périmètre).

**À créer (indicatif ; Option A retenue) :**
- `src/domain/auth/role.ts`, `src/domain/auth/session.ts`
- `src/domain/navigation/sections.ts`
- `src/application/ports/auth-gateway.ts`, `src/application/ports/session-store.ts`
- `src/application/use-cases/require-manager-session.ts`
- `src/adapters/api/http-auth-gateway.ts`
- `src/adapters/ui/dashboard-shell.tsx`, `src/adapters/ui/nav.tsx`, `src/adapters/ui/login-form.tsx`
- `app/(gerant)/layout.tsx`, `app/(gerant)/gerant/page.tsx`
  (+ éventuelles pages « À venir » des sections)
- `app/login/page.tsx`
- `app/api/auth/login/route.ts`, `app/api/auth/logout/route.ts`
- `middleware.ts` (racine du paquet)
- Config d'accès aux variables d'environnement (ex. `src/adapters/api/config.ts`) lisant
  `NEXT_PUBLIC_API_BASE_URL` (et, si retenu, `API_BASE_URL` serveur)
- Tests Vitest : `test/auth-session.test.ts` (domaine `canAccessGerant`),
  `test/navigation-sections.test.ts`, `test/require-manager-session.test.ts` (cas d'usage avec
  `AuthGateway` **fake**), `test/http-auth-gateway.test.ts` (mapping des statuts, `fetch` mocké)

**À modifier :**
- `app/page.tsx` — accueil (redirection ou liens vers `/login` / `/gerant`)
- `web-dashboard/README.md` — section « Dashboard gérant : shell, navigation, garde d'auth » (routes,
  variables d'environnement, comment ajouter une section)
- `web-dashboard/.env.example` — documenter toute variable ajoutée (ex. `API_BASE_URL` serveur si
  Option A) ; **aucune valeur réelle**
- *(éventuel)* `README.md` racine §3/§4 — mention du shell dashboard livré (#14)

**À lire (contexte) :** `web-dashboard/README.md`, `app/{layout,page}.tsx`, `src/domain/site.ts`,
`tsconfig.json`, `next.config.ts`, `vitest.config.ts`, `.env.example` ;
`docs/adr/0002`, `0007`, `0008`, `0011`, `0013`, `0015` ;
`specs/connexion-telephone-email-jwt.md`, `specs/middleware-autorisation-rbac.md` ;
`prd-coiflink.md` §4.1, §7.2, §11.2, §12.1.

## API / Interface Changes

- **API backend : none.** #14 **consomme** `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`
  (livrés #10/#12) sans les modifier.
- **Nouvelles routes web (adapter entrant Next.js) — internes au paquet `web-dashboard/` :**
  - Pages : `/login` (publique), `/gerant` (protégée, dashboard vide), + pages de sections « À venir »
    (protégées) le cas échéant.
  - *(Option A)* Route Handlers BFF : `POST /api/auth/login`, `POST /api/auth/logout`
    (+ `POST /api/auth/refresh` en suivi). Ce sont des **routes de l'application web**, pas des
    endpoints publics de la plateforme ; à documenter dans `web-dashboard/README.md` (pas d'OpenAPI).
- **CLI / autres interfaces réseau : none.**

## Data Model / Protocol Changes

- **Schéma / base de données : none.** #14 ne touche ni PostgreSQL ni migration ; il n'introduit aucun
  stockage persistant côté serveur.
- **Session côté client** *(Option A)* : sérialisation des jetons émis par le backend dans des
  **cookies `httpOnly` / `Secure` / `SameSite=Lax`** (jamais lisibles par le JS) — c'est un **format
  de transport local au web-dashboard**, pas un changement de protocole backend. Aucune PII n'est
  ajoutée au cookie au-delà des jetons émis par #10 (les claims JWT ne contiennent **aucune** PII —
  invariant #10/#12). *(Option B : jeton en mémoire/`localStorage` — voir Security.)*
- **Format des jetons inchangé** (ADR-0013) : le front les traite en opaques (il ne décode pas le JWT
  pour autoriser ; c'est `/auth/me` qui fait foi).

## Security & Privacy Considerations

Contraintes documentées touchées : **PRD §11.1** (auth), **§11.2** (autorisation/isolation — appliquée
côté serveur par #12, le front s'y conforme), **§11.3** (données personnelles), **§12.1** (dashboard
< 3 s), **ADR-0011** (secrets hors dépôt), **ADR-0013** (JWT sans PII).

- **Deny-by-default côté route.** `/gerant*` n'est rendu **que** sur session valide de rôle
  `MANAGER` `ACTIVE`, la décision reposant sur **`GET /auth/me`** (source de vérité serveur, rôle relu
  en base par #12) — jamais sur le seul décodage local d'un jeton. Le contenu privé ne doit **jamais**
  être envoyé à un visiteur non authentifié (préférer une garde **côté serveur** — Option A — au
  garde client sujet au « flash »).
- **Stockage des jetons.** Recommandation **cookie `httpOnly`/`Secure`/`SameSite=Lax`** (Option A) :
  les jetons ne sont **pas** exposés au JS (atténue le vol par XSS) et permettent la garde
  `middleware`/serveur. Si Option B (`localStorage`/mémoire) est retenue, **documenter** le risque
  XSS et l'absence de garde serveur. **Aucun jeton ne doit apparaître dans une URL, un log, ou un
  message d'erreur.**
- **Pas de secret dans le bundle client (ADR-0011).** Seules les variables `NEXT_PUBLIC_*` sont
  exposées au navigateur : elles ne contiennent **jamais** de secret. `JWT_SECRET` reste **côté
  backend** — le front ne le connaît pas et ne valide **pas** de signature. Toute variable ajoutée
  (`API_BASE_URL` serveur) est **non secrète** et documentée dans `.env.example` sans valeur réelle.
- **Aucune PII journalisée (§11.3).** `full_name`, `phone`, `email` (renvoyés par `/auth/me` pour
  l'affichage) ne doivent **jamais** être journalisés côté serveur Next ni côté client ; ne pas
  logguer l'en-tête `Authorization`, le corps de login, ni les cookies.
- **Réponses backend à honorer :** `401` → session expirée/absente → redirection connexion (ou refresh
  transparent en suivi) ; `403` → compte non `ACTIVE` ou rôle insuffisant → message générique / pas de
  contenu privé ; `429` (login) → message générique « trop de tentatives » (respecter `Retry-After`
  côté UX si affiché) ; `503` (`JWT_SECRET` non configuré) → état d'erreur maîtrisé, jamais de contenu
  privé. **Ne pas divulguer** le motif précis d'un refus.
- **Transport HTTPS** (terminaison TLS Railway, ADR-0011) : les cookies `Secure` supposent HTTPS ;
  `#14` ne gère pas la terminaison TLS. En local (`http://localhost`), prévoir le repli `Secure` non
  bloquant *(à confirmer côté implémentation)*.
- **CSRF** *(Option A)* : des cookies portant la session appellent une réflexion CSRF pour les
  mutations (`/api/auth/*`) ; `SameSite=Lax` couvre l'essentiel des cas GET, mais les `POST` de
  login/logout doivent rester non exploitables (login ne dépend pas d'une session existante ; logout
  idempotent). **À valider** à l'implémentation.
- **Budget < 3 s (§12.1)** : la garde ajoute **un** appel `/auth/me` au premier rendu du dashboard —
  impact négligeable ; éviter les appels réseau dans le `middleware` edge (garde « présence » seule).

## Testing Plan

Test gate : **`npm test`** (Vitest, `vitest run` ; `test/**/*.test.ts`, #6). Les suites existantes
(`test/site.test.ts`) doivent **rester vertes** ; `npm run lint` propre ; `npm run build` (standalone)
doit passer (job `web` de la CI, `.github/workflows/ci.yml`).

- **Unitaires — domaine (pur, sans React/réseau) :**
  - `auth/session` : `canAccessGerant` → `true` pour `{ role: MANAGER, status: ACTIVE }` ; `false`
    pour `ADMIN`/`CLIENT`/`HAIRDRESSER` et pour un `MANAGER` non `ACTIVE`.
  - `navigation/sections` : la liste contient les sections §7.2 attendues, `/gerant` marquée
    `available`, les autres `coming-soon` ; `href` non vides et uniques.
- **Unitaires — application (cas d'usage avec `AuthGateway` fake) :**
  - `require-manager-session` : `getCurrentUser` → gérant actif ⇒ `{ allow: true }` ; `null` (`401`)
    ⇒ `{ allow: false, reason: "unauthenticated" }` ; utilisateur d'un autre rôle ⇒
    `{ allow: false, reason: "wrong-role" }` ; indisponibilité (`503`) ⇒
    `{ allow: false, reason: "unavailable" }`.
- **Unitaires — adapter API (`fetch` mocké) :**
  - `http-auth-gateway` : `getCurrentUser` mappe `200`→user, `401`/`403`→`null` ; `login` mappe
    `200`→succès, `401`→échec générique, `429`→« trop de tentatives » ; **assertion de non-fuite** :
    aucun log ne contient jeton/mot de passe/PII.
- **Composants / garde (selon l'outillage retenu) :** vérifier que `DashboardShell` rend la
  navigation depuis `sections.ts` et le bouton Déconnexion ; que `LoginForm` affiche une erreur
  générique sur échec. *(Si l'environnement de test composant React n'est pas encore configuré dans
  le paquet, prévoir sa mise en place minimale — jsdom/testing-library — ou couvrir la logique de
  garde au niveau cas d'usage ; à confirmer.)*
- **Comportement de garde (au niveau testable sans navigateur) :** privilégier des tests sur
  `require-manager-session` (décision) plutôt que sur les internes de Next ; documenter que la
  redirection effective (`redirect()`/`middleware`) est un **détail d'adapter** couvert par revue +
  build.
- **Non-régression :** `test/site.test.ts` reste vert ; `npm run build` réussit (SSR du layout
  `/gerant`).
- **e2e navigateur : hors périmètre** (pas d'infra Playwright/Cypress ; suivi possible M6).

## Documentation Updates

- **`web-dashboard/README.md`** — nouvelle section « Dashboard gérant » : arborescence des routes
  (`/login`, `/gerant`, sections « À venir »), fonctionnement de la **garde d'authentification**
  (middleware « présence » + vérification `/auth/me` côté serveur), stockage de session retenu
  (cookie httpOnly — Option A), variables d'environnement (`NEXT_PUBLIC_API_BASE_URL`, +
  `API_BASE_URL` si ajoutée), et **« comment ajouter une section »** (ajouter une entrée à
  `navigation/sections.ts` + une page sous `app/(gerant)/gerant/...`).
- **`web-dashboard/.env.example`** — documenter toute variable ajoutée (non secrète, sans valeur
  réelle) ; rappeler que `NEXT_PUBLIC_*` est exposé au navigateur.
- **`README.md` (racine)** *(optionnel)* — §3/§4 : signaler le **shell du dashboard gérant** livré
  (#14) et la structure « une app Next.js, zones par rôle ».
- **ADR** — *a priori* **aucun nouvel ADR requis** : le shell découle directement d'ADR-0002 (Next.js)
  et ADR-0007 (une app, zones par rôle). **Si** une décision structurante est actée (stockage de
  session par cookie httpOnly / pattern BFF), envisager un ADR léger (`docs/adr/00xx-*`) indexé dans
  `docs/adr/README.md` — **à confirmer** (voir Open Questions).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).

## Risks and Open Questions

1. **Stockage des jetons & emplacement de la garde** *(structurant — à trancher)* : **cookie
   httpOnly + BFF + middleware/layout serveur** (Option A, recommandée : sûr, pas de flash) **vs**
   jeton client + garde `useEffect` (Option B : plus simple, mais flash + XSS + pas de garde serveur).
   Décision à acter (et éventuellement ADR léger).
2. **Périmètre de l'écran de connexion** *(à confirmer)* : #14 livre-t-il un **login minimal
   technique** (juste assez pour établir une session et démontrer la garde) ou l'**UX de connexion
   aboutie** (design, « mot de passe oublié » relié à #11) est-elle une issue distincte ? Le BACKLOG
   ne liste pas d'issue « écran de connexion web » explicite — à clarifier pour ne pas sur/sous-livrer.
3. **Comportement pour un rôle authentifié non gérant** *(à confirmer)* : `ADMIN`/`CLIENT`/
   `HAIRDRESSER` arrivant sur `/gerant` — **redirection** vers `/login` (ou une future racine par
   rôle) **vs** page « accès refusé » dédiée. Recommandation : redirection simple pour le squelette,
   `/admin` étant hors périmètre. À noter : **aucune route ne crée d'`ADMIN`** aujourd'hui (#12,
   Risk 3), et il n'existe pas d'écran de connexion mobile/coiffeur ici — le cas « autre rôle » reste
   surtout théorique au MVP.
4. **Refresh automatique du jeton** *(portée)* : traiter un `401` comme « session expirée →
   redirection » (simple, recommandé pour #14) **vs** rafraîchir de façon transparente via
   `POST /auth/refresh` (meilleure UX, plus de code). Recommandation : **différer** le refresh
   transparent en suivi.
5. **Deux URL backend (serveur vs navigateur)** *(à confirmer)* : en Option A, faut-il une
   `API_BASE_URL` **serveur** distincte de `NEXT_PUBLIC_API_BASE_URL` (réseau interne Railway) ? Par
   défaut, une seule URL publique ; ajouter la variable serveur seulement si la topologie l'exige.
   Impacte CORS (Option B) vs same-origin (Option A).
6. **Infra de test des composants React** *(à confirmer)* : le paquet n'a aujourd'hui que des tests
   Vitest **TS pur** (`test/**/*.test.ts`, sans jsdom). Tester des composants/gardes React peut
   nécessiter d'ajouter `jsdom` + Testing Library et d'élargir `include`. Alternative : concentrer les
   tests sur les cas d'usage/domaine (recommandé pour un squelette) et couvrir l'UI par revue + build.
7. **CSRF / cookies** *(Option A, à valider)* : `SameSite=Lax` + `POST` de login/logout non
   exploitables — vérifier qu'aucune mutation sensible ne repose sur un `GET` porteur de cookie.
8. **Navigation « À venir »** *(portée)* : matérialiser les sections §7.2 par des **pages vides**
   dédiées (plus de fichiers) **vs** des liens **désactivés** dans la nav (plus léger). Recommandation :
   liens désactivés / une page générique « À venir », pour rester au niveau squelette.
9. **Alignement avec #15** : la création de salon (#15) dépend de #14 et supposera qu'un gérant
   fraîchement inscrit **sans salon** atteint quand même le dashboard (état « aucun salon »). #14 doit
   donc **ne pas** exiger l'existence d'un salon pour rendre `/gerant` (le dashboard vide est
   justement l'état de départ). À garder à l'esprit (pas de dépendance dure ici).

## Implementation Checklist

> Ordre hexagonal : domaine → application → adapters → routage/câblage → tests → docs.
> Vérifier régulièrement : `cd web-dashboard && npm run lint && npm test && npm run build`.

**Préalables (décisions à confirmer avant de coder)**
- [ ] Trancher **Option A (cookie httpOnly + BFF + garde serveur)** vs **Option B (jeton client)** —
      recommandation : **A** (risque 1).
- [ ] Trancher le **périmètre de l'écran de connexion** (login minimal vs UX aboutie) (risque 2).
- [ ] Trancher le comportement pour un **rôle non gérant** sur `/gerant` (risque 3).
- [ ] Décider **refresh transparent** ou non (par défaut : différé) (risque 4).
- [ ] Décider s'il faut une **`API_BASE_URL` serveur** distincte (risque 5) et l'infra de **test
      composant** (risque 6).

**Domaine (`src/domain/` — TS pur)**
- [ ] `auth/role.ts` (`Role`, `isManager`), `auth/session.ts` (`AuthenticatedUser`, `SessionState`,
      `canAccessGerant`) — alignés sur `UserResponse`/`Role` du backend, **sans jeton ni secret**.
- [ ] `navigation/sections.ts` (sections §7.2, `available`/`coming-soon`).
- [ ] Tests : `test/auth-session.test.ts`, `test/navigation-sections.test.ts`.

**Application (`src/application/`)**
- [ ] `ports/auth-gateway.ts` (`AuthGateway`), `ports/session-store.ts` *(Option A)*.
- [ ] `use-cases/require-manager-session.ts` (décision `allow`/`reason`).
- [ ] Test : `test/require-manager-session.test.ts` (gateway **fake** : gérant actif / `401` / autre
      rôle / `503`).

**Adapters (`src/adapters/`)**
- [ ] `api/http-auth-gateway.ts` (fetch backend, mapping `200/401/403/429/503` ; **aucun log** de
      jeton/mot de passe/PII) + `api/config.ts` (lecture des variables d'environnement).
- [ ] `ui/dashboard-shell.tsx`, `ui/nav.tsx`, `ui/login-form.tsx`.
- [ ] Test : `test/http-auth-gateway.test.ts` (mapping + non-fuite).

**Routage / câblage (`app/`, `middleware.ts`)**
- [ ] `middleware.ts` *(Option A)* : redirige `/gerant/:path*` vers `/login` si cookie de session
      absent (pas d'I/O réseau edge).
- [ ] `app/(gerant)/layout.tsx` (Server Component) : `require-manager-session` → `redirect`/rendu du
      shell ; gère `401`/`403`/`503` sans exposer de contenu privé.
- [ ] `app/(gerant)/gerant/page.tsx` : **dashboard vide protégé** (titre + zone vide).
- [ ] `app/login/page.tsx` : `<LoginForm>` (public) → redirection `/gerant` après succès.
- [ ] *(Option A)* `app/api/auth/login/route.ts` + `app/api/auth/logout/route.ts` : BFF, cookies
      httpOnly/Secure/SameSite=Lax ; effacement au logout.
- [ ] `app/page.tsx` : accueil (redirection ou liens `/login` / `/gerant`).

**Documentation**
- [ ] `web-dashboard/README.md` : section « Dashboard gérant » (routes, garde, stockage session,
      variables d'environnement, « comment ajouter une section »).
- [ ] `web-dashboard/.env.example` : documenter toute variable ajoutée (non secrète, sans valeur).
- [ ] *(optionnel)* `README.md` racine §3/§4 : shell dashboard livré (#14).
- [ ] *(si décision structurante actée)* ADR léger + entrée `docs/adr/README.md`.

**Vérification finale**
- [ ] `npm run lint` propre ; `npm test` vert (suites existantes incluses) ; `npm run build`
      (standalone) réussi.
- [ ] Relecture sécurité : aucun jeton/mot de passe/PII dans un log, une URL ou un message d'erreur ;
      aucun secret dans le bundle client (uniquement `NEXT_PUBLIC_*` non secrètes) ; le contenu de
      `/gerant` n'est jamais rendu à un non-authentifié ; **aucune signature IA** dans code/commits/PR.
