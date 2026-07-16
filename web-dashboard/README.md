# web-dashboard/ — Interface web gérant / admin CoifLink (Next.js)

Interface web **gérant** et **admin** de CoifLink, conformément à
**[ADR-0002](../docs/adr/0002-web-gerant-admin-nextjs.md)** (Next.js · React · TypeScript). Ce dossier
est un **squelette d'initialisation** (#2) : page d'accueil neutre, aucune fonctionnalité métier
(salons, planning, caisse, supervision → issues M2→).

> **Arborescence retenue (#2)** : **une seule application Next.js** avec zones protégées par rôle
> (`/gerant`, `/admin`) plutôt que deux applications séparées — plus simple à outiller pour le MVP et
> cohérent avec le RBAC backend unique (PRD §11.2). Décision tracée dans
> [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md) (cf. ADR-0002 *Suivi*).

## Architecture (hexagonale — [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

```
src/
  domain/         # entités, règles & config métier (TS pur — ex. site.ts)
  application/    # cas d'usage + ports
  adapters/
    ui/           # composants React (consommés par app/)
    api/          # clients HTTP vers le backend (driven)
app/              # routage Next.js = adapter entrant + composition root du framework
```

Le routage `app/` reste l'entrée Next.js ; le domaine et les cas d'usage vivent sous
`src/` et ne dépendent ni de React ni du réseau.

## Dashboard gérant : shell, navigation, garde d'authentification (#14)

Le shell de l'espace **gérant** (`/gerant`) fournit le layout (en-tête, navigation, zone de
contenu), la navigation vers les futures sections (PRD §7.2) et une **garde d'authentification**
(deny-by-default). Aucune fonctionnalité métier n'est encore livrée : le dashboard est **vide mais
protégé** ; les sections Planning, Clients, Encaissements, Employés sont affichées
« à venir » (M2–M5). Les sections **Paramètres** (#15) et **Prestations** (#17) sont **disponibles**
(voir ci-dessous).

### Routes

| Route | Accès | Rôle |
| --- | --- | --- |
| `/` | publique | — (accueil neutre + lien vers `/gerant`) |
| `/login` | publique | point d'entrée de session (formulaire minimal) |
| `/gerant` | **protégée** | `MANAGER` actif uniquement (dashboard vide) |
| `/gerant/parametres` | **protégée** | `MANAGER` — création/consultation du salon (#15) |
| `/gerant/prestations` | **protégée** | `MANAGER` — catalogue et gestion des prestations (#17) |
| `POST /api/auth/login` | interne (BFF) | proxifie `POST /auth/login`, pose les cookies httpOnly |
| `POST /api/auth/logout` | interne (BFF) | efface les cookies de session |
| `POST /api/salons` | interne (BFF) | proxifie `POST /salons` (jeton lu du cookie httpOnly) |
| `GET /api/salons` | interne (BFF) | proxifie `GET /salons` (salons du gérant) |
| `PUT /api/salons/[id]/opening-hours` | interne (BFF) | proxifie `PUT /salons/{id}/opening-hours` (horaires, #16) |
| `GET /api/salons/[id]/services` | interne (BFF) | proxifie `GET /salons/{id}/services` (catalogue, #17) |
| `POST /api/salons/[id]/services` | interne (BFF) | proxifie `POST /salons/{id}/services` (création, #17) |
| `PUT /api/salons/[id]/services/[serviceId]` | interne (BFF) | proxifie `PUT /salons/{id}/services/{id}` (modification journalisée, #17) |
| `DELETE /api/salons/[id]/services/[serviceId]` | interne (BFF) | proxifie `DELETE …` (désactivation soft-delete, #17) |

`/api/auth/*` sont des **routes de l'application web** (Backend-For-Frontend), pas des endpoints
publics de la plateforme : elles ne figurent donc pas dans l'OpenAPI backend.

### Garde d'authentification (Option A — cookie httpOnly + BFF)

1. **Connexion** : `LoginForm` poste vers `POST /api/auth/login`, qui appelle `POST /auth/login`
   (#10) et pose les jetons dans des cookies **`httpOnly` / `Secure` (prod) / `SameSite=Lax`** —
   jamais accessibles au JS du navigateur (atténue le vol par XSS).
2. **Garde « présence » (edge)** : `proxy.ts` (convention Next.js 16, ex-`middleware`) intercepte
   `/gerant*` et redirige vers `/login` si le cookie de session est **absent** (aucun appel réseau
   au niveau edge).
3. **Vérification réelle (serveur)** : le layout `app/(gerant)/layout.tsx` (Server Component)
   appelle **`GET /auth/me`** (#12, **source de vérité**) via le cas d'usage
   `require-manager-session`. Décision : session valide de rôle `MANAGER` actif → rendu du shell ;
   `401`/`403` ou rôle non gérant → `redirect(/login)` ; `503`/panne → état d'erreur maîtrisé. Le
   contenu privé n'est **jamais** envoyé à un visiteur non autorisé (pas de « flash »).
4. **Déconnexion** : `LogoutButton` poste vers `POST /api/auth/logout` (efface les cookies) puis
   redirige vers `/login`.

La présence d'un jeton ne suffit pas : c'est la réponse `200` de `/auth/me` (rôle relu en base côté
backend) qui autorise l'affichage. Le front traite le JWT en **opaque** (il ne le décode pas). Un
`401` est traité comme « session expirée → redirection » ; le rafraîchissement transparent via
`POST /auth/refresh` est un **suivi** (hors #14).

### Paramètres — création & consultation du salon (#15)

La section **Paramètres** (`/gerant/parametres`, Server Component) charge les salons du gérant **côté
serveur** (jeton lu du cookie httpOnly, jamais exposé au navigateur) :

- **aucun salon** → formulaire de création (`SalonForm`) qui poste vers `POST /api/salons` ;
- **un salon** → fiche « Informations générales / Localisation ».

Tant que `isBookable(salon) === false` (§8.3 : `ACTIVE` **et** horaires présents — parité stricte avec
`domain/salon.py`), un **bandeau** invite à configurer les horaires d'ouverture. Les médias
(logo/photos) transitent par des **URLs signées** côté backend ; le téléversement direct
navigateur→bucket exige que le bucket autorise l'origine du dashboard (**CORS**) — configuration
d'infrastructure, hors code.

### Paramètres — horaires d'ouverture (#16)

Sous la fiche du salon, l'**éditeur d'horaires** (`OpeningHoursForm`, client) présente les 7 jours
(bascule fermé/ouvert, un ou plusieurs intervalles = **pauses**) et une section **jours exceptionnels**
(date + fermé/horaires ponctuels). La saisie est **validée côté client** (`validateOpeningHours`,
`src/domain/salon/opening-hours.ts` — **parité stricte** avec `domain/opening_hours.py`) avant d'être
postée en `PUT /api/salons/[id]/opening-hours` (le **backend reste l'autorité**). En cas de succès la
page se rafraîchit : dès que `isBookable(salon)` devient vrai, le **bandeau §8.3 disparaît**. Le fuseau
(`Africa/Abidjan`) n'est pas éditable dans l'UI au MVP.

### Prestations — catalogue du salon (#17)

La section **Prestations** (`/gerant/prestations`, Server Component) est **disponible** depuis #17. Elle
charge **côté serveur** (jeton du cookie httpOnly, jamais exposé) le salon du gérant puis ses
prestations : sans salon, elle invite à en créer un d'abord (Paramètres) ; sinon elle affiche un
**formulaire d'ajout** (`ServiceForm`) et le **catalogue** (`ServiceList`) — prestations actives **et**
désactivées (badge « Désactivée »), avec **édition en ligne** et bouton **Désactiver**.

La saisie (nom, prix, durée, catégorie, description) est **validée côté client** (`validateService`,
`src/domain/service/service.ts` — **parité stricte** avec `domain/service.py` : prix `>= 0` borné et au
plus 2 décimales, durée entière `> 0` ≤ 24 h, nom non vide) avant d'être postée aux Route Handlers BFF
`POST/PUT /api/salons/[id]/services[/serviceId]` et `DELETE …` (désactivation). Le **backend reste
l'autorité** ; la modification et la désactivation y sont **journalisées §11.4**. Le catalogue **client
public** (#18/#19) et la **réservation** (#21+) restent hors périmètre.

### Ajouter une section

1. Ajouter une entrée à `src/domain/navigation/sections.ts`
   (`{ key, label, href, status, category }`).
2. Créer la page correspondante sous `app/(gerant)/gerant/<section>/page.tsx` et passer son
   `status` de `"coming-soon"` à `"available"`.
3. Si la section ne rentre dans aucune catégorie existante, ajouter la catégorie dans
   `DASHBOARD_SECTION_CATEGORIES`.

### Variables d'environnement

- **`NEXT_PUBLIC_API_BASE_URL`** — URL de base du backend, **exposée au navigateur** (jamais un
  secret).
- **`API_BASE_URL`** *(optionnelle, serveur uniquement)* — URL utilisée par les appels serveur
  Next (Route Handlers, layout `/gerant`) ; repli sur `NEXT_PUBLIC_API_BASE_URL` si absente. À
  définir seulement si le backend est joignable par une URL interne distincte. **Non secrète.**

Voir `.env.example`. `JWT_SECRET` reste **côté backend** : le front ne le connaît pas et ne valide
aucune signature.

## Prérequis

- **Node ≥ 20** (LTS ; version de référence figée par #2 — cf. champ `engines` et
  [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md)) et `npm`.

## Installation

```bash
cd web-dashboard
npm install
```

## Lancement (dev)

```bash
cp .env.example .env.local      # ignoré par git ; aucun secret committé
npm run dev                     # http://localhost:3000
```

## Build & test

| Action | Commande |
| --- | --- |
| **Build** | `npm run build` |
| **Test** (test gate web, cf. #6) | `npm test` (Vitest) |
| Lint | `npm run lint` |
| **Image Docker** (Next.js standalone ; build-seul en CI, non-root) | `docker build -t coiflink-web ./web-dashboard` |

## Configuration

Les variables sont lues depuis l'environnement (`.env.local`, ignoré par git). Voir `.env.example` ;
seules les variables préfixées `NEXT_PUBLIC_` sont exposées au navigateur (jamais un secret). Aucun
secret n'est committé (injection hors dépôt). Modèle d'environnements & politique de secrets :
**[docs/environnements-et-secrets.md](../docs/environnements-et-secrets.md)** (ADR-0011).
