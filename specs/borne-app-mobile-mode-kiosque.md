# Mode kiosque de l'app mobile (US-8.5)

> Spécification de planification pour l'issue GitHub **#159 — US-8.5 : Mode kiosque de l'app
> mobile** (`feature`, `ux` · Must · Effort L · jalon **M7 — Borne client (kiosque
> libre-service)**, Épic 8). **Dépend de : #155, #156, #157, #158.** **Cette spec ne produit pas
> de code** : elle décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de classes, fichiers, symboles) inchangés. **Aucune signature
> IA** dans le code, les commits ou la PR.

## Problem Statement

Le jalon **M7** (`BACKLOG.md`, promu depuis « Hors périmètre MVP » — PRD §17 « Borne Intelligente
d'Accueil ») livre le parcours du client **sans rendez-vous** sur une borne tactile physique en
salon. Les issues #155 (rôle & authentification borne), #156 (identification téléphone & création
walk-in), #157 (ticket de passage) et #158 (photo de prestation) posent chacune une brique
**backend** ; #159 est la première brique **côté application mobile** qui les assemble en un
parcours tactile complet. Le critère d'acceptation exact de #159 (`BACKLOG.md`) est :

- **US-001, US-002 (UI), US-003 (UI), US-004 (UI), US-005 et US-008 couvertes ; aucune session
  personnelle active en fin de parcours ; retour automatique après 60 s d'inactivité, timer
  suspendu pendant l'impression du ticket.**

### Un point d'attention avant tout : les libellés « US-00N » n'ont pas de source documentée

Comme la spec de #160 l'a déjà constaté pour son propre critère d'acceptation (« US-007 »), une
recherche `US-00[1-9]` sur `prd-coiflink.md` **ne retourne aucune occurrence** — la seule provenance
de ces libellés est le texte de l'issue #159 lui-même dans `BACKLOG.md:468`, une recherche confirmant
qu'aucune autre issue du dépôt ni aucune section du PRD ne les définit. Cette spec **n'invente pas**
de table de correspondance faisant autorité. Elle propose, à titre d'**hypothèse de travail non
confirmée**, un rapprochement avec la numérotation du parcours borne du PRD §17.4 (« Parcours
borne », étapes 1 à 11 : arrivée → touche l'écran → choix RDV/sans RDV → identification →
vérification → confirmation de présence → numéro de passage → visibilité dans la file → prise en
charge → prestation → paiement), dont l'ordre correspond visuellement à la séquence UI de #159 :

