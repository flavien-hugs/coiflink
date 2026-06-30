# ADR-0001 : Application mobile — Flutter

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10.2 (Frontend mobile), §12.1 (performance)

## Contexte et problème

CoifLink livre une **application mobile client** (réservation, consultation des disponibilités,
historique, rappels). La cible prioritaire est **Android**, sur un marché (Afrique de l'Ouest,
Côte d'Ivoire) où une part importante des appareils est **entrée de gamme** (CPU/GPU modestes,
RAM limitée, surcouches OEM variées, réseau parfois dégradé). iOS est prévu en second lot, ou dès
le MVP si le budget le permet (§10.2). Le PRD recommande « Flutter **ou** React Native » sans
trancher : il faut figer la brique avant l'initialisation du dépôt (#2).

## Options envisagées

- **Option A — Flutter (Dart).** Rendu compilé AOT, moteur graphique propre (Skia/Impeller) qui
  dessine l'UI indépendamment des composants natifs de l'OEM.
- **Option B — React Native (JavaScript/TypeScript).** Rendu via composants natifs, pont JS,
  partage d'écosystème avec le web React/Next.js.

## Décision

L'application mobile est développée en **Flutter** (Dart), avec une base de code unique ciblant
**Android en priorité** puis iOS.

## Justification (compromis)

- **Cible Android entrée de gamme** : le rendu AOT compilé et le moteur graphique propre de Flutter
  donnent une UI **cohérente et fluide** sur des appareils modestes et hétérogènes, sans dépendre
  des surcouches OEM ni des versions de WebView/composants natifs.
- **Performance** (§12.1) : démarrage et rendu maîtrisés, animations à 60 fps atteignables même sur
  matériel limité ; pas de pont JS dans le chemin critique du rendu.
- **Écosystème** : widgets mûrs, tooling stable, large bibliothèque de paquets ; outillage de test
  intégré (`flutter test`).
- **Compromis accepté** : Dart est moins répandu que JavaScript et le **partage de code avec le web
  Next.js/React (ADR-0002) est moindre** qu'avec React Native. Ce coût (montée en compétence Dart,
  pas de mutualisation front mobile/web) est **accepté** au profit de la performance et de la
  cohérence d'UI sur Android bas de gamme, qui sont des facteurs de réussite terrain prioritaires.
- **Cohérence projet** : l'orientation `flutter test` comme exemple de test gate (README §7) et la
  numérotation `ADR 0001` étaient déjà esquissées dans l'historique ; cet ADR les matérialise.

## Conséquences

- **Positives** : une seule base mobile Android+iOS ; UI homogène et performante sur le parc cible.
- **Négatives / risques** : dépendance à l'écosystème Dart/Flutter ; pas de partage de composants
  avec le web ; à confirmer formellement, la **disponibilité de compétences Dart** dans l'équipe
  (sign-off non bloquant pour figer l'ADR, voir *Risks* de la spec).
- **Suivi** :
  - oriente le **test gate mobile** `flutter test` (issue #6) ;
  - fixe l'arborescence `app-mobile/` (issue #2) ;
  - oriente la **CI mobile** (build Android, issue #4) ;
  - **versions** de Flutter/Dart à arrêter en #2 (non figées ici).
