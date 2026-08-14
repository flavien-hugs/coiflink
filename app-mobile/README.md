# app-mobile/ — CoifLink Borne (Flutter)

Application **terminal libre-service** de CoifLink : le parcours walk-in d'une borne tactile en salon
(jalon **M7**, PRD §17, US-8.5 / #159). Conforme à
**[ADR-0001](../docs/adr/0001-app-mobile-flutter.md)** (Flutter · Dart · **Android prioritaire**, iOS
conservé). Un client se présente sans rendez-vous, s'identifie par téléphone, choisit une ou plusieurs
prestations et repart avec un ticket de passage imprimé — sans jamais créer de session personnelle.

Ce paquet n'a **qu'un seul mode** : il n'existe pas d'app cliente (recherche de salon, réservation, « Mes
rendez-vous », reçus) dans ce dépôt — ces parcours vivent côté web ([`web-dashboard/`](../web-dashboard/))
et, pour le client final, restent hors périmètre de ce paquet.

## Architecture (hexagonale — [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

```
lib/
  domain/         # entités & règles métier (Dart pur)
  application/    # cas d'usage + ports
  adapters/
    ui/terminal/     # écrans Flutter du parcours borne (terminal_app.dart → TerminalApp)
    data/         # API backend (driven)
  main.dart       # composition root, point d'entrée unique
```

La présentation vit dans `adapters/ui/`, la couche réseau dans `adapters/data/` ; le domaine et les cas
d'usage ne dépendent pas de Flutter.

## Prérequis

- **Flutter SDK stable** (canal `stable`) ; contrainte Dart `^3.12` (cf. `pubspec.yaml`).
  Versions de référence figées par #2 — voir [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md).
- Pour `build apk` : Android SDK installé (cf. `flutter doctor`).

## Installation

```bash
cd app-mobile
flutter pub get
```

## Lancement (dev) & build

Un seul indicateur de compilation, injecté via `--dart-define` (jamais codé en dur —
`adapters/data/api_config.dart`) : l'APK borne est **unique pour toutes les bornes**, il ne porte aucun
secret ni identifiant de device — ceux-ci sont obtenus **à l'exécution**, une seule fois, par l'écran
d'activation (voir section suivante).

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `API_BASE_URL` | URL de l'API backend | `http://10.0.2.2:8000` (hôte de dev vu depuis l'émulateur Android) |

```bash
# Lancement dev (même APK pour toutes les bornes ; active-la au premier lancement, voir plus bas)
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000

# Build APK borne
flutter build apk --dart-define=API_BASE_URL=https://api.coiflink.example

# Override de dev local uniquement (prévisualiser l'écran d'accueil sans activation) :
# salon figé en dur, aucune route réservée au rôle TERMINAL ne fonctionne (identification/ticket échouent).
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000 --dart-define=TERMINAL_SALON_ID=<uuid>
```

| Action | Commande |
| --- | --- |
| Test (test gate, cf. #6) | `flutter test` |
| Analyse statique | `flutter analyze` |

## Activation (une seule fois) puis authentification silencieuse

L'APK borne est **unique pour toutes les bornes** : il ne contient aucun secret ni identifiant de device.
Au tout premier lancement, `TerminalBootstrap` constate l'absence de credential stocké
(`TerminalCredentialStore.read()` renvoie `null`) et affiche `TerminalActivationScreen` — un pavé numérique
interne (jamais le clavier natif) pour saisir le **code d'activation à 6 chiffres** remis par le gérant
(lu sur la réponse de provisioning côté backend, `POST /salons/{id}/terminal-devices`, hors périmètre de ce
paquet). Ce code s'échange **une seule fois** contre le credential longue durée de la borne
(`TerminalActivationGateway.activate`, `POST /auth/terminal/activate`, route publique comme `/auth/terminal/login`)
puis se persiste localement (`SecureTerminalCredentialStore`, Android Keystore / iOS Keychain via
`flutter_secure_storage`) — la borne ne redemandera plus jamais ce code, y compris après redémarrage.

À chaque lancement suivant (credential déjà stocké), la borne s'authentifie **silencieusement**, sans
interaction utilisateur : `TerminalDeviceSession` échange le credential persisté contre un jeton via
`POST /auth/terminal/login`. Ce credential appartient au **terminal**, jamais à un client de passage ; il
n'existe **aucune notion de session personnelle** dans ce binaire (garantie structurelle : aucun écran de
connexion, aucun formulaire de mot de passe visible du client).

- Credential refusé (`401`, borne révoquée) → credential **effacé** localement, retour à
  `TerminalActivationScreen` (rien d'autre à réparer depuis l'écran : la borne doit être réactivée avec un
  nouveau code).
- Échec réseau/serveur → `TerminalUnavailableScreen` (message neutre, bouton Réessayer) ; le credential
  stocké est **conservé** (il est peut-être toujours valide, c'est le serveur qui est momentanément
  indisponible).
- Succès → le `salon_id` de la borne provient de la réponse du login (aucune valeur de salon compilée en
  dur) → écran d'accueil.