| Libellé | Étape §17.4 correspondante (hypothèse) | Statut dans #159 |
| --- | --- | --- |
| US-001 | 1. « Le client arrive au salon » / entre en interaction avec la borne | Couvert (écran d'accueil) |
| US-002 (UI) | 2. « Il touche l'écran de la borne » | UI seule (l'écran est livré par #159 (la présente issue) ; rien à « fonctionnaliser » au-delà) |
| US-003 (UI) | 3. « Il choisit *J'ai un rendez-vous* ou *Je viens sans rendez-vous* » | UI seule — **la branche « J'ai un rendez-vous » est hors scope de M7** (voir *Non-Goals*), donc potentiellement un simple affichage sans suite fonctionnelle |
| US-004 (UI) | 4. « Il s'identifie par téléphone ou QR code » | UI seule pour #159 — la logique (recherche/création) est livrée par #156, consommée ici |
| US-005 | 5. « La borne vérifie ses informations » | Couvert (résultat de #156 affiché) |
| US-008 | 8. « Le salon voit automatiquement le client dans la file » | Couvert (conséquence de l'appel à #157 depuis la confirmation) |

Cette lecture explique pourquoi certaines lignes portent « (UI) » (la logique métier sous-jacente
appartient à une autre issue) et d'autres non (#159 couvre à la fois l'écran et l'effet). **À
confirmer par le porteur produit avant l'implémentation** (voir *Risks and Open Questions*) —
notamment le sort exact de l'étape 3 (« J'ai un rendez-vous »), qui n'est pas listée par la mission
de #159 parmi les cinq écrans à livrer (voir plus bas) et que cette spec choisit délibérément de
**ne pas construire** comme choix produit fonctionnel (voir *Non-Goals*).

### État actuel du dépôt — vérifié par lecture directe

- **`app-mobile/lib/main.dart`** (18 lignes, dont un `export`) est l'unique point d'entrée aujourd'hui : il délègue
  tout à `CoifLinkApp` (`lib/adapters/ui/app.dart:40-193`), la composition root unique qui assemble
  `ApiConfig`, les gateways HTTP, `AuthSession`/`InMemoryTokenStore` et pousse `AccueilEcran`
  (`app.dart:195-276`) comme `home:` du `MaterialApp`. **Aucun second point d'entrée n'existe.**
- **Aucun flavor Android ni variante iOS.** `android/app/build.gradle.kts:19` ne déclare qu'un seul
  `applicationId = "com.coiflink.coiflink_mobile"`, sans `flavorDimensions` ni `productFlavors` ;
  `android/app/src/main/AndroidManifest.xml` ne déclare qu'une seule `<activity>` avec
  `android:name=".MainActivity"` et une unique `<category android:name="android.intent.category.
  LAUNCHER"/>` ; `ios/Runner.xcodeproj/xcshareddata/xcschemes/` ne contient qu'un seul schéma
  (`Runner.xcscheme`). Un second entry point Dart (`-t lib/main_kiosk.dart`) compilé avec ce même
  `applicationId`/bundle id produirait donc, en l'état, un APK/IPA qui **remplacerait** l'app
  cliente s'il était installé sur le même device — sans conséquence pratique pour M7 puisque la
  tablette kiosque est un **device dédié** (décision produit n°3), jamais partagé avec l'app
  cliente personnelle.
- **`AccueilEcran` (`app.dart:195-276`)** est un `StatelessWidget` : `Scaffold` + `AppBar` + colonne
  centrée de boutons (`FilledButton.icon` « Rechercher un salon », puis `OutlinedButton.icon`
  conditionnels « Mes rendez-vous » `:247-254`, « Mon historique » `:255-262`, « Mes reçus »
  `:263-270`) — les trois derniers ne s'affichent que si un callback non-`null` est injecté
  (`onOpenMyAppointments`/`onOpenMyHistory`/`onOpenMyReceipts`, `app.dart:210-217`). C'est déjà,
  structurellement, un écran « à callbacks optionnels » — mais **réutiliser cette classe telle
  quelle** pour la borne obligerait à composer avec `SearchSalons`/`GetSalonDetail` (non pertinents,
  la borne a un salon figé, décision n°8) et laisserait la porte ouverte à brancher par erreur un
  callback personnel un jour ; #159 **réécrit** un écran d'accueil dédié plutôt que de paramétrer
  celui-ci à zéro (voir *Proposed Implementation*).
- **`_ServiceStep`** (`booking_flow_screen.dart:489-534`) et **`_HairdresserStep`**
  (`booking_flow_screen.dart:536-589`) sont les deux écrans de sélection du tunnel de réservation :
  `ListView` de `ListTile` à sélection **unique** (icône radio manuelle), sans photo — `SalonService`
  porte désormais un champ `imageUrl` (`domain/salon/salon_service.dart:19,43`, livré par #158) que
  ces `ListTile` n'affichent simplement pas. `_HairdresserStep` propose une option « Peu importe » — **non pertinente pour #159** :
  le PRD §17.3 lie le choix de coiffeuse à l'« affichage temps réel des coiffeurs disponibles »,
  explicitement **hors scope de M7** (voir *Non-Goals*) ; #159 n'adapte donc **que** `_ServiceStep`.
- **`booking_confirmation_screen.dart`** (106 lignes) est un écran de confirmation *statique*
  (aucun état, aucune navigation automatique) : icône de succès, `Chip` de statut, une série de
  `_RecapTile` (`:83-106`), un unique bouton « Terminer » qui fait `Navigator.pop()`. Aucune notion
  de minuterie, d'impression ni de secours réseau n'y existe — patron de mise en page seulement.
- **`login_screen.dart:15-122`** est explicitement écarté comme paradigme d'identification par la
  mission de #159 (compte personnel + mot de passe) — seul son squelette `TextField` +
  `FilledButton` conditionné par un booléen `_canSubmit` est réutilisable comme *idée de structure*,
  pas comme composant.
- **Aucun `Timer`, `Listener` ou écouteur de geste global n'existe dans `app-mobile/lib`.** La seule
  exception est le debounce de recherche (`lib/adapters/ui/salon_search_screen.dart:49,65,73-74`,
  `Timer? _debounce`) — un usage **local à un champ**, pas un minuteur d'inactivité applicatif. Le
  mécanisme de #159 est donc entièrement nouveau pour ce paquet.
- **`TokenStore`/`InMemoryTokenStore`** (`lib/application/ports/token_store.dart:13-40`) documente
  explicitement, en commentaire d'en-tête, que le jeton **« ne survit pas au redémarrage de
  l'application »** (`:26-28`) — un choix déjà fait dans ce paquet de préférer un état de session
  **volatile** plutôt que persistant. `AuthSession`/`SignIn`/`HttpAuthGateway` ne sont instanciés
  qu'une fois, dans `CoifLinkApp` (`app.dart:50,56,67`) : rien dans le paquet n'oblige à réutiliser
  ce mécanisme pour la borne — au contraire, le parcours walk-in de #159 **n'authentifie jamais un
  client personnel** (voir *Proposed Implementation*, §E).
- **`pubspec.yaml`** ne déclare que `flutter`, `cupertino_icons`, `http`, `share_plus`
  (lignes 30-41) ; la section `assets:` (lignes 65-74) est **entièrement commentée** — aucun asset
  local (image, police) n'existe dans ce paquet à ce jour. Le repli « logo générique bundlé si
  hors-ligne » (décision produit n°8) sera donc le **premier** asset embarqué du paquet mobile.
- **Dépendances amont désormais livrées.** Les sept specs du jalon existent sous `specs/borne-*.md`,
  et les briques backend dont dépend #159 sont **livrées** : #155
  (`borne-role-authentification-kiosque.md` → `POST /auth/kiosk/login`, `kiosk-devices`), #156
  (`borne-identification-telephone-client-walkin.md` → `kiosk/customers/lookup`, `kiosk/customers`),
  #157 (`POST /salons/{id}/queue/tickets`) et #158 (`image_url` catalogue) — vérifié par lecture
  directe du backend (`adapters/inbound/{auth,kiosk_devices,kiosk_customers,queue_tickets}.py`) et du
  modèle Flutter (`SalonService.imageUrl`). Il reste à **revalider** les noms de ports/méthodes côté
  client contre le code livré (voir *Risks*). Concrètement pour #159 :
  - la **forme du credential device** est fixée par la spec de #155 : le device s'authentifie via
    `POST /auth/kiosk/login`, dont la réponse **inclut le `salon_id`** de la borne — c'est ainsi
    que le client Flutter connaît son salon (voir §C), un APK unique servant toutes les bornes ;
    la saisie du credential au premier lancement et son stockage sécurisé côté device sont livrés
    par #159 (voir §C et *Non-Goals*) ;
  - l'**endpoint et le contrat de recherche/création client walk-in** (#156) sont fixés :
    `POST /salons/{salon_id}/kiosk/customers/lookup` → `{customer_id, first_name}` (`404` neutre
    sinon) et `POST /salons/{salon_id}/kiosk/customers`, corps `{first_name, last_name, phone}`
    (trois champs requis, composition serveur « Prénom Nom ») → `{customer_id, first_name}`
    (`specs/borne-identification-telephone-client-walkin.md`, *API / Interface Changes*) ;
  - le contrat de **« rejoindre la file »** (#157) est documenté par sa spec :
    `POST /salons/{salon_id}/queue/tickets`, corps `{customer_profile_id?, service_ids: [...]}`,
    réponse `201` `{id, ticket_number, issued_date, status, estimated_wait_minutes, created_at,
    service_ids}` (`specs/borne-ticket-file-attente-walkin.md`, section *API / Interface Changes*) —
    `ticket_number` y est un **entier brut**, jamais pré-formaté côté client (le formatage
    « N° 014 » appartient au formateur ESC/POS de #160) ;
  - le champ **`image_url`** de #158 est désormais **livré** (git `2dc5c10`, PR #165) : exposé par
    `PublicServiceResponse`/`PublicServiceView` côté backend, et déjà présent sur le modèle Flutter
    `SalonService.imageUrl` (`domain/salon/salon_service.dart:19,43`) et son parseur
    (`http_salon_catalog_gateway.dart:176`, `imageUrl: json['image_url']`) — #159 peut donc
    consommer `SalonService.imageUrl` **dès maintenant**, sans supposition supplémentaire.
  - la spec de #160 (impression) s'appuie sur un dossier `lib/adapters/ui/kiosk/` (patron
    `adapters/ui/{receipts,booking}/`) où déposer son widget `ticket_preview.dart` — cette spec
    **confirme** ce chemin et l'utilise comme structure de dossier de référence (voir *Proposed
    Implementation*).

### Ce que #159 assemble

#159 est le **point de convergence UI** du jalon : un point d'entrée `main_kiosk.dart` distinct,
cinq écrans tactiles en gros boutons (accueil, identification téléphone, création client,
choix de prestation, confirmation), un minuteur d'inactivité global qui ramène systématiquement à
l'accueil, et l'absence **délibérée** de tout point d'entrée nécessitant une session personnelle.
Rien de ce périmètre ne touche `backend/` ni `web-dashboard/`.

## Goals

- **Nouveau point d'entrée `app-mobile/lib/main_kiosk.dart`**, compilé séparément
  (`flutter run/build … -t lib/main_kiosk.dart`), lisant un indicateur de compilation
  `--dart-define=APP_MODE=kiosk` — **sans** introduire de flavor Android/iOS pour ce MVP (justifié
  en détail en *Proposed Implementation* §A, avec les conditions qui justifieraient d'en introduire
  plus tard).
- **Cinq écrans neufs sous `lib/adapters/ui/kiosk/`** (accueil, identification téléphone, création
  client, choix de prestation, confirmation), chacun adaptant un écran existant **dans son idée**
  (mise en page, découpage d'état) mais réécrit à neuf pour le contexte tactile/borne — jamais une
  simple extension paramétrée d'un écran personnel.
- **Design « gros boutons tactiles »** cohérent sur les cinq écrans : tailles de cible tactile,
  espacement et contrastes chiffrés (voir §D), **aucune dépendance à un clavier physique**
  (clavier numérique tactile dédié pour le téléphone ; clavier logiciel standard, déjà tactile par
  nature, toléré pour la saisie de nom).
- **Minuteur d'inactivité global (`KioskInactivityGuard`)** : 60 s sans interaction ramènent à
  l'accueil et purgent tout état en mémoire du parcours en cours ; remise à zéro sur **toute**
  interaction tactile, où qu'elle ait lieu dans l'arbre de widgets ; **suspendu** pendant l'appel
  d'impression du ticket (dépendance #160), avec un plafond de 15 s indépendant du signal de
  reprise (décision produit n°7).
- **Aucune session personnelle en fin de parcours (critère d'acceptation).** `main_kiosk.dart`
  n'instancie **jamais** `AuthSession`, `SignIn`, `HttpAuthGateway`, ni les écrans « Mes
  rendez-vous »/« Mon historique »/« Mes reçus » — voir *Proposed Implementation* §I et *Security &
  Privacy Considerations*.
- **Saisie et stockage sécurisé du credential device (#155).** Un écran de saisie du credential au
  premier lancement et un port de stockage dédié (`KioskCredentialStore`, adossé à
  `flutter_secure_storage`/Android Keystore — nouvelle dépendance, choix à valider) : #155 fournit
  le contrat HTTP (`POST /auth/kiosk/login`) et le format du credential, #159 livre la saisie et la
  persistance côté device (voir §C). Ce credential appartient au terminal, pas au client de
  passage : ni le minuteur d'inactivité ni la purge de fin de parcours ne le touchent.
- **Branding salon figé, avec repli hors-ligne.** Le salon de la borne est fixé au provisioning
  (décision n°8) ; l'écran d'accueil affiche son nom/logo réseau (réutilisation de
  `SalonDetail.logoUrl`, `GetSalonDetail`) avec un **repli sur un logo générique bundlé** si le
  réseau ou le logo distant est indisponible — premier asset local du paquet mobile.
- **Résilience réseau (décision n°9).** Un état « borne indisponible » cohérent sur les écrans qui
  dépendent d'un appel réseau bloquant (catalogue, identification, création de ticket) ; ces trois
  actions restent **toujours en direct**, jamais dégradées.
- **Amorce de sortie du mode kiosque (décision n°11).** Un point d'entrée caché + une porte PIN
  gérant, dont le **mécanisme de vérification exact reste une question ouverte** pour cette spec
  (voir *Risks and Open Questions*) — #159 pose le geste (comment déclencher la sortie), pas
  nécessairement la vérification finale.
- **Consommation, pas réimplémentation, des briques backend amont.** #159 appelle les contrats de
  #155/#156/#157/#158 tels que fixés par leurs specs sœurs, sans dupliquer leur logique côté
  client (pas de calcul d'ETA local, pas de normalisation de téléphone dupliquée, etc.).
- **Couverture de tests** : chaque écran testé avec de faux ports (patron `_StubGateway` du dépôt),
  le minuteur d'inactivité testé de façon déterministe (`tester.pump(Duration)`), sans navigateur ni
  matériel réel.

## Non-Goals

**Hors scope de M7 dans son ensemble** (rappel, indépendant de #159, pour situer les frontières du
jalon) : vérification/check-in d'un rendez-vous existant depuis la borne, identification par QR
code ou code de réservation, affichage temps réel des coiffeurs disponibles avant affectation,
paiement autonome sur la borne.

**Hors scope spécifique de #159 :**

- **Le rôle `KIOSK`, le format du credential device et son provisioning.** #155 fournit le contrat
  HTTP (`POST /auth/kiosk/login`) et le format du credential ; #161 documente la procédure de
  provisioning. #159 ne redéfinit ni l'un ni l'autre — il livre en revanche la **saisie** du
  credential au premier lancement et sa **persistance sécurisée côté device**
  (`KioskCredentialStore`, voir §C), et découvre le `salon_id` de la borne dans la réponse du
  login device.
- **La recherche/création de fiche client walk-in.** #159 appelle le contrat de #156 (voir
  §F.2/§F.3) ; il ne normalise pas de téléphone, ne valide pas de nom, et n'écrit **aucune** ligne
  `customer_profiles`.
- **Le domaine `QueueTicket`, la numérotation et la formule d'ETA.** #159 affiche le
  `estimated_wait_minutes` et le `ticket_number` **déjà calculés** par #157 ; aucun calcul n'est
  refait côté client.
- **`image_url` côté catalogue public.** #159 **lit** `SalonService.imageUrl` (livré par #158) ;
  il ne touche ni au backend ni au mécanisme de résolution d'URL signée.
- **L'adaptateur d'impression thermique concret.** #159 **appelle** le port `TicketPrinterGateway`
  et respecte le contrat UX défini par la spec de #160 (§F de cette dernière : trois messages
  d'erreur neutres, retour jamais bloqué) ; il ne construit ni le formateur ESC/POS, ni l'adaptateur
  Bluetooth/USB, ni le choix du paquet Flutter concerné.
- **L'activation native du mode kiosque Android (Lock Task Mode / device owner).** La décision
  produit n°3 retient ce mécanisme, mais son **enrôlement** (profil device owner, politique de
  verrouillage au niveau OS) est un geste de provisioning porté par #161, pas une fonctionnalité
  Dart. #159 peut, en complément optionnel, demander par canal de plateforme le verrouillage de la
  tâche courante (`FlutterActivity`/API Android `startLockTask()`) — signalé comme amélioration
  possible, non comme un livrable de cette spec (voir *Risks*).
- **Le mécanisme de vérification du PIN gérant à la sortie du kiosque.** #159 pose le geste
  d'entrée dans l'écran de sortie (voir §H) ; la façon dont le PIN est validé (localement ? contre
  le backend ?) et journalisé (décision n°11) reste une question ouverte, potentiellement partagée
  avec #161 (procédure de provisioning).
- **Un écran fonctionnel « J'ai un rendez-vous ».** Cohérent avec l'exclusion du check-in de RDV
  existant de M7 dans son ensemble : #159 ne construit **aucune** branche menant à une vérification
  de rendez-vous. Voir la discussion de US-003 en *Problem Statement* et *Risks*.
- **Toute modification de `backend/` ou `web-dashboard/`.** #159 est un paquet **exclusivement
  mobile** (`app-mobile/`).

## Relevant Repository Context

### Stack & architecture (figées par les ADR, inchangées par #159)

| Couche | Décision | ADR |
| --- | --- | --- |
| Mobile | Flutter, Dart, **Android prioritaire** | [0001](../docs/adr/0001-app-mobile-flutter.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/{ui,data}` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| Réservation client | `ApiConfig.fromEnvironment()`, DI manuelle dans `adapters/ui/app.dart` | [0024](../docs/adr/0024-reservation-cote-client.md) |
| Reçu — impression/partage | `window.print()` (gérant) ; `share_plus` (client) ; aucune impression thermique mobile avant #160 | [0040](../docs/adr/0040-impression-recu-encaissement-gerant.md) |

`docs/adr/` va désormais jusqu'à **ADR-0042** : le jalon M7 a produit **deux** ADR distinctes —
**ADR-0041** (authentification borne kiosque, committée avec #155) et **ADR-0042** (file d'attente
walk-in `QueueTicket`, committée avec #157), toutes deux **présentes** ; #161 en vérifie la présence
et met à jour l'index `docs/adr/README.md`. #159 ne crée **pas** sa propre ADR (voir *Documentation
Updates*).

### Composition root actuelle — patron à décliner, pas à réutiliser tel quel

- `lib/main.dart:15-17` : `void main() => runApp(const CoifLinkApp());` — trivial, délègue tout.
- `lib/adapters/ui/app.dart:40-193` (`CoifLinkApp`) : instancie `ApiConfig.fromEnvironment()`
  (`:47`), les gateways HTTP (`:48-51`), `AuthSession(InMemoryTokenStore())` (`:56`), tous les cas
  d'usage (`:58-69`), puis pousse `AccueilEcran` avec cinq callbacks (réservation, modification,
  « Mes rendez-vous », « Mon historique », « Mes reçus », `:167-181`). **`main_kiosk.dart` suit la
  même forme** (fichier `main` minimal → composition root dédiée), mais la composition root kiosque
  **n'instancie aucun** de `AuthSession`/`SignIn`/`HttpAuthGateway`/`HttpReceiptGateway` ni les
  écrans `LoginScreen`/`MyAppointmentsScreen`/`AppointmentHistoryScreen`/`ReceiptsScreen` — leur
  absence du graphe d'imports de `main_kiosk.dart` est la garantie qu'**aucun chemin de navigation**
  du parcours kiosque ne peut les atteindre (voir §I).
- `lib/adapters/ui/app.dart:195-276` (`AccueilEcran`) : `Scaffold`/`AppBar`/colonne de boutons
  conditionnels. Le patron de mise en page (bouton principal + boutons secondaires optionnels) est
  repris pour `KioskHomeScreen`, mais réécrit (voir §F.1) plutôt que paramétré, car `AccueilEcran`
  reste couplé à `SearchSalons`/`GetSalonDetail`/aux callbacks personnels.

### Écrans de sélection existants — patron pour le choix de prestation

- `lib/adapters/ui/booking/booking_flow_screen.dart:489-534` (`_ServiceStep`) : `ListView` de
  `ListTile` à sélection **unique**, construite depuis `List<SalonService>` + `SalonService?
  selected` + `ValueChanged<SalonService> onSelected`. #159 en reprend l'**entrée** (même modèle de
  données) mais pas la sortie : le contrat « rejoindre la file » de #157 accepte `service_ids:
  list[uuid]` (**pluriel**, voir §*API / Interface Changes* de `specs/borne-ticket-file-attente-
  walkin.md`) — `KioskServiceSelectionScreen` doit donc permettre une **sélection multiple**, à la
  différence de `_ServiceStep` (voir §F.4).
- `lib/adapters/ui/booking/booking_flow_screen.dart:536-589` (`_HairdresserStep`) : **non adapté**
  par #159 (choix de coiffeuse hors scope M7, voir *Non-Goals*).
- `lib/adapters/ui/widgets/service_list_tile.dart:11-37` (`ServiceListTile`) : ligne de prestation
  de la fiche salon, sans photo — également non repris tel quel (grille avec photo attendue, voir
  §F.4), mais confirme que `SalonService.price`/`durationMinutes` sont déjà tolérants à l'absence
  (`String?`/`int?`).
- `lib/domain/salon/salon_service.dart:11-44` : le champ `imageUrl` (URL signée à durée limitée) est
  **désormais présent** (`:19,43`, livré par #158) et parsé par `http_salon_catalog_gateway.dart:176` ;
  #159 en dépend directement pour la grille de prestations en photo (voir *Non-Goals*, #158 n'est
  pas réimplémentée ici).

### Écran de confirmation existant — patron de mise en page, pas de comportement

- `lib/adapters/ui/booking/booking_confirmation_screen.dart:1-106` : icône de succès (`:36-40`),
  `Chip` de statut (`:48-54`), série de `_RecapTile` (`:56-68`, `:83-106`), bouton unique
  « Terminer » (`:70-76`) qui fait `Navigator.pop()`. **Aucune minuterie, aucun appel d'impression,
  aucun état d'erreur réseau** — `KioskConfirmationScreen` en reprend la structure visuelle
  (icône + tuiles de récapitulatif) mais ajoute : un numéro de ticket en très grande taille, le
  temps d'attente estimé, l'aperçu du ticket imprimable (`TicketPreview`, dépendance #160), et le
  branchement au minuteur d'inactivité (retour automatique, pas seulement sur pression d'un bouton).

### Absence de minuteur d'inactivité — mécanisme entièrement nouveau

- `lib/adapters/ui/salon_search_screen.dart:49,65,73-74` : seul usage de `Timer` du paquet, un
  debounce de recherche **local** à un champ de saisie (300 ms), sans rapport avec un retour
  automatique à l'accueil. Aucun `Listener`, `RawGestureDetector`, ni observateur de cycle de vie
  applicatif (`WidgetsBindingObserver`) n'existe ailleurs dans `app-mobile/lib`.

### Session & jeton — précédent qui *justifie* la simplicité de la purge kiosque

- `lib/application/ports/token_store.dart:13-40` : `TokenStore` abstrait + `InMemoryTokenStore`,
  dont le commentaire d'en-tête (`:5-7`, `:26-28`) documente déjà que le jeton **« ne survit pas au
  redémarrage »** — un choix de conception déjà pris dans ce paquet en faveur d'un état de session
  **volatile**, jamais persisté sur disque. C'est précisément ce qui permet à #159 de traiter la
  purge d'un parcours kiosque comme un problème de **disposition de widgets**, pas de nettoyage de
  stockage : rien de ce que #159 manipule (téléphone tapé, fiche trouvée/créée, prestations
  sélectionnées) n'est jamais écrit sur `SharedPreferences`/disque — tout vit dans le `State` des
  écrans de la pile de navigation courante, détruit par Flutter dès qu'on revient à la racine (voir
  §E).

### Assets & dépendances — premier ajout de ce type dans le paquet

- `pubspec.yaml:30-41` : `flutter`, `cupertino_icons`, `http`, `share_plus` — aucune dépendance
  Bluetooth/USB/impression, aucun package de state management ou de routing.
- `pubspec.yaml:65-74` : section `assets:` **entièrement commentée** — aucun fichier
  image/police embarqué à ce jour. Le logo générique de repli (décision n°8) sera le **premier**
  asset local déclaré dans ce paquet.

### Contraintes transverses documentées

- **PRD §17.4** (parcours borne) et **§17 Risque 5** (« lancer d'abord sans borne », piloter sur
  2-3 salons) — contexte déjà repris dans l'en-tête du jalon M7 de `BACKLOG.md`.
- **PRD §12.1** : réponse API < 3 s — les écrans kiosque doivent afficher un état de chargement pour
  tout appel réseau (identification, création de ticket) et ne jamais bloquer indéfiniment
  (cohérent avec la résilience réseau, décision n°9).
- **Décisions d'architecture M7** (fournies au porteur de cette spec) : n°3 (terminal & mode
  kiosque), n°7 (inactivité & retour auto), n°8 (borne mono-salon), n°9 (résilience réseau), n°11
  (sécurité opérationnelle) concernent **directement** #159 et sont reprises en *Risks and Open
  Questions* ; n°1, n°2, n°4, n°5, n°6, n°10 sont des propriétés d'autres issues (#155/#156/#157/
  #160), simplement **consommées** ici sans être décidées par #159.

## Proposed Implementation

Le périmètre de #159 est **exclusivement mobile** (`app-mobile/`) : un point d'entrée, une
composition root dédiée, un minuteur d'inactivité, cinq écrans, et les petits composants tactiles
qui les outillent. **Aucun** fichier `backend/` ni `web-dashboard/` n'est modifié.

### (A) Point d'entrée `lib/main_kiosk.dart` + `--dart-define=APP_MODE=kiosk`

```dart
// Point d'entrée dédié à la borne kiosque (US-8.5, #159). Compilé séparément de
// `main.dart` (flutter run/build … -t lib/main_kiosk.dart) : aucun écran nécessitant
// une session personnelle n'est importé depuis ce fichier ni depuis son graphe.
import 'package:flutter/material.dart';
import 'adapters/ui/kiosk/kiosk_app.dart';

void main() {
  runApp(const KioskApp());
}
```

**Pourquoi un second point d'entrée `-t` plutôt que de brancher un mode dans `main.dart`
existant ?** Parce que c'est la **seule** garantie *à la compilation* que le graphe d'imports du
binaire kiosque ne contient physiquement aucun chemin de navigation vers un écran personnel — un
simple `if (kioskMode) ... else ...` dans un fichier unique laisserait les deux arbres de widgets
(personnel et kiosque) importés côte à côte dans le même binaire, ce qui affaiblirait la garantie
« aucune session personnelle en fin de parcours » à une garantie *comportementale* (le code existe
mais n'est jamais atteint) plutôt que *structurelle* (le code n'est atteignable par **aucun**
chemin depuis ce point d'entrée). C'est le même raisonnement qui explique pourquoi `main.dart`
existant délègue déjà tout à `app.dart` (`main.dart:9,13`) : la convention du dépôt sépare déjà
« point d'entrée exécutable » de « composition root », #159 se contente d'ajouter un second couple
des deux, pas une branche dans le premier.

**Pourquoi `--dart-define=APP_MODE=kiosk` en plus, alors que le choix du fichier `-t` suffit déjà à
distinguer les deux binaires ?** Les deux mécanismes ne jouent pas le même rôle :

- Le **fichier d'entrée** (`-t lib/main_kiosk.dart`) est ce qui détermine, à la compilation, *quel*
  arbre de widgets existe dans le binaire — c'est le mécanisme structurel décrit ci-dessus.
- Le **`--dart-define`** est un indicateur *lu au runtime*, dans la même veine que
  `API_BASE_URL` (`api_config.dart:18-28`, déjà le seul mécanisme de configuration
  d'environnement du paquet) — il sert à :
  1. rendre les invocations de build/CI **auto-documentées et grep-ables** (`grep
     APP_MODE=kiosk` dans un script de provisioning ou un pipeline retrouve immédiatement la bonne
     commande), cohérent avec la convention déjà établie de piloter tout comportement
     dépendant de l'environnement via `--dart-define` plutôt que par un fichier de config ou une
     branche de code ;
  2. permettre une **assertion de démarrage défensive** dans `KioskApp` (`assert(kAppMode ==
     'kiosk')`) qui échoue bruyamment si `main_kiosk.dart` était un jour construit sans le
     `--dart-define` attendu (erreur de script de build), plutôt que de démarrer silencieusement
     avec une configuration incomplète ;
  3. laisser la porte ouverte à du code **partagé** entre les deux points d'entrée (par exemple un
     futur en-tête `User-Agent` distinctif sur les requêtes HTTP, utile côté observabilité backend
     avant même qu'un mécanisme d'authentification device dédié existe) sans dupliquer ce code —
     le indicateur runtime permet de le brancher sans avoir deux implémentations.
- En pratique, un seul des deux mécanismes ne suffit pas à couvrir les deux besoins (garantie
  structurelle **et** configuration/observabilité runtime) : c'est pourquoi la mission de #159 —
  reprise du texte de `BACKLOG.md:465` — demande les deux ensemble.

**Ce qui devrait déclencher un passage à de vrais flavors Android/schémas iOS plus tard** (pas dans
le périmètre de #159, à consigner comme suivi) :

1. **Coexistence sur le même device.** Si un jour un même device doit héberger **à la fois** l'app
   cliente et l'app kiosque (aujourd'hui exclu : device dédié, décision n°3), il faudra un
   `applicationId`/bundle id **distinct** par variante — ce que seuls de vrais flavors/schémas
   permettent (deux apps installables côte à côte).
2. **Gestion de parc via MDM.** La décision n°3 écarte explicitement un MDM tiers payant « pour la
   V1 » — un futur passage à un MDM d'entreprise pour gérer un parc de bornes nécessiterait
   généralement un identifiant d'application distinct pour cibler/déployer la variante kiosque
   indépendamment de l'app cliente dans le store interne de flotte.
3. **Icône/nom d'application distincts sur l'écran de lancement.** `AndroidManifest.xml` ne déclare
   qu'un seul `android:label`/`@mipmap/ic_launcher` ; si le provisioning exige de reconnaître
   visuellement le mode installé sans lancer l'app (utile en dépannage salon), il faudrait des
   ressources de manifeste distinctes — un flavor les fournit nativement.
4. **Divergence de permissions native significative.** #160 ajoutera des permissions Bluetooth/USB
   (`BLUETOOTH_CONNECT`/`BLUETOOTH_SCAN`/`android.hardware.usb.host`) au manifeste **partagé** — sans
   conséquence pour l'app cliente tant que ces permissions restent inertes hors du parcours kiosque,
   mais si la liste de permissions natives divergentes continue de croître, un flavor isolerait ce
   risque de surface (l'app cliente n'embarquerait alors plus ces permissions du tout).
5. **Cadence de publication indépendante.** Si l'app kiosque doit un jour être mise à jour
   séparément de l'app cliente (versions différentes en production), des artefacts de build
   distincts par flavor deviennent nécessaires pour un déploiement indépendant.

### (B) Composition root dédiée — `lib/adapters/ui/kiosk/kiosk_app.dart` (nouveau)

Décline le patron de `CoifLinkApp` (`app.dart:40-193`) en le réduisant strictement à ce dont le
parcours walk-in a besoin :

```dart
class KioskApp extends StatelessWidget {
  const KioskApp({super.key});

  @override
  Widget build(BuildContext context) {
    final apiConfig = ApiConfig.fromEnvironment();      // réutilisé tel quel
    final credentialStore = SecureKioskCredentialStore();     // nouveau, voir (C)
    final kioskSession = KioskDeviceSession(credentialStore); // salon_id issu de la réponse
                                                              // de POST /auth/kiosk/login (#155)
    final catalogGateway = HttpSalonCatalogGateway(config: apiConfig); // réutilisé tel quel
    final getSalonDetail = GetSalonDetail(catalogGateway);             // réutilisé tel quel

    // Nouveaux ports consommés (contrats fixés par les specs de #155/#156/#157) :
    final identityGateway = HttpKioskIdentityGateway(config: apiConfig, session: kioskSession);
    final queueGateway = HttpKioskQueueGateway(config: apiConfig, session: kioskSession);

    return MaterialApp(
      title: 'CoifLink — Borne',
      theme: kioskTheme,       // voir (D), distinct du ThemeData personnel (app.dart:169-172)
      navigatorKey: kioskNavigatorKey,
      builder: (context, child) => KioskInactivityGuard(   // voir (E)
        navigatorKey: kioskNavigatorKey,
        child: child!,
      ),
      home: KioskHomeScreen(
        getSalonDetail: getSalonDetail,
        salonId: kioskSession.salonId,
        identityGateway: identityGateway,
        queueGateway: queueGateway,
      ),
    );
  }
}
```

Points notables :

- `ApiConfig`/`HttpSalonCatalogGateway`/`GetSalonDetail` sont **réutilisés sans modification** — la
  route qu'ils consomment (`GET /catalog/salons/{id}`) est déjà **publique**, donc utilisable sans
  aucun credential device pour la partie « lecture de catalogue » (nom du salon, logo, prestations
  + photos une fois #158 livrée).
- `HttpKioskIdentityGateway`/`HttpKioskQueueGateway` sont des noms propres à #159 : leur forme
  (en-têtes d'authentification, chemins) suit les contrats fixés par les specs de #155/#156/#157 —
  à revalider contre le code réellement livré par ces issues, sans changer la structure de la
  composition root.
- **`AuthSession`, `SignIn`, `HttpAuthGateway`, `HttpReceiptGateway`, `HttpAppointmentGateway` ne
  sont jamais instanciés ici** — voir §I.
- `builder:` (plutôt qu'un widget englobant chaque écran individuellement) place
  `KioskInactivityGuard` **une seule fois**, au-dessus du `Navigator` interne du `MaterialApp` :
  tout écran poussé plus tard (`Navigator.of(context).push(...)`) hérite automatiquement de la
  détection d'inactivité sans avoir à l'envelopper lui-même — un écran oublié ne peut pas
  accidentellement échapper au minuteur.

### (C) Session device & `KioskCredentialStore` — salon figé au provisioning, porté par le credential (#155)

Le `salon_id` de la borne est **porté par le credential device** : la réponse de
`POST /auth/kiosk/login` (#155) l'inclut — mécanisme retenu pour tout le jalon, avec un **APK
unique** pour toutes les bornes (aucune valeur propre au device à compiler). Concrètement :

- **Au premier lancement**, `KioskCredentialEntryScreen` (nouveau) fait saisir le credential
  device (format défini par #155, remis au gérant lors du provisioning — procédure documentée par
  #161) et le persiste via **`KioskCredentialStore`** (nouveau port), dont l'adaptateur s'adosse à
  `flutter_secure_storage`/Android Keystore — **nouvelle dépendance du paquet, à valider** comme
  choix d'implémentation. Ce credential appartient au **terminal** : ni le minuteur d'inactivité
  (§E) ni la fin d'un parcours client ne le purgent.
- **Aux lancements suivants**, l'app lit le credential stocké, appelle `POST /auth/kiosk/login` et
  conserve en mémoire la session device retournée — dont le `salon_id`, exposé aux écrans par la
  composition root (§B). La décision produit n°8 (« `salon_id` figé une fois à
  l'installation/provisioning, pas de sélection de salon à l'écran ») est ainsi satisfaite côté
  serveur (credential ↔ salon), pas dans le binaire.

**Alternative non retenue en production** : `--dart-define=KIOSK_SALON_ID` par device (patron
`ApiConfig.fromEnvironment()`, `api_config.dart:22-28`). Elle imposerait une recompilation ou un
`--dart-define` distinct par borne physique lors du provisioning — incompatible avec l'APK unique
retenu par #155 pour le jalon. Elle est tolérée **uniquement comme override de développement
local** (lancer l'app kiosque sans device provisionné), portée par `kiosk_config.dart` et
clairement marquée comme telle dans le code. `API_BASE_URL` et `APP_MODE` restent, eux, des
`--dart-define`.

### (D) Thème kiosque — `lib/adapters/ui/kiosk/kiosk_theme.dart` (nouveau)

Un `ThemeData` **distinct** de celui de l'app personnelle (`app.dart:169-172`,
`ColorScheme.fromSeed(seedColor: Colors.indigo)`) — mêmes teintes de marque, mais recalibré pour un
usage à distance de bras, sous un éclairage de salon variable, sans confirmation possible par un
second regard (contrairement à un mobile personnel tenu en main) :

| Paramètre | Valeur cible | Justification |
| --- | --- | --- |
| Hauteur minimale d'un bouton principal (CTA) | **88 dp** | Nettement au-dessus du minimum Material (48 dp) : cible tactile confortable à bout de bras, tolérante à une frappe imprécise ou gantée. |
| Hauteur minimale d'une carte de prestation (grille) | **≥ 160×160 dp** | Assez grande pour une photo (#158) + libellé + prix lisibles sans avoir à s'approcher de l'écran. |
| Espacement minimal entre deux cibles tactiles adjacentes | **24 dp** | Marge de sécurité contre le clic accidentel sur la cible voisine (borne partagée, gestes moins précis qu'un usage assis). |
| Taille de police — corps de texte / libellés de bouton | **≥ 20 sp** | Lisible à distance de bras (le thème personnel utilise les tailles Material3 par défaut, ~14-16 sp, insuffisantes ici). |
| Taille de police — numéro de ticket (écran de confirmation) | **72-96 sp** | Doit être identifiable **d'un coup d'œil**, y compris par un client qui ne s'attarde pas à l'écran une fois le ticket imprimé. |
| Contraste texte/fond | **≥ 4,5:1** (texte courant), **≥ 3:1** (texte large) | Seuils WCAG AA — les surfaces tonales Material3 par défaut (utilisées par le thème personnel) peuvent descendre sous ces seuils sur certaines combinaisons ; le thème kiosque fixe des couples couleur/fond explicites plutôt que de s'appuyer sur les tons dérivés automatiquement. |
| Clavier | **aucune dépendance à un clavier physique** | Clavier numérique tactile dédié pour le téléphone (§F.2) ; clavier logiciel standard (déclenché par le focus d'un `TextField`, comme `login_screen.dart` le fait déjà) pour la saisie de nom — un écran tactile fournit nativement ce clavier, aucun appairage externe n'est requis. |

Ces chiffres sont des **cibles de conception à valider par une revue UX/accessibilité** avant
implémentation réelle (voir *Risks*), pas des contraintes techniques absolues.

### (E) `KioskInactivityGuard` — `lib/adapters/ui/kiosk/kiosk_inactivity_guard.dart` (nouveau)

```dart
class KioskInactivityGuard extends StatefulWidget {
  const KioskInactivityGuard({
    super.key,
    required this.navigatorKey,
    required this.child,
    this.timeout = const Duration(seconds: 60),
    this.printSuspensionCap = const Duration(seconds: 15),
  });

  final GlobalKey<NavigatorState> navigatorKey;
  final Widget child;
  final Duration timeout;
  final Duration printSuspensionCap;

  @override
  State<KioskInactivityGuard> createState() => KioskInactivityGuardState();
}

class KioskInactivityGuardState extends State<KioskInactivityGuard> {
  Timer? _timer;
  Timer? _suspensionCapTimer;
  bool _suspended = false;

  @override
  void initState() {
    super.initState();
    _resetTimer();
  }

  void _resetTimer() {
    if (_suspended) return; // une impression en cours ignore les resets normaux
    _timer?.cancel();
    _timer = Timer(widget.timeout, _returnToHome);
  }

  /// Appelé par l'écran de confirmation juste avant `TicketPrinterGateway.print(...)`.
  void pauseForPrinting() {
    _suspended = true;
    _timer?.cancel();
    _suspensionCapTimer = Timer(widget.printSuspensionCap, _returnToHome);
  }

  /// Appelé juste après la résolution de `print(...)` (succès ou exception typée).
  void resumeAfterPrinting() {
    _suspensionCapTimer?.cancel();
    _suspended = false;
    _resetTimer();
  }

  void _returnToHome() {
    widget.navigatorKey.currentState
        ?.popUntil((route) => route.isFirst);
    // Aucune purge explicite d'état supplémentaire n'est nécessaire : chaque écran
    // intermédiaire dispose son propre State en quittant la pile (téléphone tapé,
    // fiche trouvée/créée, prestations sélectionnées ne vivent que là) — voir
    // Relevant Repository Context, « Session & jeton ».
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      behavior: HitTestBehavior.translucent,   // ne vole aucun geste aux enfants
      onPointerDown: (_) => _resetTimer(),
      onPointerMove: (_) => _resetTimer(),
      child: widget.child,
    );
  }
}
```

Points de conception à justifier explicitement :

- **`Listener` plutôt que `GestureDetector`.** Un `GestureDetector` place le geste dans une *arène*
  qui peut être remportée par un widget descendant (un `ListTile`, un `TextField`…) — dans ce cas,
  le `GestureDetector` englobant ne serait **jamais notifié**. `Listener` reçoit les évènements de
  pointeur bruts (`onPointerDown`/`onPointerMove`) **avant** toute résolution d'arène, pour
  **chaque** évènement qui traverse la zone de test de collision, quel que soit le widget qui le
  traite ensuite — c'est le seul des deux qui garantisse « remise à zéro sur **toute**
  interaction », comme l'exige la mission. `behavior: HitTestBehavior.translucent` assure qu'il ne
  bloque **aucun** geste destiné à un enfant (il observe, il ne consomme pas).
- **`GlobalKey<NavigatorState>` dédié**, pas `Navigator.of(context)` local à un écran : le retour à
  l'accueil doit fonctionner **depuis n'importe quelle profondeur** de la pile de navigation
  kiosque (identification → création → choix de prestation → confirmation), avec un seul appel
  `popUntil((route) => route.isFirst)` — plus robuste qu'un compte de `pop()` répétés.
- **La purge d'état n'est pas un mécanisme actif séparé.** Comme documenté dans *Relevant
  Repository Context* (« Session & jeton »), rien de ce que le parcours walk-in manipule n'est
  jamais écrit hors du `State` Flutter de l'écran courant — revenir à la racine **est** la purge,
  au même titre que la fermeture de l'app efface déjà `InMemoryTokenStore` (`token_store.dart:26-
  28`). #159 applique le même principe à un cycle beaucoup plus court (60 s ou fin de parcours) que
  le redémarrage de l'app. Le **credential device** (§C) n'est pas concerné : identité du terminal
  et non état de parcours, il est persisté via `KioskCredentialStore` et survit délibérément au
  retour à l'accueil comme au redémarrage — ni le minuteur d'inactivité ni la purge de fin de
  parcours ne le touchent.
- **Plafond de 15 s indépendant du signal de reprise** (décision n°7) : si l'écran de confirmation
  ne rappelle jamais `resumeAfterPrinting()` (bug, plantage du plugin d'impression, deadlock), le
  minuteur de secours `_suspensionCapTimer` garantit malgré tout un retour à l'accueil — cohérent
  avec le contrat « le retour automatique n'est jamais conditionné à une impression réussie » posé
  par la spec de #160 (§F.4 de `specs/borne-impression-ticket-thermique.md`).
- **Point de coordination avec #160** (repris de son *Risks* n°2) : ce plafond de 15 s doit courir
  à partir de l'appel à `print()`, pas d'une éventuelle reconnexion Bluetooth préalable — #160
  recommande d'appeler `connect()` de façon proactive dès l'écran d'accueil plutôt qu'au moment de
  l'impression, pour que les 15 s ne soient pas déjà partiellement consommés par une reconnexion.
  `KioskConfirmationScreen` (§F.5) doit donc supposer que la connexion imprimante est **déjà**
  établie quand il appelle `pauseForPrinting()` puis `print()`.

### (F) Les cinq écrans

#### F.1 — `KioskHomeScreen` (`lib/adapters/ui/kiosk/kiosk_home_screen.dart`, nouveau)

Adapte la **mise en page** d'`AccueilEcran` (`Scaffold` + colonne centrée + gros bouton
`FilledButton`), réécrite à neuf : pas de barre de recherche, pas de callbacks personnels
optionnels. Contenu :

- Logo/nom du salon (via `GetSalonDetail(kioskSession.salonId)`), avec repli sur l'asset local
  générique (§D/décision n°8) si l'appel échoue ou si `logoUrl` est absent.
- Un unique CTA « Commencer » (88 dp de haut, §D) menant à `KioskPhoneIdentificationScreen`.
- **Aucun bouton « J'ai un rendez-vous » fonctionnel** (voir *Non-Goals* et la discussion de
  US-003 en *Problem Statement*) — à confirmer avec le porteur produit si un affichage *inerte* de
  ce choix est malgré tout attendu pour la cohérence perçue du parcours PRD §17.4 (voir *Risks*).
- État réseau : si `GetSalonDetail` échoue (backend injoignable), l'écran d'accueil doit **basculer
  vers `KioskUnavailableScreen`** (§G) plutôt que d'afficher un salon vide — c'est le point d'entrée
  naturel pour détecter une panne réseau avant que le client n'engage un parcours.
- Cible de retour du minuteur d'inactivité (§E) — c'est la **seule** route de première position de
  la pile (`home:` du `MaterialApp`, §B).
- Point d'ancrage discret de la sortie du mode kiosque (§H) — un geste caché (par ex. appui long
  sur le logo), pas un bouton visible.

#### F.2 — `KioskPhoneIdentificationScreen` + `KioskNumericKeypad` (nouveaux)

`login_screen.dart` n'est réutilisé que comme **idée de structure** (champ de saisie + bouton
d'action conditionné par un booléen `_canSubmit`, `login_screen.dart:38-39`) — pas comme
composant : c'est un formulaire identifiant + mot de passe, un paradigme explicitement écarté par
la mission de #159 pour l'identification borne.

- **`KioskNumericKeypad`** (`lib/adapters/ui/kiosk/kiosk_numeric_keypad.dart`, nouveau, réutilisable
  par F.5 si un futur écran en a besoin) : grille de boutons 0-9 + correction + validation, chaque
  bouton respectant les cibles tactiles de §D. Recommandé **spécifiquement pour le téléphone**
  (l'action la plus fréquente et la plus sensible aux erreurs de frappe — une faute de frappe sur
  un chiffre peut faire remonter la fiche d'un **autre** client, voir *Security & Privacy
  Considerations*), plutôt que le clavier numérique logiciel par défaut (rangée de touches plus
  petite que 88 dp, pensée pour une saisie tenue en main, pas à bout de bras).
- Affiche le numéro tapé en gros caractères au fur et à mesure, appelle
  `identityGateway.findByPhone(salonId, phone)` (contrat de #156 :
  `POST /salons/{salon_id}/kiosk/customers/lookup` → `{customerId, firstName}`) à la validation.
  - **Trouvé** → affiche **uniquement le prénom** (jamais le nom complet ni le téléphone à
    l'écran, miroir direct de la décision de #156 rappelée par `BACKLOG.md:441-443`) avec un bouton
    de confirmation → `KioskServiceSelectionScreen` ; le `customerId` retourné est conservé pour
    la création du ticket (`customer_profile_id` de #157).
  - **Absent** → `KioskCreateCustomerScreen`.
  - **Erreur réseau** → message neutre, bouton « Réessayer », **sans** naviguer automatiquement
    (l'identification est une des actions « toujours en direct » de la décision n°9 — pas de mode
    dégradé).
- Un bouton « Continuer sans identification » **n'est pas tranché par cette spec** — la spec de
  #157 laisse elle-même la question ouverte côté domaine (`customer_profile_id` nullable dans le
  contrat « rejoindre la file ») sans se prononcer sur l'UX ; #159 doit décider si ce chemin existe
  (voir *Risks*, repris de `specs/borne-ticket-file-attente-walkin.md`).

#### F.3 — `KioskCreateCustomerScreen` (nouveau)

Formulaire minimal, écrit à neuf : nom, prénom, téléphone (pré-rempli et non modifiable depuis
l'écran précédent), gros champs de saisie, clavier logiciel standard (pas de clavier tactile
dédié — la saisie de nom est alphabétique, un pavé numérique ne convient pas, et cet écran n'est
emprunté que par les **nouveaux** clients, un sous-ensemble du trafic). Appelle une création
walk-in via `identityGateway.createCustomer(salonId, {firstName, lastName, phone})` (contrat de
#156 : trois champs requis, composition « Prénom Nom » côté serveur, réponse
`{customerId, firstName}` — le `customerId` est conservé pour la création du ticket, #157) —
**sans mot de passe**, cohérent avec `BACKLOG.md:442` (« crée une fiche nom/prénom/téléphone sans
mot de passe ») — puis enchaîne directement vers `KioskServiceSelectionScreen`.

#### F.4 — `KioskServiceSelectionScreen` + `KioskServiceCard` (nouveaux)

Adapte `_ServiceStep` (`booking_flow_screen.dart:489-534`) dans son **entrée** (liste de
`SalonService`) mais pas dans sa **sortie** ni sa présentation :

- **Présentation** : `GridView` de `KioskServiceCard` (≥ 160×160 dp, §D) au lieu d'une `ListView`
  de `ListTile` — chaque carte affiche `service.imageUrl` (#158, `Image.network` avec un
  espace réservé/icône générique si `null`), le nom, le prix, la durée.
- **Cardinalité — déviation assumée par rapport à `_ServiceStep`.** `_ServiceStep` est à sélection
  **unique** (un radio par ligne, `booking_flow_screen.dart:509-521`). Le contrat « rejoindre la
  file » de #157 accepte `service_ids: list[uuid]` (voir *Problem Statement*) : `
  KioskServiceSelectionScreen` doit donc permettre une sélection **multiple** (bascule on/off par
  carte, pas de radio), avec un CTA « Continuer » désactivé tant qu'aucune prestation n'est
  sélectionnée — un changement de comportement délibéré par rapport à l'écran dont il s'inspire,
  pas un oubli.
- **Aucune coiffeuse affichée** (voir *Non-Goals* — `_HairdresserStep` n'est pas adapté).
- À la validation, appelle `queueGateway.joinQueue(salonId, customerProfileId?, serviceIds)`
  (contrat de #157) → `KioskConfirmationScreen`. Erreur réseau → message neutre + réessai, sans
  perdre la sélection déjà faite (l'action reste « toujours en direct », décision n°9).

#### F.5 — `KioskConfirmationScreen` (nouveau)

Reprend la structure visuelle de `booking_confirmation_screen.dart` (icône de succès, tuiles de
récapitulatif) en l'étendant :

- **Numéro de ticket en très grande taille** (72-96 sp, §D) — c'est l'information la plus
  importante de l'écran, le client doit pouvoir la retenir d'un coup d'œil même s'il s'éloigne
  aussitôt.
- Temps d'attente estimé (`estimated_wait_minutes`, #157), salon, prestation(s) choisies.
- **`TicketPreview`** (widget porté par la spec de #160,
  `lib/adapters/ui/kiosk/ticket_preview.dart` — cette spec **confirme** le chemin `kiosk/` retenu
  par #160) : rend à l'écran le contenu du ticket, **indépendamment** du résultat de l'impression.
- **Séquence d'impression, encadrée par le minuteur (§E)** :
  1. `KioskInactivityGuardState.of(context).pauseForPrinting()` (via un `InheritedWidget` exposant
     l'état du guard, ou un `GlobalKey<KioskInactivityGuardState>` partagé par `KioskApp`) ;
  2. `await ticketPrinterGateway.print(payload)` dans un `try/catch` sur les trois exceptions
     typées définies par #160 (`PrinterNotConnectedException`, `PrinterOutOfPaperException`,
     `PrinterWriteFailedException`), chacune affichant le message correspondant **exactement** tel
     que fixé par le contrat de #160 (§F de `specs/borne-impression-ticket-thermique.md`) ;
  3. `resumeAfterPrinting()` dans un `finally`, pour couvrir aussi bien le succès que l'échec ;
  4. **Aucun échec d'impression ne raccourcit ni ne bloque** le retour automatique — le numéro
     reste affiché à l'écran quel que soit le résultat (reprise du principe non négociable posé par
     #160, *Security & Privacy Considerations*).
- Bouton « Terminer » optionnel (retour immédiat à l'accueil sans attendre les 60 s) — un
  complément raisonnable pour un client qui a fini avant l'expiration du minuteur, sans remplacer
  le retour automatique (filet de sécurité pour un client qui s'éloigne sans y penser).

### (G) `KioskUnavailableScreen` (nouveau) — résilience réseau (décision n°9)

Écran de repli affiché quand un appel réseau **bloquant** échoue de façon non récupérable par un
simple réessai local (ex. `GetSalonDetail` au démarrage) : message neutre (« La borne est
momentanément indisponible. »), pas de détail technique, bouton « Réessayer ». Le catalogue peut
tolérer un **cache court terme** (décision n°9) — à la différence de l'identification téléphone et
de la création de ticket, qui restent **toujours en direct**, sans mode dégradé, conformément à la
même décision. Le dimensionnement exact de ce cache (durée, portée) n'est pas fixé par cette spec
et devrait rester **hors invalidation des URLs signées** de #158 (une `image_url` mise en cache
au-delà de sa durée de validité échouerait silencieusement) — point à trancher à l'implémentation,
signalé ici comme repris de la spec de #158 (*Risks* n°1).

### (H) Sortie du mode kiosque — `KioskExitGate` (nouveau, périmètre volontairement limité)

La décision produit n°11 exige que la sortie du mode kiosque et les actions de maintenance soient
« protégées par PIN gérant, journalisées ». #159 pose le **geste d'entrée** dans cet écran (un
appui long caché sur l'écran d'accueil, §F.1, ouvrant un dialogue de saisie de code réutilisant
`KioskNumericKeypad`, §F.2) sans trancher la **vérification** elle-même :

- **Option A — réutiliser la connexion personnelle existante.** Vérifier le code contre
  `POST /auth/login` (déjà existant, `SignIn`/`HttpAuthGateway` déjà écrits dans le paquet) avec les
  identifiants d'un compte `MANAGER` du salon. Avantage : **aucun développement backend
  supplémentaire**, réutilise un mécanisme déjà audité. Inconvénient : ce n'est pas un « PIN » au
  sens court/rapide du terme (mot de passe complet), et l'exigence de journalisation (décision
  n°11) est déjà satisfaite nativement si l'audit de connexion existant couvre ce cas.
- **Option B — un code PIN court, local au device.** Meilleure UX pour un geste fréquent en plein
  service, mais introduit un nouveau secret à provisionner/stocker sur le device (propriété de
  #161) et **ne journalise rien côté backend** par construction (un PIN purement local n'a aucun
  moyen d'écrire une entrée d'audit serveur) — contredirait la partie « journalisées » de la
  décision n°11 sans un appel réseau supplémentaire dédié.

Cette spec **ne tranche pas** entre A et B (voir *Risks*) : #159 se limite à prévoir le point
d'entrée UI (le geste caché + le dialogue de saisie), la logique de vérification réelle étant
soit consommée depuis l'infrastructure existante (Option A) soit coordonnée avec #161
(Option B). Dans les deux cas, la sortie du mode kiosque doit `pauseForPrinting()`-style suspendre
également le minuteur d'inactivité pendant la saisie du code (un gérant qui tape un PIN ne doit pas
être interrompu par un retour à l'accueil).

### (I) Ce qui garantit l'absence de session personnelle (critère d'acceptation)

- `main_kiosk.dart` n'importe **jamais**, directement ou transitivement,
  `lib/adapters/ui/auth/login_screen.dart`, `lib/adapters/ui/appointments/{my_appointments_screen,
  appointment_history_screen}.dart`, ni `lib/adapters/ui/receipts/receipts_screen.dart` — aucun
  fichier du dossier `lib/adapters/ui/kiosk/` ne les référence.
- `KioskApp` (§B) n'instancie **jamais** `AuthSession`, `SignIn`, `HttpAuthGateway`,
  `HttpReceiptGateway`, ni les cas d'usage `ListMyAppointments`/`ListMyAppointmentHistory`/
  `ModifyAppointment`/`CancelAppointment`/`ListMyReceipts`/`GetReceiptDetail`.
- **Il n'existe, à proprement parler, aucune notion de « session personnelle » à purger dans le
  parcours walk-in** : l'identification d'un client par téléphone (#156) ne produit ni jeton ni
  compte — `CustomerProfile` n'a ni mot de passe ni mécanisme de connexion. La seule notion
  d'authentification présente sur la borne est celle du **device** (#155), qui n'est jamais
  personnelle (elle appartient au terminal, pas au client de passage) et n'est donc, par
  construction, jamais « une session personnelle active en fin de parcours » au sens du critère
  d'acceptation.
- Conséquence directe : la garantie « aucune session personnelle en fin de parcours » est vraie dès
  la conception de `main_kiosk.dart`, pas seulement grâce au minuteur d'inactivité — le minuteur
  (§E) garantit en plus qu'un client n'abandonne pas la borne au **milieu** d'un parcours (téléphone
  tapé, fiche affichée) en la laissant visible à l'écran pour le client suivant.

## Affected Files / Packages / Modules

### `app-mobile/` — à créer

| Fichier | Rôle |
| --- | --- |
| `lib/main_kiosk.dart` | point d'entrée dédié, `runApp(const KioskApp())` |
| `lib/adapters/data/kiosk_config.dart` | override optionnel de développement local (`KIOSK_SALON_ID`, §C) — jamais utilisé en production |
| `lib/application/ports/kiosk_credential_store.dart` | port `KioskCredentialStore` — persistance sécurisée du credential device (§C) |
| `lib/adapters/data/secure_kiosk_credential_store.dart` | adaptateur `flutter_secure_storage`/Android Keystore (nouvelle dépendance, à valider) |
| `lib/adapters/ui/kiosk/kiosk_app.dart` | composition root kiosque (`KioskApp`) |
| `lib/adapters/ui/kiosk/kiosk_theme.dart` | `ThemeData` dédié (gros boutons, contraste) |
| `lib/adapters/ui/kiosk/kiosk_inactivity_guard.dart` | `KioskInactivityGuard`/`KioskInactivityGuardState` |
| `lib/adapters/ui/kiosk/kiosk_credential_entry_screen.dart` | saisie du credential device au premier lancement (§C) |
| `lib/adapters/ui/kiosk/kiosk_home_screen.dart` | écran d'accueil borne |
| `lib/adapters/ui/kiosk/kiosk_numeric_keypad.dart` | pavé numérique tactile réutilisable |
| `lib/adapters/ui/kiosk/kiosk_phone_identification_screen.dart` | identification par téléphone |
| `lib/adapters/ui/kiosk/kiosk_create_customer_screen.dart` | création de fiche walk-in |
| `lib/adapters/ui/kiosk/kiosk_service_selection_screen.dart` | choix de prestation(s), grille photo, sélection multiple |
| `lib/adapters/ui/kiosk/kiosk_service_card.dart` | carte tactile d'une prestation |
| `lib/adapters/ui/kiosk/kiosk_confirmation_screen.dart` | confirmation, numéro, ETA, impression |
| `lib/adapters/ui/kiosk/kiosk_unavailable_screen.dart` | état « borne indisponible » |
| `lib/adapters/ui/kiosk/kiosk_exit_gate.dart` | geste caché + dialogue PIN (vérification non tranchée, §H) |
| `assets/images/kiosk_logo_fallback.png` *(ou `.svg`)* | logo générique de repli hors-ligne (décision n°8) |
| `test/kiosk_inactivity_guard_test.dart` | minuterie déterministe (`tester.pump`) |
| `test/kiosk_home_screen_test.dart`, `test/kiosk_phone_identification_screen_test.dart`, `test/kiosk_create_customer_screen_test.dart`, `test/kiosk_service_selection_screen_test.dart`, `test/kiosk_confirmation_screen_test.dart` | tests par écran, faux ports locaux au fichier |

### `app-mobile/` — à modifier

| Fichier | Modification |
| --- | --- |
| `pubspec.yaml` | déclaration de la section `assets:` (actuellement commentée, `:65-74`) pour `assets/images/kiosk_logo_fallback.png` ; ajout de la dépendance `flutter_secure_storage` (credential device, §C — choix à valider) |
| `app-mobile/README.md` | nouvelle section « Mode kiosque (US-8.5, #159) » |
| `.github/workflows/ci.yml` | ajout recommandé d'une étape `flutter build apk --debug -t lib/main_kiosk.dart` (voir *Testing Plan*) — **à confirmer**, non strictement requis par l'acceptation de #159 |

### Fichiers consommés **sans modification** (dépendances directes)

`lib/adapters/data/api_config.dart`, `lib/domain/salon/salon_detail.dart`,
`lib/domain/salon/salon_service.dart` (une fois `imageUrl` ajouté par #158),
`lib/application/use_cases/get_salon_detail.dart`, `lib/adapters/data/http_salon_catalog_gateway.dart`.

### Non modifiés (référence, patrons lus mais pas touchés)

`lib/main.dart`, `lib/adapters/ui/app.dart` (`CoifLinkApp`/`AccueilEcran` restent strictement ceux
de l'app personnelle), `lib/adapters/ui/auth/login_screen.dart`,
`lib/adapters/ui/booking/booking_flow_screen.dart`,
`lib/adapters/ui/booking/booking_confirmation_screen.dart`,
`lib/adapters/ui/widgets/service_list_tile.dart`, `lib/application/ports/token_store.dart`,
`lib/application/auth_session.dart`. **Aucun** fichier `backend/` ni `web-dashboard/` n'est touché.

## API / Interface Changes

**Aucune nouvelle route backend.** #159 est un paquet **exclusivement mobile** : la matrice RBAC,
`PUBLIC_ROUTE_PATHS` et l'invariant `unprotected_routes(app)` ne sont pas concernés.

Interfaces internes au paquet mobile, **consommées** (contrats fixés par les specs sœurs du
jalon — voir *Problem Statement*) :

| Écran | Appel (nom côté #159) | Backend consommé | Contrat |
| --- | --- | --- | --- |
| `KioskHomeScreen` | `GetSalonDetail.call(salonId)` | `GET /catalog/salons/{salon_id}` (**déjà public**) | inchangé, réutilisé tel quel |
| `KioskPhoneIdentificationScreen` | `identityGateway.findByPhone(salonId, phone)` | `POST /salons/{salon_id}/kiosk/customers/lookup` (#156, **déjà spécifiée**) | `{customer_id, first_name}` si trouvé, `404` neutre sinon |
| `KioskCreateCustomerScreen` | `identityGateway.createCustomer(salonId, {firstName, lastName, phone})` | `POST /salons/{salon_id}/kiosk/customers` (#156, **déjà spécifiée**) | `{first_name, last_name, phone}` (3 champs requis, composition serveur « Prénom Nom ») → `{customer_id, first_name}`, sans mot de passe (`BACKLOG.md:442`) |
| `KioskServiceSelectionScreen` | `queueGateway.joinQueue(salonId, customerProfileId?, serviceIds)` | `POST /salons/{salon_id}/queue/tickets` (#157, **déjà spécifiée**) | `{customer_profile_id?, service_ids}` → `201 {id, ticket_number, issued_date, status, estimated_wait_minutes, created_at, service_ids}` |
| `KioskConfirmationScreen` | `ticketPrinterGateway.print(payload)` | aucun réseau (matériel local, #160) | `TicketPrintPayload{salonName, ticketNumber (int brut), issuedAt, serviceNames: List<String>}` — formatage « N° 014 » et une ligne imprimée par prestation côté formateur #160 |

**Toutes les routes consommées au-delà du catalogue public exigent un credential device (#155)** —
#159 ne les appelle jamais avec un jeton personnel ni sans authentification. La forme de cette
authentification est fixée par la spec de #155 : session device obtenue via
`POST /auth/kiosk/login`, dont la réponse inclut le `salon_id` de la borne (voir §C).

**Aucun changement de CLI, de variable d'environnement backend, ni de contrat inter-paquet
existant.** Une nouvelle variable de compilation Flutter est introduite (`APP_MODE`), au même titre
que `API_BASE_URL` déjà existante — aucune n'est un secret ; `KIOSK_SALON_ID` ne subsiste que comme
override de développement local (§C), jamais en production.

## Data Model / Protocol Changes

**Aucune migration, aucune table.** #159 introduit néanmoins deux éléments à traiter comme un
« protocole » interne au paquet mobile, par cohérence avec la façon dont la spec de #160 traite son
propre protocole ESC/POS :

1. **Le contrat de compilation kiosque** : `--dart-define=APP_MODE=kiosk` (indicateur runtime) —
   fourni au moment du build, jamais lu depuis le code métier autrement que via l'assertion de
   démarrage. L'identité du salon n'est **pas** une valeur de compilation : elle provient de la
   session device (`POST /auth/kiosk/login`, §C) ; `--dart-define=KIOSK_SALON_ID` ne subsiste que
   comme override de développement local, clairement marqué comme tel.
2. **Le contrat du minuteur d'inactivité** : 60 s de délai par défaut, 15 s de plafond de
   suspension pendant l'impression — des constantes de configuration du widget
   `KioskInactivityGuard`, pas des valeurs codées en dur ailleurs, pour rester ajustables sans
   toucher aux écrans qui les consomment.

Ces deux éléments sont des choix de configuration/comportement, pas un schéma de données — ils
n'engagent aucune compatibilité de sérialisation avec le backend.

## Security & Privacy Considerations

- **Aucune session personnelle, par construction.** Voir *Proposed Implementation* §I. Le parcours
  walk-in de #159 ne produit ni ne lit jamais de jeton `AuthSession` — la seule identité en jeu est
  celle du **device** (#155), jamais celle d'un client individuel.
- **Exposition minimale du client à l'écran, cohérente avec #156.** `KioskPhoneIdentificationScreen`
  n'affiche **jamais** autre chose que le prénom d'un client retrouvé — jamais le nom complet, le
  téléphone normalisé, ni aucune autre fiche que celle en cours d'interaction (une borne est un
  terminal **partagé**, contrairement à un mobile personnel).
- **Clavier numérique dédié, pas seulement une question d'ergonomie.** Au-delà du confort tactile
  (§D), un pavé numérique **interne à l'app** évite de déclencher le clavier logiciel natif de
  l'OS pour un champ de type téléphone — ce qui évite, sur un terminal **public et partagé**, tout
  risque de suggestion/autocomplétion de numéros précédemment saisis par un autre client via les
  mécanismes d'IME natifs (contrairement à un mobile personnel, où ce risque n'existe pas puisque
  l'utilisateur est le même d'une session à l'autre).
- **Purge par disposition de widgets, pas par effacement actif.** Comme documenté en *Relevant
  Repository Context* et *Proposed Implementation* §E : rien de ce que le parcours manipule
  (téléphone tapé, fiche trouvée/créée, sélection de prestations) n'est jamais écrit sur
  `SharedPreferences`/disque — un retour à l'accueil (minuteur ou bouton « Terminer ») **est** la
  purge complète, garantie par le fait que ces données ne vivent que dans le `State` d'écrans
  disposés par Flutter en sortant de la pile de navigation.
- **Aucune donnée personnelle du client sur le ticket imprimé.** #159 construit un
  `TicketPrintPayload` (contrat de #160) qui ne porte **ni nom ni téléphone** — seulement salon,
  numéro, date/heure, prestation(s) — cohérent avec la restriction déjà posée par la spec de #160
  (*Security & Privacy Considerations*), justifiée par le fait qu'un ticket papier peut finir
  ramassé par un tiers dans une salle d'attente publique.
- **Résilience réseau, sans mode dégradé sur les actions sensibles (décision n°9).**
  L'identification téléphone et la création de ticket restent **toujours en direct** : aucune
  file d'attente locale, aucune écriture optimiste non confirmée par le serveur — un échec réseau
  sur ces deux actions se traduit par un message d'erreur et un réessai, jamais par une action
  silencieusement retardée qui pourrait produire un doublon ou un ticket fantôme.
- **Sortie du mode kiosque non résolue = surface à traiter avec rigueur avant livraison.** Tant que
  §H n'est pas tranché (Option A/B), #159 ne doit **pas** exposer de geste de sortie qui contourne
  la vérification prévue par la décision n°11 — le geste caché doit rester inerte (afficher un
  message « fonctionnalité de maintenance à venir ») plutôt que de sortir du mode kiosque sans
  aucune vérification, si l'implémentation de la vérification choisie n'est pas encore prête.
- **Pas d'implication pour l'anti-oracle ADR-0026 au niveau de #159.** La règle anti-oracle
  (ne jamais interroger `users` par téléphone) est une propriété du **backend** de #156 ; #159 ne
  fait qu'afficher le résultat qu'on lui retourne — il n'introduit aucune requête supplémentaire ni
  aucun canal qui pourrait révéler l'existence d'un compte personnel.
- **Aucun secret dans `--dart-define`.** `APP_MODE` (et l'override de développement
  `KIOSK_SALON_ID`, §C) ne sont pas des secrets (un `salon_id` est déjà une donnée publique du
  catalogue) — cohérent avec la règle déjà appliquée à `API_BASE_URL` (`api_config.dart:3-5`). Le
  **credential device** (#155), lui, est un secret : il ne transite jamais par `--dart-define` —
  saisi à l'écran au premier lancement et persisté via `KioskCredentialStore` (stockage sécurisé,
  §C), il n'apparaît ni dans une commande de build ni dans le binaire.

## Testing Plan

Test gate mobile uniquement : `flutter test`. **Aucun** impact sur `pytest` backend ni `npm test`
web (aucun fichier de ces paquets n'est touché).

### Minuteur d'inactivité (`test/kiosk_inactivity_guard_test.dart`, nouveau)

- Utiliser `WidgetTester.pump(Duration)` (déterministe, sans horloge réelle) pour vérifier :
  - aucune navigation vers l'accueil avant `timeout` (59 s) sans interaction ;
  - un évènement de pointeur simulé (`await tester.tapAt(...)` ou l'injection directe d'un
    `PointerDownEvent`) **réinitialise** le compte à rebours — un nouveau délai complet doit
    s'écouler avant le retour ;
  - après `timeout` sans interaction, `popUntil((route) => route.isFirst)` est bien appelé (assertion
    sur la route affichée, ou sur un compteur d'appels dans un faux `NavigatorObserver`) ;
  - `pauseForPrinting()` empêche tout retour avant le plafond de 15 s même en l'absence
    d'interaction ; `resumeAfterPrinting()` appelé avant 15 s relance normalement le délai de 60 s ;
    l'absence d'appel à `resumeAfterPrinting()` déclenche malgré tout le retour à 15 s pile.

### Écrans (patron `_StubGateway`, `salon_search_screen_test.dart:20-30`)

- **`kiosk_home_screen_test.dart`** : rendu du nom de salon (faux `GetSalonDetail` réussi) ; repli
  sur le logo générique bundlé si `GetSalonDetail` échoue ou `logoUrl` est `null` ; le CTA
  « Commencer » navigue vers l'identification.
- **`kiosk_phone_identification_screen_test.dart`** : un faux gateway d'identité couvrant trois cas
  — trouvé (affiche **uniquement** le prénom, jamais le nom complet ni le téléphone dans l'arbre de
  widgets, assertion `find.text` négative sur ces valeurs) ; absent (navigue vers la création) ;
  erreur réseau (message neutre + bouton réessayer, aucune navigation automatique).
- **`kiosk_create_customer_screen_test.dart`** : validation minimale du formulaire, appel de
  création avec les bons champs, absence de champ mot de passe dans l'arbre de widgets.
- **`kiosk_service_selection_screen_test.dart`** : sélection **multiple** (activer deux cartes,
  vérifier que `service_ids` transmis contient les deux identifiants) — non-régression explicite du
  choix de cardinalité par rapport à `_ServiceStep` ; CTA désactivé tant qu'aucune sélection.
- **`kiosk_confirmation_screen_test.dart`** : rendu du numéro de ticket et de l'ETA depuis un faux
  résultat de `joinQueue` ; les trois branches d'erreur d'impression (faux
  `TicketPrinterGateway` levant chacune des exceptions de #160) affichent le message correspondant
  **sans** empêcher le bouton « Terminer »/le minuteur de fonctionner (vérifier que
  `resumeAfterPrinting()` est bien appelé même en cas d'exception, via un faux guard injecté).

### Non-régression

- Aucun test existant (`test/widget_test.dart`, `test/salon_search_screen_test.dart`,
  `test/*booking*`, `test/*receipt*`) n'est affecté : #159 n'ajoute que des fichiers nouveaux sous
  `lib/adapters/ui/kiosk/`, `lib/adapters/data/kiosk_config.dart` et `lib/main_kiosk.dart`, sans
  modifier `lib/main.dart` ni `lib/adapters/ui/app.dart`.
- `flutter analyze` couvre automatiquement les nouveaux fichiers (analyse tout `lib/**`,
  indépendamment du point d'entrée).
- **CI (`*.github/workflows/ci.yml:174`)** ne construit aujourd'hui que `flutter build apk --debug`
  (entrée par défaut, `lib/main.dart`) — le second point d'entrée `main_kiosk.dart` **n'est pas**
  couvert par ce build. *Recommandation* : ajouter une étape `flutter build apk --debug -t
  lib/main_kiosk.dart` pour détecter une régression de compilation sur ce second entry point ;
  **à confirmer avec le porteur produit/CI** (coût : quelques dizaines de secondes de CI
  supplémentaires, bénéfice : détection immédiate d'un import cassé côté kiosque).

## Documentation Updates

- **`app-mobile/README.md`** — nouvelle section « Mode kiosque — borne libre-service (US-8.5,
  #159) », sur le patron de la section « Mes reçus » (`README.md:183` et suivantes) : arborescence
  des nouveaux fichiers, les `--dart-define` (`APP_MODE`, `API_BASE_URL`), commande de
  build/lancement (`flutter run -t lib/main_kiosk.dart --dart-define=APP_MODE=kiosk
  --dart-define=API_BASE_URL=...`), la saisie du credential device au premier lancement (§C — le
  `salon_id` vient de la session device ; `KIOSK_SALON_ID` uniquement comme override de
  développement local), et un rappel explicite que ce point d'entrée est **Android-first**
  (ADR-0001) comme le reste de l'app.
- **Pas de nouvel ADR créé par #159.** Comme #158 et #160 avant elle, cette spec **ne crée pas**
  d'ADR séparée : le jalon M7 produit deux ADR distinctes — **ADR-0041** (authentification borne,
  committée avec l'implémentation de #155) et **ADR-0042** (file d'attente walk-in `QueueTicket`,
  committée avec #157). Les décisions structurantes que #159 soulève (choix `-t` + `--dart-define`
  plutôt que des flavors, mécanisme du minuteur d'inactivité `Listener`+`Timer`, question ouverte
  sur la vérification du PIN de sortie) sont consignées dans cette spec et la section README du
  mode kiosque ; celles qui touchent au provisioning alimentent le **runbook** rédigé par #161
  (« ADR, documentation & procédure de provisioning borne »), qui vérifie aussi la présence des
  deux ADR et met à jour `docs/adr/README.md`.
- **`pubspec.yaml`** : commentaire explicatif au-dessus de la nouvelle section `assets:` (patron des
  commentaires déjà présents au-dessus de `http`/`share_plus`, `pubspec.yaml:38-39`).
- **`BACKLOG.md`/`README.md` (racine)** : non modifiés par #159 — la mise à jour du PRD/BACKLOG une
  fois le jalon M7 livré est explicitement le périmètre de #161.

## Risks and Open Questions

Cette section reprend les décisions de la liste d'architecture retenue pour M7 qui concernent
**directement** #159, comme choix à valider par le porteur produit avant l'implémentation réelle,
ainsi que les questions ouvertes propres à cette spec.

### Décisions M7 directement concernées

1. **Décision n°3 (terminal & mode kiosque).** `main_kiosk.dart` + `--dart-define=APP_MODE=kiosk`,
   pas de flavors pour ce MVP — justifié en détail en *Proposed Implementation* §A, avec la liste
   des déclencheurs d'un futur passage à de vrais flavors. **Point non couvert par cette spec** :
   l'activation native d'Android Lock Task Mode (`startLockTask()`) est un appel de plateforme côté
   Flutter que #159 **pourrait** ajouter en complément (pour que l'app elle-même demande le
   verrouillage au lancement, plutôt que de dépendre uniquement d'une configuration MDM/device-owner
   externe) — non tranché ici, **à confirmer** avec l'implémenteur et #161 (qui documente
   l'enrôlement).
2. **Décision n°7 (inactivité & retour auto, 60 s / suspension 15 s).** Implémentée par
   `KioskInactivityGuard` (§E). **Point de coordination avec #160** : le plafond de 15 s doit courir
   depuis l'appel `print()`, pas depuis une éventuelle reconnexion Bluetooth — #159 doit donc
   supposer une connexion imprimante déjà établie en amont de la confirmation (recommandation reprise
   de la spec de #160, *Risks* n°2), ce qui suppose que `EscPosTicketPrinterGateway.connect()` soit
   appelé de façon proactive dès l'écran d'accueil (§F.1) plutôt qu'à la confirmation — **à
   coordonner explicitement avec l'implémenteur de #160**.
3. **Décision n°8 (borne mono-salon).** Traduite par la session device (§C) : le `salon_id` est
   porté par le credential device et retourné par `POST /auth/kiosk/login` (#155) — mécanisme
   retenu pour tout le jalon, un APK unique pour toutes les bornes. Le
   `--dart-define=KIOSK_SALON_ID` par device n'est **pas** retenu en production (recompilation ou
   valeur à provisionner par borne physique) ; il ne subsiste que comme override de développement
   local, clairement marqué comme tel.
   Le repli sur un logo générique bundlé (premier asset local du paquet) est un changement mineur
   mais réel de l'outillage (`pubspec.yaml`) — à valider dans la même PR.
4. **Décision n°9 (résilience réseau).** Traduite en `KioskUnavailableScreen` (§G) et en la règle
   « identification/création de ticket toujours en direct ». **Question ouverte reprise de la spec
   de #158** (*Risks* n°1) : la durée de mise en cache court-terme du catalogue (et donc des
   `image_url` signées, à durée de validité limitée) n'est fixée par aucune décision produit — à
   trancher à l'implémentation, sans bloquer #159 qui peut démarrer sans cache (rafraîchissement à
   chaque affichage de l'écran de choix de prestation) en V1.
5. **Décision n°11 (sécurité opérationnelle — PIN gérant, journalisation).** #159 pose le geste
   d'entrée (`KioskExitGate`, §H) sans trancher la vérification (Option A : réutiliser
   `/auth/login` existant ; Option B : PIN court local, à coordonner avec #161). **Décision
   structurante à prendre avant l'implémentation** — elle conditionne si #159 a besoin d'un nouveau
   port (`ManagerPinVerifier` ou équivalent) ou peut se contenter de réutiliser `SignIn`/
   `HttpAuthGateway` déjà écrits pour l'app personnelle (en les important, cette fois, uniquement
   dans le contexte de sortie du mode kiosque — ce qui ne contredit pas §I, puisque ce n'est plus
   une « session personnelle active en fin de parcours **client** », mais un geste de maintenance
   gérant qui met délibérément fin au parcours kiosque).

### Questions ouvertes propres à #159

- **Correspondance « US-00N » ↔ parcours PRD §17.4.** Voir *Problem Statement* — hypothèse non
  confirmée, en particulier pour le sort de l'étape 3 (« J'ai un rendez-vous »/« Je viens sans
  rendez-vous »). *Recommandation : ne construire aucune branche RDV*, cohérent avec les
  *Non-Goals* de M7 dans son ensemble ; **à confirmer** si un affichage inerte de ce choix est
  malgré tout attendu pour la cohérence perçue avec le PRD.
- **Bouton « Continuer sans identification ».** Repris de la spec de #157 (*Risks* n°10 — ticket
  anonyme, qui la laisse elle-même ouverte côté domaine) : `customer_profile_id` est nullable dans
  le contrat « rejoindre la file », mais l'UX n'est tranchée par aucune spec. *Recommandation : exiger une
  identification ou une création de fiche avant le choix de prestation* (cohérent avec les cinq
  écrans explicitement listés par la mission de #159, qui ne mentionnent aucun chemin « anonyme »).
  **À confirmer avec le porteur produit et l'implémenteur de #156.**
- **Chiffres de conception « gros boutons » (§D).** Les tailles/contrastes proposés sont des
  cibles de premier jet, pas une revue UX/accessibilité formelle — *recommandation : les faire
  valider par une revue dédiée* (idéalement avec un test sur tablette physique en conditions de
  salon) avant de les figer dans `kiosk_theme.dart`.
- **Ajout d'une étape de build kiosque à `ci.yml`.** Recommandé (*Testing Plan*) mais non requis
  par l'acceptation littérale de #159 — **à confirmer** avec le porteur produit/l'équipe CI, le
  coût étant marginal (un second `flutter build apk --debug -t ...`).
- **Dérive éventuelle des contrats de #155/#156/#157 à la livraison.** Ces briques backend sont
  désormais **livrées** (`POST /auth/kiosk/login` + le credential device pour #155 ;
  lookup/création `{customer_id, first_name}` pour #156 ; `POST /salons/{id}/queue/tickets` pour
  #157) ; les noms de ports (`HttpKioskIdentityGateway`, `HttpKioskQueueGateway`) et de méthodes
  (`findByPhone`, `createCustomer`, `joinQueue`) restent des choix propres à #159. **À revalider en
  tout début d'implémentation de #159** contre le code réellement livré (formes JSON exactes,
  en-têtes d'authentification device).

## Implementation Checklist

1. **Lire** `lib/main.dart`, `lib/adapters/ui/app.dart` (`CoifLinkApp`, `AccueilEcran`),
   `lib/adapters/ui/booking/booking_flow_screen.dart` (`_ServiceStep`, `_HairdresserStep`),
   `lib/adapters/ui/booking/booking_confirmation_screen.dart`, `lib/adapters/ui/auth/login_screen.dart`,
   `lib/application/ports/token_store.dart`, `lib/adapters/data/api_config.dart`,
   `lib/adapters/ui/salon_search_screen.dart` (debounce) — s'imprégner des patrons existants et de
   leurs limites documentées.
2. **Revalider les contrats livrés de #155/#156/#157/#158** au démarrage de l'implémentation (specs
   **et** code backend désormais livrés) — ajuster les noms de ports/méthodes de cette spec aux
   formes JSON et en-têtes réels.
3. **Trancher les questions ouvertes** structurantes (US-003/branche RDV, bouton « sans
   identification », mécanisme de vérification du PIN de sortie, chronologie `connect()` imprimante
   proactif) avant d'écrire du code.
4. **Credential device** : créer le port `KioskCredentialStore`, son adaptateur sécurisé
   (`flutter_secure_storage`/Android Keystore, dépendance à valider) et
   `kiosk_credential_entry_screen.dart` (§C) ; réduire `lib/adapters/data/kiosk_config.dart` à
   l'override de développement local `KIOSK_SALON_ID`.
5. **Thème** : créer `lib/adapters/ui/kiosk/kiosk_theme.dart` (tailles/contrastes §D, à valider par
   une revue UX avant de figer les valeurs définitives).
6. **Minuteur** : créer `lib/adapters/ui/kiosk/kiosk_inactivity_guard.dart` ; écrire
   `test/kiosk_inactivity_guard_test.dart` **avant** de le brancher sur un écran (mécanisme testable
   isolément).
7. **Écrans, dans l'ordre du parcours** : `kiosk_home_screen.dart` →
   `kiosk_numeric_keypad.dart` + `kiosk_phone_identification_screen.dart` →
   `kiosk_create_customer_screen.dart` → `kiosk_service_card.dart` +
   `kiosk_service_selection_screen.dart` → `kiosk_confirmation_screen.dart` (avec câblage de
   `pauseForPrinting`/`resumeAfterPrinting` et des trois messages d'erreur de #160) —
   chaque écran accompagné de son test avant de passer au suivant.
8. **Résilience** : créer `kiosk_unavailable_screen.dart`, câbler la bascule depuis
   `kiosk_home_screen.dart` en cas d'échec de `GetSalonDetail`.
9. **Sortie du mode kiosque** : créer `kiosk_exit_gate.dart` (geste + dialogue), avec la
   vérification tranchée à l'étape 3 (Option A ou B) — garder le geste **inerte** si la
   vérification n'est pas prête (voir *Security & Privacy Considerations*).
10. **Composition root** : créer `lib/adapters/ui/kiosk/kiosk_app.dart` (`KioskApp`), assembler
    `ApiConfig`, la session device et `KioskCredentialStore` (§C), les gateways kiosque,
    `KioskInactivityGuard`, `KioskHomeScreen`.
11. **Point d'entrée** : créer `lib/main_kiosk.dart`.
12. **Assets** : ajouter `assets/images/kiosk_logo_fallback.png`, déclarer la section `assets:` dans
    `pubspec.yaml` (actuellement commentée) avec un commentaire explicatif.
13. **Tests** : exécuter `flutter test` (tous les nouveaux fichiers) et `flutter analyze` ;
    vérifier qu'aucun test existant n'est affecté.
14. **CI** (si confirmé, voir *Risks*) : ajouter l'étape `flutter build apk --debug -t
    lib/main_kiosk.dart` à `.github/workflows/ci.yml`.
15. **Documentation** : section « Mode kiosque » dans `app-mobile/README.md` ; consigner les
    décisions structurantes dans cette spec/le README et alimenter le runbook de provisioning de
    #161, sans créer d'ADR séparée (les deux ADR du jalon — 0041 avec #155, 0042 avec #157 — sont
    portées par ces issues).
16. **Vérification finale** : `flutter test` au vert (aucun test backend/web affecté) ; relire la
    PR pour confirmer qu'**aucun** écran du dossier `lib/adapters/ui/kiosk/` n'importe
    `AuthSession`/`SignIn`/les écrans personnels, qu'**aucune PII** (nom complet, téléphone) n'est
    affichée au-delà du prénom ou imprimée sur le ticket, et qu'**aucune signature IA** n'a été
    introduite dans le code, les commits ou la PR.
