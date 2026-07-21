# app-mobile/ — Application mobile CoifLink (Flutter)

Application mobile **client** de CoifLink, conformément à
**[ADR-0001](../docs/adr/0001-app-mobile-flutter.md)** (Flutter · Dart · **Android prioritaire**,
iOS conservé). Initialisé en squelette (#2), le paquet porte depuis #18 sa **première brique
réseau** et l'écran de **recherche/liste des salons** (§7.1). Depuis #22, le paquet porte aussi le
**tunnel de réservation client** (choix prestation → date → créneau → commentaire → confirmation) et
une **connexion cliente minimale** ; l'historique « Mes rendez-vous », la modification/annulation et
les rappels restent à venir (issues M3→).

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
  `SalonPage`, `SalonCatalogException`, `SalonNotFoundException`) ;
- `application/use_cases/search_salons.dart` — cas d'usage `SearchSalons` (normalisation, bornes) ;
- `adapters/data/api_config.dart` — `API_BASE_URL` via `--dart-define` ;
- `adapters/data/http_salon_catalog_gateway.dart` — `GET /catalog/salons` (`http`), mapping JSON →
  domaine ; **ne journalise ni URL signée ni PII** ;
- `adapters/ui/salon_search_screen.dart` + `widgets/salon_card.dart` — recherche (debounce), filtre
  ville, pagination incrémentale, états **chargement / vide / erreur**, badge « Réservable » /
  « Bientôt disponible » (§8.3).

Le domaine et les cas d'usage ne dépendent **pas** de Flutter ; seuls `adapters/ui` et `adapters/data`
importent `flutter`/`http`.

## Fiche salon — consultation (#19, [ADR-0021](../docs/adr/0021-consultation-salon-cote-client.md))

Extension hexagonale de la couche #18 : taper une carte de la liste ouvre la **fiche de détail** d'un
salon.

- `domain/salon/salon_detail.dart`, `salon_service.dart`, `opening_hours.dart` — entités de détail
  (identité + `phone` + localisation + horaires + prestations + photos + `isBookable`), pures ;
- `application/ports/salon_catalog_gateway.dart` — méthode `getSalon(String id)` ; un `404` remonte en
  `SalonNotFoundException` (état « introuvable » distinct d'une erreur réseau) ;
- `application/use_cases/get_salon_detail.dart` — cas d'usage `GetSalonDetail` ;
- `adapters/data/http_salon_catalog_gateway.dart` — `GET /catalog/salons/{id}`, mapping JSON →
  `SalonDetail` (services, `opening_hours`, photos) ;
- `adapters/ui/salon_detail_screen.dart` + `widgets/opening_hours_view.dart`,
  `widgets/service_list_tile.dart` — en-tête (logo, nom, localisation, badge `isBookable`), horaires
  par jour, prestations + **prix**, téléphone, et le **point d'entrée réservation** : un bouton
  « Réserver » **dérivé de `isBookable`** (désactivé « Bientôt disponible » si `false`) qui ouvre le
  **tunnel de réservation** (#22) quand un lanceur est câblé, ou reste inerte sinon (contextes/tests
  sans réservation) ; états **chargement / introuvable / erreur** ;
- **navigation** : `salon_card` devient cliquable → `Navigator.push` vers la fiche (l'app n'avait
  jusqu'ici que l'écran de recherche).

La « disponibilité » de la fiche se limite à `isBookable` (§8.3) + affichage des horaires ; le
**calcul de créneaux libres** est consommé par le tunnel de réservation (#22, ci-dessous).

## Réservation client (#22, [ADR-0024](../docs/adr/0024-reservation-cote-client.md))

Tunnel de réservation guidé branché sur le bouton « Réserver » de la fiche, au-dessus des endpoints
livrés par #21 (`GET /catalog/salons/{id}/availability` **public** et `POST /salons/{id}/appointments`
client) — **backend inchangé**. Découpage hexagonal :

- `domain/appointment/appointment.dart`, `availability_slot.dart`, `appointment_status.dart` — value
  objects purs + `enum AppointmentStatus` (mapping `PENDING → « En attente »`, valeur inconnue tolérée) ;
- `application/ports/appointment_gateway.dart` — port `AppointmentGateway` (+ `BookingDraft` et
  exceptions **neutres** `AppointmentGatewayException` / `SlotTakenException` / `NotBookableException`
  / `UnauthorizedException`) ; `application/ports/auth_gateway.dart`, `token_store.dart`,
  `application/auth_session.dart` — connexion cliente & session ;
- `application/use_cases/check_availability.dart`, `book_appointment.dart`, `sign_in.dart` — cas
  d'usage (validations amont : date non passée, ≥ 1 prestation) ;
- `adapters/data/http_appointment_gateway.dart`, `http_auth_gateway.dart` — adapters HTTP (mapping
  JSON → domaine, codes `201`/`401`/`409`/`404`/réseau, en-tête `Authorization: Bearer`) ;
- `adapters/ui/booking/` (tunnel + confirmation) et `adapters/ui/auth/login_screen.dart` — écrans.

**Prérequis session** : le `POST` exige un JWT client (`APPOINTMENT_BOOK`). Le tunnel demande une
connexion (`POST /auth/login`) au moment de confirmer si aucune session n'est active. Le jeton vit
derrière un port `TokenStore` — implémentation **en mémoire** au MVP (session perdue au redémarrage ;
bascule vers un magasin sécurisé de plateforme = simple remplacement d'implémentation, ADR-0024).

**Portée MVP** : **une seule** prestation par réservation (cohérent avec la disponibilité
mono-`service_id`), réservation **au niveau salon** (pas de coiffeur), horizon de date de **30 jours**,
repère **Africa/Abidjan (UTC+0)**. Statut initial **« En attente »** affiché depuis la réponse du `POST`.

**Garde-fous (§11)** : le corps de réservation n'envoie **jamais** `client_id`/`salon_id`/`status`
(imposés serveur) ; aucun jeton, URL, corps ni PII n'est **journalisé** ; les exceptions portent des
messages **génériques**. Un `409` créneau pris → retour à l'étape créneaux rafraîchie ; un `401` →
reconnexion.
