# Contribuer à CoifLink

Merci de contribuer à CoifLink. Ce document décrit les **conventions de contribution** du dépôt :
messages de commit, rôle du pipeline ADW, langue et décisions d'architecture.

## Langue

Le dépôt est rédigé en **français** : PRD, BACKLOG, README, ADR, specs et documentation. Les
**licences standard** restent dans leur forme d'origine.

**Le code est nommé en anglais.** Tous les identifiants — modules/fichiers source, classes,
fonctions, méthodes, variables, constantes, énumérations, fixtures et noms de tests — sont en
**anglais**, dans tous les paquets (`backend/`, `web-dashboard/`, `app-mobile/`). Exemples :
`domain/`, `adapters/inbound/`, `RegisterClient`, `normalize_phone`, `PhoneAlreadyInUse`.
Les **docstrings, commentaires, messages d'erreur destinés aux utilisateurs** et la documentation
restent en français. Ne pas introduire de nouveau nom français dans le code ; si un identifiant
français subsiste, le renommer en anglais à l'occasion d'une modification du fichier concerné.

## Conventions de commits — Conventional Commits

Les messages de commit suivent la spécification **[Conventional Commits](https://www.conventionalcommits.org/fr/)** :

```
<type>(<portée optionnelle>): <description à l'impératif>
```

**Types utilisés :**

| Type | Usage |
| --- | --- |
| `feat` | nouvelle fonctionnalité |
| `fix` | correction de bug |
| `docs` | documentation uniquement |
| `chore` | maintenance, outillage, dépendances (sans impact fonctionnel) |
| `ci` | intégration continue / pipeline |
| `refactor` | refactorisation sans changement de comportement |
| `test` | ajout ou modification de tests |

**Règles :**

- Description courte, à l'**impératif présent** (« ajoute », « corrige »), sans point final.
- **Portée** optionnelle entre parenthèses (p. ex. `feat(backend):`, `docs(adr):`).
- Référencer l'**issue** concernée quand c'est pertinent (p. ex. `(#2)`).
- Un corps de message facultatif explique le *pourquoi* si nécessaire.

Exemples (cohérents avec l'historique) :

```
docs: ADR de la stack technique (#1)
feat: pivot vers CoifLink + backlog MVP et outillage ADW
ci: add adw_sdlc GitHub Actions workflow
```

## Git / GitHub : détenus par le pipeline ADW

La livraison passe par le **pipeline ADW** ([`adw_sdlc/`](./adw_sdlc/)), qui **détient l'intégralité
des opérations git/gh** : création des branches de travail (`ci/<n>-<adwid>-<slug>`), commits, ouverture
et fusion des pull requests. Les contributeurs (humains comme agents) ne créent ni ne poussent de
branche, ni n'ouvrent de PR manuellement dans le cadre d'un run ; les conventions ci-dessus cadrent les
messages produits.

## Décisions d'architecture

Toute décision d'architecture majeure est tracée par un **ADR** dans [`docs/adr/`](./docs/adr/) (format
et processus : [ADR-0000](./docs/adr/0000-processus-et-gabarit-adr.md)). Les ADR sont la **source de
vérité de la stack** ; ne pas réécrire un ADR existant — en créer un nouveau qui le remplace.

## Secrets

Ne **jamais** committer de secret (clé, mot de passe, jeton, DSN avec identifiants réels). Seuls les
fichiers `*.env.example` (placeholders non secrets) sont versionnés ; les `.env` réels sont ignorés par
git. La **gestion des secrets hors dépôt** (magasin de la plateforme, injection par variables
d'environnement, rotation, conduite en cas de fuite, non-journalisation) est décrite dans
**[docs/environnements-et-secrets.md](./docs/environnements-et-secrets.md)** (décision :
[ADR-0011](./docs/adr/0011-deploiement-environnements-secrets.md)).

## Build & test par paquet

Voir le [README](./README.md) (section « Build & test par paquet ») et le `README.md` de chaque paquet
(`app-mobile/`, `web-dashboard/`, `backend/`) pour les commandes de build et de test.
