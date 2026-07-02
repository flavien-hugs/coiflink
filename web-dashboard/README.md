# web-dashboard/ — Interface web gérant / admin CoifLink (Next.js)

Interface web **gérant** et **admin** de CoifLink, conformément à
**[ADR-0002](../docs/adr/0002-web-gerant-admin-nextjs.md)** (Next.js · React · TypeScript). Ce dossier
est un **squelette d'initialisation** (#2) : page d'accueil neutre, aucune fonctionnalité métier
(salons, planning, caisse, supervision → issues M1→).

> **Arborescence retenue (#2)** : **une seule application Next.js** avec zones protégées par rôle
> (`/gerant`, `/admin`) plutôt que deux applications séparées — plus simple à outiller pour le MVP et
> cohérent avec le RBAC backend unique (PRD §11.2). Décision tracée dans
> [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md) (cf. ADR-0002 *Suivi*).

## Architecture (hexagonale — [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

```
src/
  domaine/        # entités, règles & config métier (TS pur — ex. site.ts)
  application/    # cas d'usage + ports
  adapters/
    ui/           # composants React (consommés par app/)
    api/          # clients HTTP vers le backend (driven)
app/              # routage Next.js = adapter entrant + composition root du framework
```

Le routage `app/` reste l'entrée Next.js ; le domaine et les cas d'usage vivent sous
`src/` et ne dépendent ni de React ni du réseau.

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
