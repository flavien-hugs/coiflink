# ADR-0008 : Architecture hexagonale (ports & adapters) pour tous les paquets

- **Statut** : Accepté
- **Date** : 2026-06-30
- **Décideurs** : équipe CoifLink
- **Issue** : décision d'architecture transverse (suite de #2)
- **Référence PRD** : §10 (architecture), §11 (sécurité), §12 (performance)

## Contexte et problème

L'issue #2 a posé les trois paquets applicatifs (`backend/`, `web-dashboard/`,
`app-mobile/`) et leurs squelettes. Reste à fixer **comment le code est organisé
à l'intérieur** de chaque paquet, avant que la logique métier (jalon M1→) ne
s'installe. Sans règle commune, le métier finit couplé aux frameworks (FastAPI,
Next.js, Flutter) et aux I/O (PostgreSQL, Redis, S3, FCM/SMS — ADR-0004/0005/0006) :
testabilité dégradée, remplacement d'une brique coûteux, conventions divergentes
d'un paquet à l'autre.

## Décision

Adopter l'**architecture hexagonale (ports & adapters)** dans **tous** les
paquets. Trois couches, la dépendance allant toujours **vers l'intérieur** :

1. **domaine** — entités, objets-valeur, règles métier. Aucune dépendance
   framework/I/O.
2. **application** — cas d'usage orchestrant le domaine ; déclare ses besoins
   externes via des **ports** (interfaces). Dépend du domaine, jamais des adapters.
3. **adapters** — seule couche qui connaît les frameworks et l'I/O :
   - **entrants (driving)** : traduisent une sollicitation externe (HTTP, UI)
     vers l'application ;
   - **sortants (driven)** : implémentent les ports (persistance, cache,
     stockage, notifications).

Le **composition root** instancie les adapters et les injecte dans l'application.

### Déclinaison par paquet

| Paquet | domaine | application | adapters entrants | adapters sortants | composition root |
| --- | --- | --- | --- | --- | --- |
| `backend/` (FastAPI) | `coiflink_api/domaine/` | `coiflink_api/application/` (+ `ports/`) | `adapters/entrant/` (routers HTTP) | `adapters/sortant/` (Postgres, Redis, S3...) | `coiflink_api/main.py` |
| `web-dashboard/` (Next.js) | `src/domaine/` | `src/application/` | `app/` (routage Next.js) + `src/adapters/ui/` | `src/adapters/api/` (clients HTTP) | `app/` (layout/page) |
| `app-mobile/` (Flutter) | `lib/domaine/` | `lib/application/` | `lib/adapters/ui/` (écrans) | `lib/adapters/data/` (API, stockage local) | `lib/main.dart` |

Côté front (web/mobile), l'hexagonal est appliqué dans son **esprit** : isoler le
domaine et les cas d'usage du framework de présentation. Le routage Next.js
(`app/`) et `main.dart` jouent le rôle d'adapter entrant + composition root du
framework.

## Options envisagées

- **A — Hexagonal (retenu).** Découple métier / framework / I/O ; testable sans
  infra ; cohérent entre paquets.
- **B — Architecture en couches classique** (MVC/MVT, services + repositories
  sans ports). Plus familière, mais le métier tend à dépendre du framework et de
  l'ORM ; remplacer une brique coûte plus cher.
- **C — Aucune convention imposée** (libre par paquet). Rapide au départ,
  divergence garantie entre les trois paquets.

## Justification (compromis)

- **Testabilité** (test gate #6) : domaine et cas d'usage testables sans base ni
  réseau ; les tests d'ancrage actuels (`pytest`, `vitest`, `flutter test`)
  restent verts après restructuration.
- **Indépendance des briques** : les choix ADR-0004/0005/0006 (Postgres/Redis,
  S3, FCM/SMS) deviennent des **adapters sortants** interchangeables derrière des
  ports.
- **Sécurité** (PRD §11) : autorisation/validation dans le domaine/application,
  pas éparpillées dans les contrôleurs.
- **Coût initial** : surcoût de structure modéré ; au démarrage `domaine`/
  `application` sont quasi vides (assumé), et se remplissent au fil de M1→.

## Conséquences

- Le **backend** est restructuré dès maintenant : `/health` devient un adapter
  entrant (`adapters/entrant/sante.py`) et `main.py` est le composition root.
- **Web** et **mobile** reçoivent l'arborescence des couches + conventions
  (README par couche) ; le code métier s'y place à partir de M1.
- Complète l'**ADR-0007** (arborescence du monorepo) en fixant l'**organisation
  interne** de chaque paquet.
- Règle d'or : toute dépendance externe passe par un **port** + un adapter
  sortant ; aucune importation directe d'un client d'infrastructure depuis le
  domaine ou l'application.
