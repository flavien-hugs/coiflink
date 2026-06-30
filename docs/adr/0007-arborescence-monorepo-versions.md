# ADR-0007 : Arborescence du monorepo, versions de référence & application web unique

- **Statut** : Accepté
- **Date** : 2026-06-30
- **Décideurs** : équipe CoifLink
- **Issue** : #2
- **Référence PRD** : §10 (architecture), §11.2 (RBAC), §18 (Sprint 0)

## Contexte et problème

L'issue #2 matérialise l'**arborescence du monorepo** (`app-mobile/`, `web-dashboard/`, `backend/`).
Les ADR de stack (0001–0006, issue #1) ont **volontairement différé** trois points à #2 (cf.
[index ADR](./README.md)) :

1. **Versions de référence** des runtimes (Flutter/Dart, Node, Python ; PostgreSQL/Redis pour mémo) ;
2. **Arborescence de `web-dashboard/`** : une seule application Next.js **vs** deux applications
   séparées gérant/admin (ADR-0002 *Suivi*) ;
3. (pour mémo) la disposition interne des paquets, afin que les commandes de build/test soient réelles.

Ces choix doivent être figés pour débloquer #3 (données), #4 (CI) et #6 (test gate), qui présupposent
des paquets dotés de commandes de build/test exécutables.

## Options envisagées

- **Web — Option A : une application Next.js unique** avec zones protégées par rôle (`/gerant`,
  `/admin`). **Option B : deux applications séparées** (`web-dashboard/gerant/`, `web-dashboard/admin/`).
- **Versions — Option A : figer des versions de référence** (canal stable / LTS) dans les manifestes.
  **Option B : laisser flotter** les versions (résolues au moment du build).

## Décision

- **`web-dashboard/` = une seule application Next.js** (React, TypeScript, App Router) avec zones
  protégées par rôle (`/gerant`, `/admin`).
- **Versions de référence figées** (ancrées dans les manifestes des paquets) :

  | Runtime | Version de référence | Ancrage |
  | --- | --- | --- |
  | Flutter / Dart | canal **stable** / Dart **^3.12** | `app-mobile/pubspec.yaml` |
  | Node.js | **≥ 20** (LTS) | `web-dashboard/package.json` (`engines`) |
  | Python | **≥ 3.12** | `backend/pyproject.toml` (`requires-python`) |
  | PostgreSQL (mémo runtime) | **16** | — (pas de code en #2, cf. ADR-0004) |
  | Redis (mémo runtime) | **7** | — (pas de code en #2, cf. ADR-0004) |

- **Disposition des paquets** : `app-mobile/` (projet Flutter), `web-dashboard/` (projet Next.js),
  `backend/` (paquet importable `coiflink_api/` + `tests/`), chacun avec un `README.md` documentant
  build **et** test.

## Justification (compromis)

- **Une app web unique** : plus simple à outiller (un seul `package.json`, un seul build/CI), cohérente
  avec un **RBAC backend unique** (§11.2) qui porte déjà l'autorisation par rôle ; évite la duplication
  de configuration de deux apps au MVP. Compromis accepté : un découpage en deux apps reste possible
  ultérieurement si les besoins gérant/admin divergent fortement (nouvel ADR le remplacerait).
- **Versions de référence figées** : rend les commandes de build/test **reproductibles** et débloque la
  CI (#4) et le test gate (#6). On retient des canaux **stable / LTS** plutôt que des versions
  patch figées, pour limiter la maintenance tout en garantissant la compatibilité de l'outillage.
- **Compromis accepté** : ces versions sont des **références** susceptibles d'évoluer (montée de LTS) ;
  l'ancrage dans les manifestes documente l'intention sans interdire les mises à jour maîtrisées.

## Conséquences

- **Positives** : arborescence stable et débloquante pour #3/#4/#6 ; commandes de build/test réelles
  par paquet ; décision web tranchée et tracée.
- **Négatives / risques** : si la stack ou une version LTS change, les manifestes devront suivre ;
  l'unification web suppose un RBAC côté client soigné (issues M1).
- **Suivi** : alimente la CI (#4 — jobs séparés mobile/web/backend) et le câblage du test gate
  `MX_AGENT_TEST_CMD` (#6) ; n'arrête **pas** l'hébergeur ni les fournisseurs concrets (différés #4/#5,
  ADR-0005/0006).