Voir `adapters/ui/terminal/terminal_bootstrap.dart` (widget public, testable directement, machine à 4 états :
chargement / activation / indisponible / prêt), `adapters/ui/terminal/terminal_activation_screen.dart` et
`application/terminal_device_session.dart`.

## Parcours borne (`lib/adapters/ui/terminal/`)

`terminal_app.dart` (composition root) → `terminal_bootstrap.dart` (activation puis amorçage, ci-dessus) puis,
huit écrans :

1. **Accueil** (`terminal_home_screen.dart`) — logo/nom du salon (repli sur
   `assets/images/terminal_logo_fallback.png`), CTA « Commencer ». Appui long caché sur le logo = geste de
   sortie (`terminal_exit_gate.dart`).
2. **Identification par téléphone** (`terminal_phone_identification_screen.dart` +
   `terminal_numeric_keypad.dart`, #156) — pavé numérique interne (jamais le clavier natif, §11.3).
   Fiche trouvée → affiche **le prénom seul** puis enchaîne **automatiquement** (aucune confirmation
   manuelle) ; fiche absente → création ; erreur réseau → réessai, **toujours en direct** (décision n°9).
3. **Création de fiche** (`terminal_create_customer_screen.dart`, #156) — prénom/nom/téléphone, **sans mot
   de passe**.
4. **Choix des prestations** (`terminal_service_selection_screen.dart` + `terminal_service_card.dart`, #158) —
   grille **2 colonnes fixes**, photo, sélection **multiple** (`service_ids` au pluriel, #157).
5. **Vérification** (`terminal_confirm_screen.dart`) — récapitulatif client + prestations avant tout appel
   réseau ; « Confirmer » crée le ticket (`POST /salons/{id}/queue/tickets`, #157), « Modifier mon choix »
   revient au choix de prestations sans rien avoir créé.
6. **Numéro de passage** (`terminal_ticket_number_screen.dart`) — numéro géant, heure, attente estimée ;
   écran de lecture pure, enchaîne seul vers l'impression après un court délai.
7. **Impression** (`terminal_print_screen.dart`, #160) — aperçu imprimable (`ticket_preview.dart`, bordure
   pointillée), séquence d'impression encadrée par le minuteur d'inactivité, message neutre par type
   d'échec (`PrinterNotConnected`/`OutOfPaper`/`WriteFailed`) — un échec d'impression **n'interrompt
   jamais** le parcours, le numéro reste affiché. « Terminer » revient à l'accueil.

`terminal_unavailable_screen.dart` couvre tout échec réseau bloquant (amorçage, catalogue) ;
`terminal_exit_gate.dart` pose le geste caché de sortie (PIN gérant, vérification non tranchée, §H — geste
**inerte** tant que la vérification n'est pas prête).

## Minuteur d'inactivité (`terminal_inactivity_guard.dart`, décision n°7)

Posé **une seule fois** via `MaterialApp.builder`, au-dessus du `Navigator` : 60 s sans interaction →
retour à l'accueil (`popUntil(isFirst)`), remise à zéro sur **toute** interaction (`Listener` translucide,
avant l'arène de gestes). **Suspendu** pendant l'impression du ticket, avec un **plafond de 15 s**
indépendant du signal de reprise (retour garanti même si le plugin d'impression plante), et pendant la
saisie du PIN gérant (`pauseForModal`).

## Ports & adaptateurs (hexagonal, [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

`application/ports/{terminal_activation,terminal_auth,terminal_identity,terminal_queue,salon_catalog,ticket_printer}_gateway.dart`
+ `application/ports/terminal_credential_store.dart`, implémentés respectivement par
`adapters/data/http_{terminal_activation,terminal_auth,terminal_identity,terminal_queue,salon_catalog}_gateway.dart`,
`adapters/data/noop_ticket_printer_gateway.dart` (place-tenant jusqu'à l'adaptateur ESC/POS de #160) et
`adapters/data/secure_terminal_credential_store.dart` (routes réservées au rôle **TERMINAL**, en-tête
`Authorization: Bearer` du device, jamais un jeton personnel — retry unique après ré-authentification sur
`401`, `adapters/data/terminal_http_retry.dart`). `application/terminal_device_session.dart` échange le
credential contre une session device et expose le `salon_id`.

## Garde-fous (§11)

Aucune PII à l'écran au-delà du **prénom** ; **aucun** nom/téléphone sur le ticket imprimé
(`TicketPrintPayload` : salon, numéro, date, prestations) ; identification et création de ticket
**toujours en direct** (jamais de mode dégradé, décision n°9) ; purge de fin de parcours par
**disposition de widgets** (rien n'est écrit hors du `State` de l'écran courant) ; le credential device
n'est **jamais** journalisé ni saisi directement à l'écran (seul le code d'activation à 6 chiffres, à usage
unique, l'est) — il est stocké **chiffré** sur l'appareil (Android Keystore / iOS Keychain via
`flutter_secure_storage`), jamais en clair, jamais compilé dans le binaire.
