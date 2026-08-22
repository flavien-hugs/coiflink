# Impression du ticket de passage sur imprimante thermique (US-8.6)

> Spécification de planification pour l'issue GitHub **#160 — US-8.6 : Impression du ticket sur
> imprimante thermique** (`feature` · Must · Effort M · jalon **M7 — Borne client (terminal
> libre-service)**, Épic 8). **Dépend de #157** (ticket de passage walk-in & estimation d'attente)
> **et #159** (mode terminal de l'application mobile). **Cette spec ne produit pas de code** : elle
> décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de classes, champs, symboles) inchangés. **Aucune signature IA**
> dans le code, les commits ou la PR.
>
> **État : implémenté.** §A/§B/§E/§F ont été livrés par #159 avant même le début de
> l'implémentation de #160. §C/§D (formateur pur, adaptateur matériel) ainsi que la sélection
> d'imprimante et le retry manuel (#171) sont maintenant livrés — voir `docs/adr/0042-file-attente-
> walkin-queue-ticket.md` §7 pour les décisions finales (certaines affinent les recommandations
> ci-dessous, notamment l'USB abandonné en V1 et la sélection d'imprimante par setup ponctuel, une
> question que cette spec n'avait pas résolue). Les annotations « **[livré]** » ci-dessous marquent
> les sections mises à jour ; le reste du document est conservé tel quel comme trace de la
> planification d'origine.

## Problem Statement

Le jalon **M7** (BACKLOG.md, promu depuis « Hors périmètre MVP » — PRD §17 « Borne Intelligente
d'Accueil ») livre le parcours du client **sans rendez-vous** sur une borne tactile physique en
salon. L'issue **#160** en est la dernière brique matérielle : une fois qu'un ticket de passage a
été créé (#157) et que la borne mobile (#159) affiche l'écran de confirmation, il faut **matérialiser
ce ticket sur papier**, sans intervention du personnel — c'est le second critère de sortie du
jalon (« … et reçoit un **ticket imprimé** »). Le critère d'acceptation exact de #160 est :

- **Le ticket imprimé contient salon, numéro, date, heure et prestation (US-007) ; un échec
  d'impression est signalé clairement au client sans bloquer le retour à l'accueil.**

(« US-007 » est le libellé porté par l'acceptation de l'issue #160 elle-même dans BACKLOG.md — une
recherche `US-0[0-9][0-9]` sur `prd-coiflink.md` ne retourne aucune occurrence : ce n'est **pas** un
renvoi vers une numérotation PRD préexistante, seulement l'étiquette interne de ce critère
d'acceptation. Cette spec ne lui invente pas de correspondance supplémentaire.)

### État actuel du dépôt — aucune impression physique n'existe nulle part

Une recherche exhaustive (`escpos|esc_pos|thermal|printer`, insensible à la casse) sur
`backend/coiflink_api`, `web-dashboard/src`, `app-mobile/lib` et `docs/` ne retourne **aucune**
occurrence en dehors des icônes/labels UI du reçu gérant (« Imprimer », `PrinterIcon`). Concrètement :

- **Web (gérant, reçu de paiement, PR #154/ADR-0040) — impression navigateur, pas matérielle.**
  `web-dashboard/src/adapters/ui/receipt-print-modal.tsx:177` déclenche `window.print()` ; le CSS
  `@media print` scopé à `.receipt-print-area` (`web-dashboard/app/globals.css:89-104`, largeur
  `80mm` ligne 101) n'est qu'une mise en page imprimée par le pilote d'imprimante du système
  d'exploitation — **aucun octet ESC/POS n'est émis par le code**. Le succès « imprimé » se déduit
  de l'évènement DOM `afterprint` (`receipt-print-modal.tsx:54-55`), documenté **explicitement**
  comme un signal *best-effort*, pas une confirmation matérielle (commentaire lignes 13-17,
  ADR-0040 §5 : « le navigateur ne peut pas savoir si le ticket est réellement sorti de
  l'imprimante thermique »).
- **Mobile (client, reçu de paiement, PR #154/ADR-0040 §6) — partage, pas impression.**
  `app-mobile/lib/adapters/ui/receipts/receipt_detail_screen.dart:1-7` documente en tête de fichier
  « **aucune** impression thermique réelle depuis le mobile » et n'expose qu'un bouton « Partager »
  via `SharePlus.instance.share` (ligne 24, paquet `share_plus`). ADR-0040 §6 le pose comme un choix
  assumé : « pas de SDK d'impression Bluetooth, hors périmètre » — **pour ce jalon précédent**. #160
  est précisément la levée de cette limite, mais **uniquement côté borne**, pas pour le client sur
  son propre téléphone (voir *Non-Goals*).
- **`app-mobile/pubspec.yaml:30-41`** (bloc `dependencies:`) ne déclare que quatre dépendances
  (`flutter` SDK, `cupertino_icons`, `http`, `share_plus`) : **aucun** paquet Bluetooth, USB ou
  ESC/POS.
- **`app-mobile/android/app/src/main/AndroidManifest.xml`** ne déclare **aucune** permission
  Bluetooth (`BLUETOOTH_CONNECT`/`BLUETOOTH_SCAN`) ni fonctionnalité USB host
  (`android.hardware.usb.host`) — seule une `<queries>` pour `ACTION_PROCESS_TEXT` existe.
- **Aucun `Timer`, écouteur d'inactivité ou geste global** n'existe dans `app-mobile/lib` (seule
  exception : un debounce de recherche sans rapport, `salon_search_screen.dart`) — le retour auto
  après impression (décision 7, voir *Risks*) reste entièrement à construire par #159.

### Ce que #160 ajoute, et ses dépendances amont

#160 introduit la **première** intégration matérielle du dépôt : un port `TicketPrinterGateway`
côté Flutter et un adaptateur ESC/POS, avec une gestion d'erreurs concrète (hors ligne, plus de
papier, échec d'écriture) et une UX qui ne bloque jamais le retour à l'accueil. Deux dépendances
amont sont **spécifiées par leurs specs sœurs** (leur implémentation reste à livrer) :

- **#157** (`specs/borne-ticket-file-attente-walkin.md`) définit le domaine `QueueTicket` —
  `ticket_number` en **entier brut**, séquentiel par salon et par jour, `service_ids` en liste
  (≥ 1), statut, ETA — et son endpoint « rejoindre la file ».
- **#159** (`specs/borne-app-mobile-mode-kiosque.md`) définit `main_terminal.dart`, les écrans borne
  sous `lib/adapters/ui/terminal/` et le timer d'inactivité (60 s, suspendu pendant l'impression) —
  l'écran de confirmation qui **appellera** l'impression y est spécifié, son implémentation restant
  à venir.

Pour ne pas coupler #160 au domaine `QueueTicket` de #157, cette spec propose de **découpler** le
port d'impression via un petit objet de transfert propre à #160 (voir *Proposed Implementation*
§A) — seul le contenu **minimal exigé par l'acceptation** (salon, numéro, date, heure, prestations)
traverse la frontière.

## Goals

- **Nouveau port `TicketPrinterGateway`** (application, Flutter, patron `ReceiptGateway`/
  `TokenStore`) exposant exactement les trois opérations demandées par l'issue : **`connect`**,
  **`print`**, **`status`** — indépendant de toute bibliothèque Bluetooth/USB/ESC-POS concrète
  (ADR-0008, hexagonale).
- **Objet de transfert `TicketPrintPayload`**, propre à #160, portant uniquement les cinq données
  exigées par l'acceptation (salon, numéro — en entier brut —, date, heure, prestations — en liste,
  le ticket pouvant en porter plusieurs) — **sans** dépendre du type `QueueTicket` de #157, pour
  rester stable si sa forme évolue avant livraison.
- **Un adaptateur ESC/POS concret** (Bluetooth ou USB), construit sur un paquet Flutter **encore à
  choisir et auditer** (voir *Proposed Implementation* §C) — pas de dépendance matérielle
  propriétaire figée dans le code métier (décision produit n°4).
- **Gabarit visuel du ticket dérivé de celui du reçu** (`ReceiptBody`,
  `receipt-print-modal.tsx:230-282`, CSS `80mm` de `globals.css:86-107`) — même **information**
  affichée (identité du salon centrée, séparateurs, contenu en colonnes, message de politesse), mais
  **traduit en commandes ESC/POS et en widget Flutter natif** ; aucune réutilisation de code React/
  CSS (deux plateformes distinctes).
- **Séparer le formatage (pur, testable) de l'entrée/sortie matérielle** (plugin, non testable en
  CI) : un formateur ESC/POS pur produit les octets à partir du `TicketPrintPayload`, l'adaptateur ne
  fait qu'établir la connexion et écrire ces octets — pattern déjà utilisé dans le dépôt pour séparer
  logique pure et effets de bord (ex. `_appointmentFromJson` pur dans un adaptateur HTTP).
- **Taxonomie d'erreurs matérielles concrète et neutre** (imprimante non connectée/non appairée,
  plus de papier, échec d'écriture), mappée en exceptions typées (patron
  `ReceiptGatewayException`/`UnauthorizedException`) — jamais une exception brute de plugin qui
  fuiterait jusqu'à l'UI.
- **UX non bloquante.** Un échec d'impression, quelle qu'en soit la cause, **n'empêche jamais** le
  retour à l'accueil de la borne (#159) ; le client voit un message clair, et son numéro reste
  affiché à l'écran indépendamment du résultat de l'impression papier.
- **Aucune promesse de confirmation matérielle fiable** — même limite documentée pour le reçu
  gérant (ADR-0040 §5) et le renoncement mobile (ADR-0040 §6), **aggravée** ici par le fait qu'une
  borne libre-service est **sans personnel présent** pour constater visuellement la sortie du
  papier (voir *Security & Privacy Considerations* et *Risks*).
- **Couverture de tests** : formatage ESC/POS pur (sans plugin ni matériel), mapping d'erreurs de
  l'adaptateur (via un faux transport), rendu de l'aperçu à l'écran — et une procédure de test
  **manuel sur device physique**, documentée pour nourrir la procédure de provisioning de #161.

## Non-Goals

**Hors scope de M7 dans son ensemble** (rappel, indépendant de #160) : vérification/check-in d'un
rendez-vous existant depuis la borne, identification par QR code ou code de réservation, affichage
temps réel des coiffeurs disponibles avant affectation, paiement autonome sur la borne.

**Hors scope spécifique de #160 :**

- **Le domaine `QueueTicket` et l'endpoint « rejoindre la file »** — livrés par #157. #160 ne
  consomme qu'un `TicketPrintPayload` déjà résolu par l'appelant (voir *Goals*) ; il ne définit ni
  numérotation, ni formule d'ETA, ni statut de ticket.
- **Les écrans borne, le point d'entrée `main_terminal.dart` et le timer d'inactivité** — livrés par
  #159. #160 fournit le port, l'adaptateur et un aperçu de ticket réutilisable ; il ne construit
  **aucun** écran d'accueil/identification/choix de prestation.
- **Le choix définitif et l'audit du paquet ESC/POS/Bluetooth/USB.** Cette spec **nomme des
  candidats réalistes** (§ Proposed Implementation C) mais **aucun n'est retenu, audité ni
  benchmarké** à ce stade — c'est une décision d'implémentation, pas un fait acquis.
- **Les imprimantes réseau (Wi-Fi/Ethernet).** La décision produit n°4 restreint le transport à
  **Bluetooth ou USB** ; une imprimante IP est hors périmètre (elle poserait d'ailleurs des
  questions réseau différentes — découverte, sécurité du LAN salon).
- **L'impression d'une image/logo (rendu bitmap).** Le gabarit repris de `ReceiptBody` est déjà
  **texte seul** (aucun logo) — #160 n'introduit pas de rendu raster ; le contenu du ticket reste du
  texte formaté (alignement, gras, tailles), cohérent avec le gabarit existant.
- **La réimpression, un historique ou un journal des tickets imprimés.** #160 imprime **une fois**
  au moment de la confirmation (#159) ; aucune fonctionnalité de retrouver/réimprimer un ticket plus
  tard n'est ajoutée.
- **Une alerte distante au tableau de bord gérant en cas de panne imprimante.** Voir *Risks* — #160
  ne modifie **aucune** route backend, n'introduit **aucune** notification serveur ; le signal de
  panne reste **local à la borne** dans cette itération.
- **La gestion complète des imprimantes appairées (écran de sélection, catalogue persistant de
  devices).** Le couplage borne↔imprimante est un geste de **provisioning**, plus proche du
  périmètre de #161 (« procédure de provisioning d'un device ») que d'une fonctionnalité applicative
  répétée par le client.
- **iOS.** La décision produit n°3 retient une tablette **Android** en boîtier terminal pour la V1 ;
  cette spec ne couvre pas de contraintes iOS (voir *Risks* pour une limite technique aggravante sur
  ce point : le Bluetooth classique (SPP), utilisé par la plupart des imprimantes thermiques
  génériques, n'est de toute façon pas accessible depuis une app iOS non certifiée MFi).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Mobile | Flutter, Dart, **Android prioritaire** | [0001](../docs/adr/0001-app-mobile-flutter.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/{ui,data}` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| Réservation client | `ApiConfig.fromEnvironment()`, DI manuelle dans `adapters/ui/app.dart` | [0024](../docs/adr/0024-reservation-cote-client.md) |
