# ADR-0002 : Interface web gérant / admin — Next.js (React)

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10.2 (Frontend web), §10.1 (interfaces gérant et admin), §12.1 (dashboard < 3 s)

## Contexte et problème

CoifLink comporte deux interfaces web : un **dashboard gérant** (salon, planning, prestations,
encaissements, employés, paramètres) et une **interface admin** (supervision des salons, support,
abonnements, KPI globaux). Le PRD §10.2 recommande « React.js / Next.js », un dashboard
**responsive** et une **interface simple adaptée aux gérants non techniques**, avec un budget de
chargement du dashboard principal **< 3 s** (§12.1). Il faut figer le framework web avant #2.

## Options envisagées

- **Option A — Next.js (React, TypeScript).** Framework React avec rendu serveur/statique (SSR/SSG),
  routage par fichiers, conventions intégrées.
- **Option B — React SPA pure (Vite / CRA).** Plus minimal, rendu 100 % côté client, à assembler
  soi-même (routeur, data-fetching, build).

## Décision

Les interfaces **gérant et admin** sont développées avec **Next.js (React, TypeScript)**.

## Justification (compromis)

- **Performance / budget de chargement** (§12.1) : le rendu serveur/statique de Next.js aide à
  tenir le « dashboard < 3 s », notamment au premier rendu, mieux qu'une SPA pure dépendante d'un
  gros bundle client.
- **Écosystème et DX** : routage par fichiers, conventions établies, vaste écosystème React, large
  vivier de talents ; productif pour bâtir des interfaces responsives destinées à des **gérants non
  techniques** (§10.2).
- **TypeScript** : typage statique pour fiabiliser des écrans métier (caisse, planning) à enjeu.
- **Compromis accepté** : Next.js ajoute un **surcoût de framework** (build, conventions SSR) par
  rapport à une SPA simple ; ce coût est accepté pour la performance, la structuration et la
  cohérence d'outillage entre les deux interfaces web.

## Conséquences

- **Positives** : socle web unique et performant pour gérant et admin ; budgets de perf plus
  faciles à tenir ; écosystème riche.
- **Négatives / risques** : courbe SSR/Next.js ; pas de partage de composants avec le mobile Flutter
  (ADR-0001).
- **Suivi / à confirmer (non bloquant)** :
  - **une application Next.js unique** avec zones protégées par rôle (gérant/admin) **vs deux
    applications séparées** — décision d'arborescence renvoyée à l'issue #2 ;
  - **versions** Node/Next.js à arrêter en #2 ;
  - l'autorisation par rôle s'appuiera sur le RBAC backend (§11.2, issues #10/#12).
