# ADR-0000 : Processus et gabarit des ADR

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10, §18 (Sprint 0 — « Choix technologiques », « Architecture technique »)

## Contexte et problème

Le dépôt est greenfield : aucune décision d'architecture n'est encore tracée. Le PRD §10 se
contente de **recommander** une stack et laisse plusieurs briques ouvertes sous forme
d'alternatives. Avant d'écrire du code (issue #2 et suivantes), il faut **figer** ces choix et,
surtout, **conserver la trace de leur justification** pour éviter de re-discuter les mêmes
arbitrages à chaque sprint.

Nous avons besoin d'un mécanisme léger, lisible aussi bien par les humains que par les agents du
pipeline ADW, pour enregistrer chaque décision d'architecture majeure et son compromis.

## Options envisagées

- **Option A — Architecture Decision Records (ADR) en Markdown, format MADR simplifié.** Un fichier
  par décision, versionné dans le dépôt, à côté du code.
- **Option B — Une page unique « Architecture » dans le README ou le wiki.** Centralisé, mais
  l'historique des décisions et leurs alternatives se diluent vite ; pas de granularité « une
  décision = un fichier » exigée par l'acceptation de l'issue #1.
- **Option C — Pas de traçabilité formelle** (décisions implicites dans le code / les commits).
  Écartée : l'issue #1 exige explicitement « un ADR par décision majeure dans `docs/adr/` ».

## Décision

Nous adoptons des **Architecture Decision Records (ADR)** au format **MADR simplifié**, en
**français**, stockés dans `docs/adr/`, à raison d'**un fichier par décision majeure**.

Conventions retenues :

- **Numérotation** : `NNNN` croissant à quatre chiffres (`0000`, `0001`, …), jamais réutilisé.
  Le numéro est attribué à la création et ne change plus.
- **Nom de fichier** : `NNNN-titre-en-kebab-case.md`.
- **Statuts** : `Proposé` → `Accepté` → `Remplacé par ADR-XXXX` (ou `Déprécié`). Un ADR n'est
  jamais supprimé ni réécrit : on crée un nouvel ADR qui remplace l'ancien et on bascule le statut
  de ce dernier sur `Remplacé par ADR-XXXX`.
- **Langue** : français (cohérent avec le PRD, le BACKLOG et le README).
- **Sections obligatoires** : Statut, Contexte et problème, Options envisagées, Décision,
  Justification (compromis), Conséquences.
- **Index** : `docs/adr/README.md` maintient un tableau `ADR | Titre | Statut | Issue`.

## Justification (compromis)

- **Coût de rédaction faible** : Markdown léger, pas d'outillage ni de dépendance ; un agent comme
  un développeur peut produire et lire un ADR sans contexte supplémentaire.
- **Écosystème** : le format MADR est largement connu ; il reste lisible sans rendu particulier.
- **Granularité** : « une décision = un fichier » satisfait directement le critère d'acceptation de
  l'issue #1 et garde chaque compromis isolé et révisable indépendamment.
- **Compromis accepté** : un peu de redondance entre ADR (chacun rappelle son contexte) et une
  discipline de numérotation à tenir manuellement, en échange d'une traçabilité durable.

## Conséquences

- **Positives** : chaque brique de stack est tracée avec son alternative et sa justification ;
  les agents ADW disposent d'une source de vérité stable pour les phases ultérieures.
- **Négatives / risques** : la cohérence de l'index et de la numérotation repose sur la
  discipline humaine/agent ; un lint Markdown pourra être ajouté en #4 (non bloquant ici).
- **Suivi** : ce gabarit s'applique aux ADR 0001–0006 (décisions de stack de l'issue #1) et à
  toute décision d'architecture future (p. ex. ADR de déploiement rattaché à #4/#5).