| Reçu — impression/partage | `window.print()` navigateur (gérant) ; `share_plus` (client) ; **aucune** impression thermique mobile | [0040](../docs/adr/0040-impression-recu-encaissement-gerant.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0040**. Le jalon M7 prévoit **deux ADR distinctes** (une
décision = une ADR, chacune committée avec la PR de sa fonctionnalité, cf. ADR-0039 avec #148 et
ADR-0040 avec #154) : `docs/adr/0041-authentification-borne-kiosque.md` (avec l'implémentation de
#155) et `docs/adr/0042-file-attente-walkin-queue-ticket.md` (avec l'implémentation de #157). Cette
spec ne propose **pas** d'ADR propre à #160 — ses décisions structurantes (choix de paquet,
taxonomie d'erreurs, absence de confirmation matérielle fiable) doivent être **versées dans
l'ADR-0042** (volet QueueTicket/walk-in) plutôt que dupliquées ; #161 vérifie la présence des deux
ADR et met à jour l'index `docs/adr/README.md` (voir *Documentation Updates*).

### Précédent le plus proche : impression du reçu (PR #154, ADR-0040)

- `web-dashboard/src/adapters/ui/receipt-print-modal.tsx:1-17` (commentaire d'en-tête) documente le
  choix `window.print()` + CSS `@media print`, et l'état « imprimé » déduit de `afterprint` (lignes
  50-56) comme un signal **best-effort**.
- `web-dashboard/src/adapters/ui/receipt-print-modal.tsx:230-282` (`ReceiptBody`) : gabarit visuel du
  ticket — nom du salon centré (police serif), numéro + date/heure centrés en gris, séparateurs
  pointillés (`border-t border-dashed`), lignes de prestation avec prix, total, mode de paiement,
  statut, référence optionnelle, message de politesse final. **C'est ce gabarit d'information (pas
  ce code) qui inspire le ticket borne** — en retirant tout ce qui est propre au paiement (total,
  mode de paiement, statut, référence, identité du client) puisque l'acceptation de #160 ne demande
  que salon/numéro/date/heure/prestation.
- `web-dashboard/app/globals.css:86-107` : la règle `@media print` masque tout sauf
  `.receipt-print-area`, fixée à `width: 80mm` (ligne 101) — confirme le standard 80mm déjà retenu
  implicitement par le produit, cohérent avec la décision n°4 (imprimante thermique 80mm générique).
- `backend/coiflink_api/domain/receipt.py:95-107` (`format_receipt_number`) formate un entier en
  `"REC-{n:06d}"` — **aucune** réutilisation directe possible (numérotation différente, propre au
  paiement), mais le **modèle direct** du formatage d'affichage du numéro de ticket, qui est la
  responsabilité de #160 : #157 transmet `ticket_number` en **entier brut** (voir §A), et c'est le
  formateur ESC/POS pur (§C) qui produit la forme affichée (« N° 014 », zéro-padding), sur le
  patron de `format_receipt_number`.
- **Mobile** : `app-mobile/lib/adapters/ui/receipts/receipt_detail_screen.dart:1-25` et
  `receipt_share_text.dart:1-29` — patron de **formatage pur, testable sans harnais widget**
  (`formatReceiptShareText`), à reproduire pour le formateur ESC/POS de #160 (voir §B/§C).

### Patrons Flutter à réutiliser tels quels

- **Port en `Protocol`/`abstract class` + exceptions neutres dédiées** :
  `app-mobile/lib/application/ports/receipt_gateway.dart:15-42` (`ReceiptGatewayException` racine,
  sous-classes `UnauthorizedException`/`ReceiptNotFoundException`, aucune ne transporte de PII, de
  jeton ni d'URL). #160 décline ce patron pour les pannes imprimante (§B).
- **Implémentation en mémoire d'un port stateful** :
  `app-mobile/lib/application/ports/token_store.dart:13-40` (`TokenStore` abstrait +
  `InMemoryTokenStore`) — patron direct pour un éventuel **faux imprimante** utilisé en test/dev
  (`NoopTicketPrinterGateway` ou équivalent, voir *Testing Plan*).
- **Fichiers de test avec un faux local au fichier**, jamais un module de fakes partagé :
  `app-mobile/test/get_receipt_detail_test.dart:14-35` (`class _StubGateway implements
  ReceiptGateway`). #160 suit la même convention pour ses propres tests.
- **Composition root unique** : `app-mobile/lib/adapters/ui/app.dart:40-51` instancie
  `ApiConfig.fromEnvironment()` puis chaque gateway/cas d'usage à la main (pas de DI magique). #159
  créera l'équivalent `main_terminal.dart` ; #160 y ajoutera l'instanciation de
  `TicketPrinterGateway` une fois ce fichier livré.
- **Dossiers par fonctionnalité** : `lib/domain/{appointment,receipt,salon}/`,
  `lib/adapters/ui/{booking,appointments,receipts}/` — #160 introduit `lib/domain/ticket/` (objet de
  transfert pur) et ajoute ses fichiers d'adaptateur sous `lib/adapters/data/`.

### Ce qui est spécifié par les specs sœurs mais pas encore implémenté

- **`app-mobile/lib/adapters/ui/terminal/`** (écrans #159) — pas encore implémenté, mais le chemin est
  **confirmé** par la spec #159 (`specs/borne-app-mobile-mode-kiosque.md`), qui y place ses écrans
  et y attend `ticket_preview.dart` (§E) ; l'écran de confirmation qui appellera
  `TicketPrinterGateway.print` y est spécifié.
- **La forme JSON de la réponse « rejoindre la file »** (#157) — **fixée** par
  `specs/borne-ticket-file-attente-walkin.md` : le champ « numéro » s'appelle `ticket_number`
  (entier, séquentiel par salon et par jour) ; #160 ne le consomme pas directement (voir §A), le
  mapping `QueueTicket → TicketPrintPayload` (fait par #159) transmettant l'entier brut, jamais une
  chaîne pré-formatée.

## Proposed Implementation

Le périmètre de #160 est **exclusivement mobile** (`app-mobile/`) : un port, un objet de transfert
pur, un formateur ESC/POS pur, un adaptateur matériel, et un petit widget d'aperçu réutilisable par
l'écran de confirmation que #159 construira. **Aucun** fichier backend ni web n'est modifié.

### (A) Domaine — `lib/domain/ticket/ticket_print_payload.dart` (nouveau, pur)

Objet de transfert **immuable**, indépendant du domaine `QueueTicket` de #157 (découplage assumé,
voir *Problem Statement*) :

```dart
class TicketPrintPayload {
  const TicketPrintPayload({
    required this.salonName,
    required this.ticketNumber,   // entier brut, tel que renvoyé par #157 (ticket_number)
    required this.issuedAt,       // date/heure d'émission, déjà résolue en heure locale
    required this.serviceNames,   // >= 1 — une ligne imprimée par prestation
  });

  final String salonName;
  final int ticketNumber;
  final DateTime issuedAt;
  final List<String> serviceNames;
}
```

- **`ticketNumber` est l'entier brut** produit par #157 (`ticket_number`, séquentiel par salon et
  par jour — voir `specs/borne-ticket-file-attente-walkin.md`) : le **formatage d'affichage**
  (« N° 014 », zéro-padding) est la responsabilité de #160, dans le formateur ESC/POS pur (§C), sur
  le modèle de `format_receipt_number` (`backend/coiflink_api/domain/receipt.py:95-107`) — jamais
  pré-formaté en chaîne par #157 ou #159.
- **`serviceNames` est une liste (≥ 1)** : le ticket peut porter plusieurs prestations — #157
  définit `service_ids` en liste (≥ 1) et #159 impose la sélection multiple à l'écran ;
  l'imprimante sort **une ligne par prestation**.
- **Aucun champ optionnel n'est ajouté par défaut** (pas de temps d'attente estimé, pas de nom de
  coiffeuse) : l'acceptation de #160 liste précisément « salon, numéro, date, heure et prestation ».
  L'ajout du temps d'attente estimé sur le ticket papier (que #157 calcule déjà pour l'écran) est une
  **question ouverte**, pas un fait acquis de cette spec (voir *Risks*).
- **Aucune PII du client** (ni nom, ni téléphone) n'entre dans ce type — voir *Security & Privacy
  Considerations* pour la justification.

### (B) Port — `lib/application/ports/ticket_printer_gateway.dart` (nouveau)

Interface abstraite à trois opérations, conforme à l'énoncé de l'issue (« connect/print/status ») :

```dart
enum TicketPrinterStatus { connected, disconnected, outOfPaper, unknown }

abstract class TicketPrinterException implements Exception {
  const TicketPrinterException(this.message);
  final String message;
}

class PrinterNotConnectedException extends TicketPrinterException {
  const PrinterNotConnectedException([
    super.message = "Imprimante indisponible.",
  ]);
}

class PrinterOutOfPaperException extends TicketPrinterException {
  const PrinterOutOfPaperException([
    super.message = "Imprimante en panne de papier.",
  ]);
}

class PrinterWriteFailedException extends TicketPrinterException {
  const PrinterWriteFailedException([
    super.message = "Échec de l'impression.",
  ]);
}

abstract class TicketPrinterGateway {
  /// Établit/rétablit la connexion à l'imprimante appairée (Bluetooth) ou
  /// détectée (USB). Idempotent : peut être rappelée après un échec (retry).
  /// Lève [PrinterNotConnectedException] en cas d'échec/timeout.
  Future<void> connect();

  /// Imprime le ticket décrit par [payload]. Lève [PrinterNotConnectedException]
  /// (aucune connexion active), [PrinterOutOfPaperException] (signalé par le
  /// matériel quand disponible), [PrinterWriteFailedException] (écriture/
  /// timeout, y compris déconnexion en cours d'impression).
  ///
  /// Un retour sans exception signifie uniquement que les octets ont été émis
  /// sans erreur reportée par le pilote/plugin — **pas** une confirmation que
  /// le papier est physiquement sorti (voir Security & Privacy).
  Future<void> print(TicketPrintPayload payload);

  /// Sonde l'état courant, en best-effort. De nombreuses imprimantes
  /// thermiques low-cost ne renvoient pas de façon fiable leur état papier sur
  /// liaison série Bluetooth (SPP) : l'absence de réponse dans un délai court
  /// doit renvoyer [TicketPrinterStatus.unknown], jamais être interprétée par
  /// défaut comme [TicketPrinterStatus.connected].
  Future<TicketPrinterStatus> status();
}
```

Ce découpage à trois exceptions typées (plutôt qu'une exception générique unique) est ce qui permet
à l'écran de confirmation (#159) d'afficher un message **différencié mais toujours neutre** au
client, sans jamais laisser fuiter un message brut de plugin (adresse MAC, code d'erreur natif,
nom de classe Java/Kotlin) — même posture que `ReceiptGatewayException` (aucune URL, jeton ni PII).

### (C) Formateur pur — `lib/adapters/data/ticket_escpos_formatter.dart` **[livré]**

Séparé de l'adaptateur matériel pour rester **testable sans aucun plugin ni matériel** (patron
`formatReceiptShareText` / `_appointmentFromJson`, fonctions pures dans des fichiers d'adaptateur) :

```dart
class TicketEscPosFormatter {
  List<int> format(TicketPrintPayload payload) { ... }
}
```

Reprend l'**information** du gabarit `ReceiptBody` (`receipt-print-modal.tsx:230-282`), réduite aux
cinq champs exigés, en commandes ESC/POS génériques (init `ESC @`, alignement centré `ESC a 1`, gras
`ESC E 1`, séparateur en ligne de tirets texte — pas de bordure CSS, ESC/POS n'a pas de concept de
bordure —, saut de ligne, coupe papier `GS V` si le matériel la supporte). C'est **ce formateur**
qui produit la forme affichée du numéro (« N° 014 », zéro-padding) à partir de l'entier brut
`ticketNumber` (§A), sur le modèle de `format_receipt_number`
(`backend/coiflink_api/domain/receipt.py:95-107`), et qui imprime **une ligne par prestation** de
`serviceNames` :

```
        [Nom du salon]      (centré, gras)
------------------------------------------
              N° 014                (centré, grande taille)
        10/08/2026 — 14:32
        Coupe homme
        Défrisage
------------------------------------------
           Merci de votre visite.
```

**Point d'attention concret, absent de la liste des décisions produit** : la plupart des
imprimantes thermiques génériques ESC/POS embarquent une page de code **mono-octet** (CP437/PC850)
par défaut et ne décodent **pas** l'UTF-8 nativement — un nom de salon ou de prestation avec des
accents français (« Défrisage », « Crème ») s'imprimerait garanti **incorrect** sans sélection
explicite de la bonne page de code (commande ESC/POS `ESC t n`) ou sans translittération des
accents en amont. Le formateur doit **choisir explicitement** l'un des deux (page de code adaptée
au français si le firmware la supporte, sinon repli sur une translittération ASCII) — voir *Risks*,
ce point n'est tranché par aucune des décisions produit fournies et doit l'être avant l'implé.

**[livré]** Formateur construit sur `esc_pos_utils_plus` (`Generator`), page de code **`CP1252`**
(profil `default`, résolue via `CapabilityProfile.load()` — pas de translittération, la page couvre
nativement les accents français). Tests dans `test/ticket_escpos_formatter_test.dart` (contenu,
numéro formaté, accents, commande de découpe).

### (D) Adaptateur matériel — `lib/adapters/data/esc_pos_ticket_printer_gateway.dart` **[livré]**

`EscPosTicketPrinterGateway implements TicketPrinterGateway` :

- Injecte un `TicketEscPosFormatter` (§C) et une dépendance de transport (Bluetooth classique SPP ou
  USB host) fournie par le paquet choisi à l'implémentation.
- `connect()` délègue à la connexion du plugin (association à un device Bluetooth déjà **appairé**
  côté OS, ou obtention d'une permission USB host) ; toute erreur/timeout devient
  `PrinterNotConnectedException` — **jamais** l'exception native du plugin propagée telle quelle.
- `print(payload)` : `formatter.format(payload)` puis écriture des octets sur la connexion active ;
  capture toute erreur d'E/S (câble débranché, device hors de portée, tampon plein) en
  `PrinterWriteFailedException` ; si le plugin choisi expose un indicateur « plus de papier » distinct
  (tous ne le font pas, voir §B), le traduit en `PrinterOutOfPaperException`.
- `status()` : requête best-effort avec délai court ; toute absence de réponse ou incertitude →
  `TicketPrinterStatus.unknown` plutôt qu'une supposition optimiste.
- **Aucun paquet n'est retenu par cette spec.** Candidats identifiés dans l'écosystème Flutter/Dart
  pour ce cas d'usage (impression ESC/POS 80mm sur liaison Bluetooth classique ou USB), à évaluer et
  auditer (maintenance, licence, compatibilité Android 12+, support Bluetooth **classique** vs BLE
  — beaucoup de paquets ESC/POS ne gèrent que le SPP classique) avant de figer un choix :
  - familles `esc_pos_bluetooth` / `esc_pos_printer` / `esc_pos_utils` (génération de commandes
    ESC/POS + transport, historiquement disjoints selon les paquets) ;
  - `flutter_thermal_printer` (plus récent, vise à unifier BLE/USB) ;
  - un couple séparé génération (`esc_pos_utils`-like) + transport USB dédié
    (`usb_serial`/`flutter_usb_printer`) si le choix se porte sur l'USB plutôt que le Bluetooth.
  Ce choix est **explicitement une décision à valider** avant l'implémentation réelle (voir *Risks*),
  pas un fait acquis de cette spec — la mission de #160 formulait déjà cette réserve.

**[livré]** Paquet retenu : `flutter_thermal_printer` (transport), Bluetooth **uniquement** en V1
(pas d'USB — voir ADR-0042 §7). `EscPosTicketPrinterGateway` compose `TicketEscPosFormatter` (§C) et
`TicketPrinterDeviceStore` (identifiant d'imprimante persisté, jamais de sélection au moment
d'imprimer — voir la section suivante). Le plugin ne remonte pas de signal « hors papier » distinct :
tout échec d'écriture devient `PrinterWriteFailedException`, jamais `PrinterOutOfPaperException` en
pratique. Tests dans `test/esc_pos_ticket_printer_gateway_test.dart`, volontairement limités au seul
chemin testable sans plugin natif (imprimante non configurée) — le reste (mapping des échecs
plugin réels, connexion effective) relève du test manuel sur device physique (checklist, étape 13).

**Sélection de l'imprimante — question non résolue par cette spec, tranchée pendant
l'implémentation.** Cette section n'aborde jamais *comment* choisir laquelle des imprimantes
disponibles utiliser. Résolu par un écran de setup ponctuel, **`TerminalPrinterSetupScreen`**
(`lib/adapters/ui/terminal/`), affiché une seule fois juste après la première activation de la
borne (nouvel état `printerSetup` de `TerminalBootstrap`) : recherche Bluetooth active (pas
d'appairage OS préalable requis), sélection par le technicien, identifiant persisté via
`TicketPrinterDeviceStore` (`flutter_secure_storage`, même mécanisme que `TerminalCredentialStore`).
Non bloquant (« Configurer plus tard » mène quand même à l'accueil). Aucune sélection n'a lieu
pendant le parcours client.

### (E) Aperçu à l'écran — `lib/adapters/ui/terminal/ticket_preview.dart` *(chemin confirmé par la spec #159)*

Un petit widget `StatelessWidget` (`TicketPreview({required TicketPrintPayload payload})`) qui
**rend à l'écran** le même contenu que celui qui part vers l'imprimante (nom du salon centré,
numéro — même formatage « N° 014 » que le papier —, date/heure, prestations, une ligne par
prestation), en `Text` monospace façon reçu — **indépendant** du succès de
l'impression : le client voit toujours son numéro à l'écran, même si le papier ne sort pas (voir
*Security & Privacy Considerations*, *Non-Goals*). Le dossier `adapters/ui/terminal/` (cohérent avec
`adapters/ui/{receipts,booking,appointments}/` existants) est **confirmé par la spec #159**
(`specs/borne-app-mobile-mode-kiosque.md`), qui attend précisément `ticket_preview.dart` à cet
emplacement.

### (F) Comportement UX en cas d'échec (contrat pour #159)

#160 fournit le port et la taxonomie d'erreurs ; le **câblage dans l'écran de confirmation** revient
à #159, mais cette spec fixe le contrat attendu pour que #159 puisse s'y conformer sans ambiguïté :

1. L'appel à `print(payload)` est entouré d'un `try/catch` sur `TicketPrinterException`.
2. Chaque sous-type produit un message **court, neutre et actionnable**, distinct :
   - `PrinterNotConnectedException` → « Impossible de joindre l'imprimante. Votre numéro reste
     affiché à l'écran. »
   - `PrinterOutOfPaperException` → « Il n'y a plus de papier. Votre numéro reste affiché à
     l'écran. »
   - `PrinterWriteFailedException` → « L'impression a échoué. Votre numéro reste affiché à
     l'écran. »
3. **Dans tous les cas**, l'écran de confirmation (et donc le `TicketPreview`, §E) reste visible le
   temps normalement prévu par #159 avant le retour à l'accueil — un échec d'impression ne
   **raccourcit jamais** ce délai, il ne fait que retirer la confirmation « ticket imprimé ».
4. Le retour automatique à l'accueil (décision produit n°7, minuté par #159) **n'est jamais
   conditionné** à une impression réussie.
5. **Signal côté personnel — local uniquement dans cette itération.** Recommandation : un indicateur
   discret sur l'écran d'accueil (idle) de la borne elle-même (visible seulement quand aucun client
   n'est en cours de parcours, pour ne pas perturber l'expérience client), reflétant le dernier
   `status()` connu différent de `connected`. **Aucune** alerte distante vers le tableau de bord
   gérant n'est ajoutée par #160 (nécessiterait un nouveau canal backend, hors périmètre — voir
   *Risks*).

## Affected Files / Packages / Modules

**[livré]** Table mise à jour a posteriori — reflète les fichiers réellement créés/modifiés, qui
diffèrent de la proposition initiale sur deux points : `esc_pos_ticket_printer_gateway_test.dart` a
une portée plus restreinte que prévu (voir §D), et trois fichiers supplémentaires ont été nécessaires
pour la sélection d'imprimante (question non anticipée par cette spec).

### Mobile (`app-mobile/`) — créés

| Fichier | Rôle |
| --- | --- |
| `lib/domain/ticket/ticket_print_payload.dart` | objet de transfert pur (salon, numéro en entier brut, date/heure, prestations en liste) — livré par #159 |
| `lib/application/ports/ticket_printer_gateway.dart` | port `TicketPrinterGateway` + `TicketPrinterStatus` + exceptions typées — livré par #159 |
| `lib/adapters/data/ticket_escpos_formatter.dart` | formateur ESC/POS **pur**, sans plugin (payload → octets), `esc_pos_utils_plus` |
| `lib/adapters/data/esc_pos_ticket_printer_gateway.dart` | adaptateur matériel Bluetooth, `flutter_thermal_printer` |
| `lib/application/ports/printer_device_scan_gateway.dart` | port de recherche d'imprimantes (setup ponctuel) — non anticipé par cette spec |
| `lib/application/ports/ticket_printer_device_store.dart` | port de persistance de l'imprimante sélectionnée — non anticipé par cette spec |
| `lib/adapters/data/secure_ticket_printer_device_store.dart` | implémentation `flutter_secure_storage` du port ci-dessus |
| `lib/adapters/data/flutter_thermal_printer_scan_gateway.dart` | implémentation `PrinterDeviceScanGateway` |
| `lib/adapters/ui/terminal/terminal_printer_setup_screen.dart` | écran de setup ponctuel — non anticipé par cette spec |
| `lib/adapters/ui/terminal/ticket_preview.dart` | aperçu à l'écran du contenu du ticket — livré par #159 |
| `test/ticket_escpos_formatter_test.dart` | tests du formatage (contenu, page de code, structure des commandes) |
| `test/esc_pos_ticket_printer_gateway_test.dart` | portée réduite (§D) : seul le chemin testable sans plugin natif |
| `test/terminal_printer_setup_screen_test.dart` | tests widget de l'écran de setup |

### Mobile — modifiés

| Fichier | Modification |
| --- | --- |
| `app-mobile/pubspec.yaml` | ajout `esc_pos_utils_plus` + `flutter_thermal_printer`, commentés |
| `app-mobile/android/app/src/main/AndroidManifest.xml` | permissions Bluetooth (`BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` + variantes legacy `maxSdkVersion="30"`) — pas de `android.hardware.usb.host` (USB abandonné en V1) |
| `app-mobile/lib/adapters/ui/terminal/terminal_print_screen.dart` | ajout du bouton « Réessayer », affiché seulement après un échec (#171) + tests |
| `app-mobile/lib/adapters/ui/terminal/terminal_bootstrap.dart` | nouvel état `printerSetup`, une seule fois avant l'accueil + tests |
| `app-mobile/lib/adapters/ui/terminal/terminal_app.dart` | câblage de `EscPosTicketPrinterGateway`/`FlutterThermalPrinterScanGateway`/`SecureTicketPrinterDeviceStore` en production, à la place du `NoopTicketPrinterGateway` (retiré, devenu mort) |
| `docs/adr/0042-file-attente-walkin-queue-ticket.md` | nouvelle section de décision §7 (pas de nouvel ADR, comme prévu par cette spec) |
| `app-mobile/README.md` | machine à 5 états (setup imprimante ajouté), écran 7 (bouton Réessayer), ports & adaptateurs à jour |

### À lire (sans modifier) pour rester fidèle aux patrons

`app-mobile/lib/application/ports/receipt_gateway.dart`,
`app-mobile/lib/application/ports/token_store.dart`,
`app-mobile/lib/adapters/ui/receipts/{receipt_detail_screen,receipt_share_text}.dart`,
`app-mobile/lib/adapters/ui/app.dart`, `app-mobile/test/get_receipt_detail_test.dart`,
`web-dashboard/src/adapters/ui/receipt-print-modal.tsx`, `web-dashboard/app/globals.css`,
`docs/adr/0040-impression-recu-encaissement-gerant.md`.

**Non touchés :** tout `backend/` (aucune route, aucune migration), tout `web-dashboard/` (parcours
gérant inchangé), `lib/domain/receipt/`, `lib/adapters/ui/receipts/` (le reçu de paiement du client
reste un partage texte, ADR-0040 §6, inchangé par #160).

## API / Interface Changes

**Aucune route HTTP, ni backend ni web.** #160 n'ajoute, ne modifie et ne supprime **aucun**
endpoint : la matrice RBAC, `PUBLIC_ROUTE_PATHS` et l'invariant `unprotected_routes(app)` ne sont pas
concernés.

**Interface interne au paquet mobile** (surface non publiée hors de `app-mobile/`) :

- Nouveau port `TicketPrinterGateway` (`connect`, `print`, `status`) et son objet de transfert
  `TicketPrintPayload` — contrat consommé par l'écran de confirmation de #159.
- Nouvelles exceptions `PrinterNotConnectedException`, `PrinterOutOfPaperException`,
  `PrinterWriteFailedException` (sous-types de `TicketPrinterException`).

**Protocole matériel introduit (nouveau pour le dépôt)** — voir *Data Model / Protocol Changes*.

## Data Model / Protocol Changes

**Aucune migration, aucune table, aucune colonne.** #160 introduit en revanche deux éléments qui
méritent d'être traités comme un « protocole » au sens de cette section, car ils engagent une
compatibilité matérielle durable :

1. **Le protocole de sortie ESC/POS** — un sous-ensemble de commandes standard (init, alignement,
   gras, saut de ligne, coupe papier, sélection de page de code) choisi pour fonctionner sur une
   imprimante thermique 80mm générique, **sans dépendance à un modèle propriétaire précis**
   (décision produit n°4). Le sous-ensemble exact de commandes supportées doit être vérifié sur au
   moins un device physique avant généralisation (rejoint l'acceptation de #161).
2. **La forme du `TicketPrintPayload`** — un contrat **interne** au paquet mobile, volontairement
   plus étroit que le futur `QueueTicket` de #157 (§A) : toute évolution de #157 qui ajoute des
   champs à la réponse « rejoindre la file » (ex. position dans la file, nom de la coiffeuse) **ne
   force pas** une évolution correspondante de #160, tant que les cinq champs exigés par
   l'acceptation restent mappables.

**Encodage de caractères** (protocole, pas schéma) : la page de code envoyée à l'imprimante (ESC/POS
`ESC t n`) doit être choisie pour couvrir les caractères accentués français, ou à défaut le
formateur (§C) doit translittérer — décision à trancher avant l'implémentation (voir *Risks*).

## Security & Privacy Considerations

- **Minimisation des données sur le support papier (§11.3).** Le `TicketPrintPayload` (§A) ne porte
  **ni le nom, ni le téléphone** du client walk-in identifié par #156 — uniquement salon, numéro,
  date/heure, prestation, strictement ce qu'exige l'acceptation. C'est un choix de conception
  **plus restrictif** que le reçu gérant (`Receipt.clientName`/`clientPhone`, ADR-0040 §2), justifié
  par le contexte : un reçu de paiement reste dans les mains du gérant (registre interne, isolé),
  tandis qu'un ticket de passage est remis **au client lui-même** puis potentiellement jeté dans un
  lieu public (salon d'attente) — imprimer son propre nom/téléphone n'apporte aucune valeur au
  client et créerait un support papier PII inutile, ramassable par un tiers. **À confirmer** comme
  décision produit (voir *Risks*), la liste des décisions fournie ne tranche pas ce point
  explicitement.
- **Cohérent avec la philosophie d'affichage minimal de #156.** #156 n'affiche que le **prénom** du
  client retrouvé par téléphone, à l'écran de la borne, pour limiter l'exposition PII sur un
  terminal public partagé (voir sa propre spec). #160 va plus loin sur le support papier : **aucun**
  élément d'identité du client, même minimal.
- **Aucun jeton, secret ou identifiant de compte sur le ticket ni dans les logs de l'adaptateur.**
  L'adaptateur ESC/POS ne journalise **jamais** l'adresse MAC Bluetooth du device appairé, ni le
  contenu des trames écrites — même posture que les gateways HTTP existants (§11.1, aucune URL, PII
  ni jeton journalisés).
- **Pas de nouvelle route, pas de nouvelle permission, pas de nouvel oracle.** #160 n'introduit
  aucune surface HTTP ; l'invariant deny-by-default (ADR-0015) n'est pas concerné.
- **Provisioning de l'imprimante = geste de configuration, pas une action cliente.** L'appairage
  Bluetooth (ou la connexion USB) doit être réalisé **avant** l'activation du mode terminal verrouillé
  (Android Lock Task Mode, décision produit n°3) : une fois la borne verrouillée en mode terminal, un
  client ne doit **jamais** se retrouver à devoir naviguer dans les réglages Bluetooth du système
  d'exploitation. `connect()` (§B) suppose donc un device **déjà appairé** au niveau OS ; toute
  procédure d'appairage initial relève du provisioning (#161), pas du parcours client.
- **Aucune preuve fiable d'impression réussie — limite structurellement aggravée par rapport à
  ADR-0040.** Le reçu gérant (ADR-0040 §5) est déjà documenté comme un signal *best-effort*
  (`afterprint`), mais un **gérant est physiquement présent** pour constater si le papier est
  réellement sorti et relancer l'impression depuis la même modale en cas de doute. Une borne
  libre-service est **par construction sans personnel présent** : rien ne garantit qu'un humain
  remarque un échec silencieux avant le client suivant. C'est pourquoi cette spec pose en **principe
  non négociable** (§F, *Goals*) que le numéro du client reste **toujours visible à l'écran**
  indépendamment du résultat de l'impression — le ticket papier est une **commodité**, jamais le
  seul support de preuve du numéro attribué. `print()` ne renvoyant aucune exception signifie
  seulement « octets émis sans erreur reportée par le pilote », **pas** « papier sorti, lisible,
  non bourré ».
- **Journalisation des pannes matérielles, sans PII.** Si un journal local de diagnostic est ajouté
  à l'implémentation (recommandé pour aider le dépannage salon), il ne doit contenir **que** l'état
  technique (type d'exception, horodatage) — jamais le contenu d'un ticket, un numéro de téléphone
  ou une adresse MAC identifiable.

## Testing Plan

Test gate mobile : `flutter test`. **Aucun** impact sur la suite `pytest` backend ni `npm test`
web (aucun fichier de ces paquets n'est touché).

### Unitaires purs (`flutter_test`, sans plugin ni matériel)

- **`test/ticket_escpos_formatter_test.dart`** (nouveau) : pour un `TicketPrintPayload` donné,
  vérifier que les octets produits contiennent, dans l'ordre, les commandes d'initialisation,
  l'alignement centré attendu, le nom du salon, le numéro, la date/heure formatée, les prestations,
  et une commande de coupe si modélisée ; **un cas multi-prestations** (payload avec plusieurs
  `serviceNames` → une ligne imprimée par prestation, dans l'ordre) ; **un cas de formatage du
  numéro** (`ticketNumber` entier brut, ex. `14`, rendu « N° 014 » avec zéro-padding, patron
  `format_receipt_number`) ; vérifier explicitement le traitement des caractères accentués
  (page de code sélectionnée ou translittération, selon la décision prise — voir *Risks*) avec un nom
  de salon/prestation contenant des accents.
- **`test/esc_pos_ticket_printer_gateway_test.dart`** (nouveau) : en injectant un **faux transport**
  (interface interne à l'adaptateur, substituable en test — aucune dépendance au plugin réel dans
  cette suite), vérifier que : une erreur de connexion du faux transport devient
  `PrinterNotConnectedException` ; une erreur d'écriture devient `PrinterWriteFailedException` ; un
  indicateur « plus de papier » simulé devient `PrinterOutOfPaperException` ; une absence de réponse
  au sondage `status()` renvoie `TicketPrinterStatus.unknown` (jamais `connected` par défaut) ;
  **aucune** exception native du faux transport ne fuite telle quelle hors de l'adaptateur.
- **`test/ticket_preview_test.dart`** (nouveau) : `pumpWidget` avec un
  `TicketPrintPayload` d'exemple, vérifier que le salon, le numéro formaté, la date/heure et les
  prestations (une ligne chacune) sont bien rendus à l'écran ; aucune donnée absente du payload
  n'est affichée.

### Intégration manuelle (device physique, non automatisée en CI)

- **Procédure documentée** (à consigner avec la procédure de provisioning de #161, dont
  l'acceptation exige déjà une vérification « sur au moins un device physique ») : appairage
  Bluetooth (ou branchement USB) réel, impression d'un ticket complet, simulation d'un bac papier
  ouvert/vide en cours d'utilisation, déconnexion du device en cours d'impression, redémarrage de la
  borne avec l'imprimante éteinte. Chaque scénario doit produire le message client attendu (§F) et
  **ne jamais** empêcher le retour à l'accueil.
- Ce test manuel est la **seule** vérification qui approche une preuve d'impression physique réussie
  — cohérent avec la limite documentée en *Security & Privacy Considerations* (aucune vérification
  automatisée fiable n'est possible depuis le code).

### Non-régression

- Aucun test existant (`app-mobile/test/*receipt*`, `*booking*`, `*appointment*`) n'est affecté :
  #160 n'ajoute que des fichiers nouveaux et ne modifie aucun fichier de production existant en
  dehors de `pubspec.yaml` et `AndroidManifest.xml` (additions pures).

## Documentation Updates

- **`app-mobile/README.md`** : nouvelle section « Ticket de passage — impression thermique (US-8.6,
  #160) », patron de la section « Mes reçus » existante (ligne 183 et suivantes) : découpage des
  fichiers (§A-§E), paquet ESC/POS retenu une fois choisi, taxonomie d'erreurs et leur traduction en
  message client, et **le même type d'avertissement explicite** que celui déjà rédigé pour le reçu
  gérant/mobile (« aucune confirmation matérielle fiable »).
- **ADR** : #160 **ne crée pas** sa propre ADR. Le jalon porte deux ADR distinctes :
  `docs/adr/0041-authentification-borne-kiosque.md` (authentification borne, committée avec #155)
  et `docs/adr/0042-file-attente-walkin-queue-ticket.md` (QueueTicket walk-in, committée avec
  #157). Les décisions structurantes que #160 soulève (choix du paquet ESC/POS et de son transport,
  taxonomie d'erreurs, absence de confirmation matérielle fiable, gestion de la page de code/
  accents) doivent être **versées dans l'ADR-0042** (volet QueueTicket/walk-in du jalon) — créer
  une ADR distincte pour #160 fragmenterait inutilement la décision. #161 vérifie la présence des
  deux ADR (et les écrit si elles manquent à ce stade) et met à jour l'index `docs/adr/README.md`.
- **`pubspec.yaml`** : commentaire explicatif au-dessus de la ou des nouvelles dépendances (patron
  des lignes 38-40 actuelles, ex. « Impression thermique du ticket walk-in (borne, #160)… »).
- **`BACKLOG.md` / `README.md` (racine)** : **non modifiés par #160** — la mise à jour du
  PRD/BACKLOG une fois le jalon M7 livré est explicitement le périmètre de #161.

## Risks and Open Questions

**[livré]** Voir ADR-0042 §7 pour l'état final de chaque décision ci-dessous. Résumé : (1) Bluetooth
retenu, **USB abandonné en V1** (pas seulement « en premier ») ; (2) `connect()` reste **paresseux**
(au premier `print()`, pas proactif à l'accueil) — non traité par cette implémentation, risque
résiduel sur le budget des 15 s si la connexion doit être rétablie, à surveiller au test manuel ; (3)
non applicable tel quel — le setup ponctuel effectue sa propre recherche Bluetooth active, il ne
suppose plus d'appairage OS préalable ; (4) tranché **« librement accessible »**, bouton « Réessayer »
sans PIN (#171). Le paragraphe original est conservé ci-dessous pour trace.

Seules les décisions de la liste produit **directement concernées par #160** sont reprises
ci-dessous, comme choix à valider par le porteur produit avant l'implémentation réelle :

1. **Imprimante thermique 80mm générique, Bluetooth ou USB, port dédié, pas de dépendance
   matérielle propriétaire figée (décision n°4).** C'est la décision fondatrice de #160 : le port
   `TicketPrinterGateway` (§B) rend le choix de paquet/transport substituable sans toucher le code
   appelant. **Ce qui reste à trancher** : lequel des deux transports (Bluetooth classique vs USB)
   est retenu en premier pour la V1 — chacun a ses paquets Flutter candidats distincts (§D) et des
   implications de permissions Android différentes ; **recommandation : commencer par le Bluetooth
   classique** (pas de câble à gérer sur un boîtier terminal, imprimantes 80mm Bluetooth très
   répandues et peu coûteuses en Côte d'Ivoire), avec l'USB comme option de repli si l'audit du
   paquet Bluetooth s'avère décevant.
2. **Timer d'inactivité 60 s, suspendu pendant l'impression jusqu'à confirmation ou 15 s maximum
   (décision n°7).** Cette borne de 15 s doit être mesurée **à partir de l'appel à `print()`**, pas
   depuis la tentative de reconnexion : si `connect()` doit être relancé au moment de l'impression
   (device perdu sa connexion Bluetooth entre deux clients), le délai de reconnexion risque à lui
   seul de consommer une bonne part des 15 s. **Recommandation : appeler `connect()` de façon
   proactive à l'accueil de la borne (avant qu'un client ne s'identifie), pas seulement au moment
   d'imprimer**, pour que le budget de 15 s couvre uniquement la génération + écriture des octets
   (de l'ordre de la seconde pour un ticket de 5-6 lignes sur une imprimante 80mm standard). **À
   confirmer avec l'implémenteur de #159**, qui pilote effectivement ce timer.
3. **Tablette Android en boîtier terminal, Android Lock Task Mode natif (décision n°3).** Implique
   que l'appairage Bluetooth de l'imprimante **doit être fait avant** le verrouillage en mode
   terminal (voir *Security & Privacy Considerations*) — `connect()` ne doit jamais avoir besoin
   d'ouvrir une UI système de pairage à laquelle un client verrait accès. **À vérifier** : le paquet
   ESC/POS retenu (§D) doit pouvoir se connecter à un device **déjà appairé** sans redemander de
   confirmation utilisateur à chaque lancement de l'app.
4. **Sortie du mode terminal et actions de maintenance protégées par PIN gérant, journalisées
   (décision n°11).** **Question à trancher** : une action de type « réessayer la connexion
   imprimante » doit-elle être **librement accessible** au client (simple bouton « Réessayer » sur
   le message d'échec, §F) ou réservée au gérant derrière le PIN de sortie du mode terminal ?
   **Recommandation : librement accessible au client** pour un simple retry non destructif (ce
   n'est pas une action de maintenance au sens de la décision n°11, qui vise la sortie du mode
   terminal et les mises à jour applicatives) ; réserver le PIN aux actions réellement sensibles
   (redémarrage, changement de device appairé, sortie du terminal).

**Questions ouvertes propres à #160, non couvertes par la liste de décisions produit :**

- **Faut-il imprimer le temps d'attente estimé sur le ticket ?** L'acceptation de #160 ne liste que
  salon/numéro/date/heure/prestation ; #157 calcule pourtant déjà une ETA pour l'écran.
  *Recommandation : l'omettre en V1* (l'ETA est une estimation volontairement volatile — décision
  produit n°5, « heuristique perfectible » — l'imprimer la fige sur un support qui ne se met plus à
  jour si l'attente réelle change). **À confirmer.**
- **Gestion de la page de code / des accents français (§C).** Non traité par la liste de décisions
  produit. *Recommandation : sélectionner explicitement une page de code compatible latin (via `ESC
  t n`) si le firmware cible la supporte, avec un filet de repli par translittération ASCII* pour ne
  jamais dépendre d'un firmware inconnu à l'avance. **À trancher avant l'implémentation**, le choix
  conditionne le format exact produit par `TicketEscPosFormatter`.
- **Absence du nom/téléphone du client sur le ticket papier** (voir *Security & Privacy
  Considerations*). Non explicitement tranché par la liste de décisions produit.
  *Recommandation : confirmer cette restriction comme un choix produit assumé*, pas seulement une
  omission de cette spec, avant l'implémentation.
- **Alerte au personnel en cas de panne imprimante récurrente.** Cette spec recommande un signal
  **local** à l'écran d'accueil de la borne (§F) faute de canal backend existant pour une alerte
  distante. *Si le porteur produit juge cela insuffisant pour un pilote sur 2-3 salons (cf. Risque 5
  du PRD), une alerte distante nécessiterait un nouveau développement backend (notification ou
  entrée de tableau de bord) hors du périmètre M7 tel que défini* — à documenter comme suivi
  explicite plutôt qu'à improviser dans #160.
- **Chemin de l'écran de confirmation borne (§E) — résolu.** `adapters/ui/terminal/` est **confirmé
  par la spec #159** (`specs/borne-app-mobile-mode-kiosque.md`), qui y attend `ticket_preview.dart` ;
  ce n'est plus une question ouverte, seule l'implémentation de #159 reste à livrer. Le port et le
  formateur (§B/§C) n'en dépendent de toute façon pas.
- **[livré]** ETA sur le ticket : **omise**, comme recommandé. Accents/page de code : **`CP1252`**
  (§C), pas de translittération nécessaire. Absence nom/téléphone client : déjà garantie par la forme
  de `TicketPrintPayload` (#159), rien à confirmer de plus. Alerte personnel à distance : **non
  ajoutée**, reste hors périmètre comme recommandé (aucun signal local d'accueil ajouté non plus —
  au-delà de ce que #159 fournissait déjà via `TicketPrinterStatus`, un signal idle dédié n'a pas été
  construit ; à reconsidérer si le pilote terrain le juge nécessaire).
- **[livré, hors périmètre spec initiale]** Sélection de l'imprimante parmi plusieurs appareils
  Bluetooth : voir §D ci-dessus (`TerminalPrinterSetupScreen`). Changer d'imprimante après le setup
  initial reste **non couvert** (redémarrage/réinstallation de l'app requis) — suivi noté dans
  ADR-0042 §7, probablement à rattacher au menu de maintenance protégé par PIN que #161 doit encore
  définir (`terminal_exit_gate.dart`, actuellement inerte).

## Implementation Checklist

1. ✅ **Lire** les fichiers de référence du reçu de paiement (#154/ADR-0040) — fait pendant la
   planification initiale de cette spec.
2. ✅ **Questions ouvertes tranchées** : Bluetooth retenu, **USB abandonné** en V1 (pas juste
   priorisé) ; page de code `CP1252` (pas de translittération) ; ETA omise ; nom/téléphone client déjà
   absent par construction (#159). Sélection d'imprimante (question non anticipée par cette spec) :
   setup ponctuel, voir §D.
3. ✅ **Domaine** — `lib/domain/ticket/ticket_print_payload.dart` : livré par #159, avant même le début
   de #160.
4. ✅ **Port** — `lib/application/ports/ticket_printer_gateway.dart` : livré par #159.
5. ✅ **Formateur pur** — `lib/adapters/data/ticket_escpos_formatter.dart` : `esc_pos_utils_plus`,
   `CP1252`.
6. ✅ **Tests du formateur** — `test/ticket_escpos_formatter_test.dart` : contenu, numéro formaté,
   accents, commande de découpe.
7. ✅ **Paquet choisi et audité** — `esc_pos_utils_plus` (formatage, stable, publisher vérifié) +
   `flutter_thermal_printer` (transport Bluetooth, activement maintenu). `esc_pos_bluetooth` écarté
   (obsolète).
8. ✅ **Adaptateur** — `lib/adapters/data/esc_pos_ticket_printer_gateway.dart` : `connect`/`print`/
   `status`, mapping d'erreurs vers les trois exceptions du port.
9. ✅ **Tests de l'adaptateur** — `test/esc_pos_ticket_printer_gateway_test.dart` : portée réduite au
   seul chemin testable sans plugin natif (imprimante non configurée) — voir §D pour la justification.
10. ✅ **Manifeste Android** — `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` (Android 12+) + variantes legacy
    (`maxSdkVersion="30"`), pas de `android.hardware.usb.host` (USB abandonné). `pubspec.yaml` : deux
    dépendances ajoutées, commentées.
11. ✅ **Aperçu à l'écran** — `ticket_preview.dart` : livré par #159.
12. ✅ **Câblage** — `EscPosTicketPrinterGateway` instancié dans `terminal_app.dart` (composition root
    réelle du paquet — `main_terminal.dart` n'existe pas, le point d'entrée est `lib/main.dart` →
    `TerminalApp`), `terminal_print_screen.dart` déjà branché sur `print()` par #159 ; ajout du bouton
    « Réessayer » (#171, non anticipé par cette spec) sur échec uniquement. Setup imprimante ponctuel
    ajouté dans `terminal_bootstrap.dart`/`terminal_app.dart` (non anticipé par cette spec, voir §D).
13. ⬜ **Test manuel sur device physique** — **non fait dans cette itération** : appairage réel,
    impression, simulation panne papier, déconnexion en cours d'impression, vérification du build
    `flutter build apk` (release) avec les nouvelles permissions Bluetooth. Reste à faire avant mise en
    production sur un vrai salon — voir la note sur `flutter_thermal_printer` (§D) : son `ConnectionType`
    ne distingue pas Bluetooth Classic (SPP) de BLE, à vérifier contre le matériel réel du parc
    (beaucoup d'imprimantes 80mm bon marché en Côte d'Ivoire utilisent le SPP classique, pas le BLE).
14. **Documentation** : section dédiée dans `app-mobile/README.md` ; transmettre les décisions
    structurantes (paquet retenu, taxonomie d'erreurs, limite de confirmation matérielle) à
    l'ADR-0042 (file d'attente walk-in & QueueTicket, committée avec #157 — #161 en vérifie la
    présence et met à jour l'index), plutôt que de créer une ADR séparée.
15. **Vérification finale** : `flutter test` au vert (aucun test backend/web affecté) ; relire la PR
    pour s'assurer qu'**aucune PII client** (nom, téléphone) n'apparaît sur le ticket ni dans les
    logs de l'adaptateur, qu'**aucune exception plugin brute** ne fuite hors du port, et qu'**aucune
    signature IA** n'a été introduite dans le code, les commits ou la PR.
