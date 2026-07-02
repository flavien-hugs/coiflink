# app-mobile/ — Application mobile CoifLink (Flutter)

Application mobile **client** de CoifLink, conformément à
**[ADR-0001](../docs/adr/0001-app-mobile-flutter.md)** (Flutter · Dart · **Android prioritaire**,
iOS conservé). Ce dossier est un **squelette d'initialisation** (#2) : il n'affiche qu'un écran
d'accueil neutre et n'implémente aucune fonctionnalité métier (réservation, disponibilités,
historique, rappels → issues M1→).

## Architecture (hexagonale — [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

```
lib/
  domain/         # entités & règles métier (Dart pur)
  application/    # cas d'usage + ports
  adapters/
    ui/           # écrans Flutter (app.dart → CoifLinkApp)
    data/         # API backend, stockage local (driven)
  main.dart       # composition root (réexporte CoifLinkApp pour les tests/outils)
```

La présentation vit dans `adapters/ui/` ; le domaine et les cas d'usage ne dépendent
pas de Flutter.

## Prérequis

- **Flutter SDK stable** (canal `stable`) ; contrainte Dart `^3.12` (cf. `pubspec.yaml`).
  Versions de référence figées par #2 — voir [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md).
- Pour `build apk` : Android SDK installé (cf. `flutter doctor`).

## Installation

```bash
cd app-mobile
flutter pub get
```

## Lancement (dev)

```bash
flutter run        # sur un émulateur / appareil connecté
```

## Build & test

| Action | Commande |
| --- | --- |
| **Build** (Android, cible prioritaire) | `flutter build apk` |
| **Test** (test gate, cf. #6) | `flutter test` |
| Analyse statique | `flutter analyze` |
