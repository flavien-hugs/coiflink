# app-mobile/ — Application mobile CoifLink (Flutter)

Application mobile **client** de CoifLink, conformément à
**[ADR-0001](../docs/adr/0001-app-mobile-flutter.md)** (Flutter · Dart · **Android prioritaire**,
iOS conservé). Initialisé en squelette (#2), le paquet porte depuis #18 sa **première brique
réseau** et l'écran de **recherche/liste des salons** (§7.1) ; la réservation, les disponibilités,
l'historique et les rappels restent à venir (issues M3→).

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

L'URL de l'API backend est **injectée au build** via `--dart-define=API_BASE_URL` (jamais codée en
dur, jamais un secret — #18, [ADR-0020](../docs/adr/0020-catalogue-salons-cote-client.md)). Défaut
`http://10.0.2.2:8000` : l'hôte de la machine de dev **vu depuis l'émulateur Android** (jamais
`localhost`, qui viserait l'émulateur lui-même).

```bash
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # émulateur Android
```

## Build & test

| Action | Commande |
| --- | --- |
| **Build** (Android, cible prioritaire) | `flutter build apk --dart-define=API_BASE_URL=https://api.coiflink.example` |
| **Test** (test gate, cf. #6) | `flutter test` |
| Analyse statique | `flutter analyze` |

## Catalogue de salons (#18)

Premier flux data du paquet (hexagonal, [ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) :

- `domain/salon/salon_summary.dart` — entité de vitrine (`SalonSummary`, `isBookable` §8.3) ;
- `application/ports/salon_catalog_gateway.dart` — port `SalonCatalogGateway` (+ `SalonSearchQuery`,
  `SalonPage`, `SalonCatalogException`) ;
- `application/use_cases/search_salons.dart` — cas d'usage `SearchSalons` (normalisation, bornes) ;
- `adapters/data/api_config.dart` — `API_BASE_URL` via `--dart-define` ;
- `adapters/data/http_salon_catalog_gateway.dart` — `GET /catalog/salons` (`http`), mapping JSON →
  domaine ; **ne journalise ni URL signée ni PII** ;
- `adapters/ui/salon_search_screen.dart` + `widgets/salon_card.dart` — recherche (debounce), filtre
  ville, pagination incrémentale, états **chargement / vide / erreur**, badge « Réservable » /
  « Bientôt disponible » (§8.3).

Le domaine et les cas d'usage ne dépendent **pas** de Flutter ; seuls `adapters/ui` et `adapters/data`
importent `flutter`/`http`.
