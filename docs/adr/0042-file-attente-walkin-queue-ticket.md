# ADR-0042 : File d'attente walk-in — ticket de passage `QueueTicket` indépendant d'`Appointment`, numérotation par salon+jour & estimation d'attente V1

- **Statut** : Accepté
- **Date** : 2026-08-11
- **Décideurs** : équipe CoifLink
- **Issue** : #157 (US-8.3 · Ticket de passage walk-in & estimation d'attente) — jalon **M7** (Borne
  client, Épic 8)
- **Référence PRD** : §4.1 (permissions par rôle), §8.1 (rendez-vous ≥ 1 prestation), §11.2 (isolation
  par salon), §11.3 (non-fuite PII), §11.4 (journalisation), §17 (Borne Intelligente d'Accueil)
- **S'appuie sur** : [ADR-0041](./0041-authentification-borne-kiosque.md) (#155, rôle `TERMINAL` +
  `QUEUE_TICKET_CREATE`), [ADR-0040](./0040-impression-recu-encaissement-gerant.md) (#154, numérotation
  séquentielle par salon — verrou consultatif transactionnel + `MAX+1`),
  [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (#12, RBAC deny-by-default),
  [ADR-0026](./0026-fiche-client-portee-salon.md) (#28, anti-oracle fiche client)
- **Spec de planification** : [`specs/us-8-3-ticket-passage-walkin-estimation-attente.md`](../../specs/us-8-3-ticket-passage-walkin-estimation-attente.md)

## Contexte et problème

Le jalon M7 (PRD §17) livre le parcours « client sans rendez-vous » : #155 dote la borne d'une identité
(`TERMINAL`), #156 lui donne de quoi identifier un client (recherche téléphone / création walk-in). Il
manque la **pièce centrale** : délivrer au client identifié un **numéro de passage**, une **estimation
d'attente**, et le faire apparaître dans la file du personnel pour qu'il soit pris en charge.

Deux faits du dépôt (état vérifié au commit `4320171`) structurent la décision :

1. **`Appointment.client_id` est `NOT NULL` (FK `users`).** Un walk-in obtient, dans le cas général,
   une `CustomerProfile` **sans compte** (`user_id = NULL`) ; l'entité de domaine `Customer` n'expose
   même pas `user_id` (anti-oracle ADR-0026). Un ticket walk-in ne peut donc **pas** devenir une ligne
   `appointments` sans exiger un compte (contradiction avec le walk-in) ou assouplir le schéma.
2. **La seule « file d'attente » livrée (#150/#152) est un outil de pointage sur RDV déjà planifiés** :
   `domain/queue.py` dérive un statut d'un `Appointment` réel — aucune notion de numéro de passage,
   d'estimation d'attente ni de client sans RDV n'existe.

## Décision

### 1. Un domaine `QueueTicket` **indépendant d'`Appointment`**, migration additive dédiée

Nouvelle entité pure `domain/queue_ticket.py` + deux tables (`queue_tickets`, `queue_ticket_services`,
migration `0014` strictement **additive**). Aucune ligne `appointments`/`services`/`customer_profiles`
n'est modifiée. `QueueTicket.customer_profile_id` est **nullable** (ticket anonyme possible) ;
`hairdresser_id` référence `users.id` (identifiant de compte, appartenance salon vérifiée
**applicativement**, miroir exact d'`Appointment.hairdresser_id`). Cycle de vie fermé
`waiting → called → in_progress → done` (+ `expired`), machine à états pure miroir d'`AppointmentStatus`.

**Alternative écartée** : réutiliser `appointments` avec un pseudo-`client_id` (compte technique
« walk-in »). Rejetée — il polluerait toutes les lectures « mes rendez-vous » et casserait l'hypothèse
`client_id → un seul client réel` exploitée par stats/notifications/historique.

### 2. Numérotation séquentielle par salon **et** jour civil, sûre en concurrence (patron ADR-0040)

`ticket_number` redémarre à 1 chaque jour civil du salon (`Africa/Abidjan`). `SqlQueueTicketRepository.
create` décline exactement le patron `receipt_number` : `SELECT pg_advisory_xact_lock(hashtext(:key))`
(clé `salon_id:issued_date`) puis `MAX(ticket_number)+1` dans la **même** transaction, `flush` sans
`commit`. La contrainte `UNIQUE (salon_id, issued_date, ticket_number)` est le filet ultime (course
improbable → `IntegrityError`, jamais une corruption). Pas de nouvelle table de compteur, pas de job de
purge — le compteur reparte à 1 par la seule clé de verrou/`WHERE`.

**Alternative écartée** : une séquence PostgreSQL nommée par salon redémarrée par cron — DDL dynamique
par salon (potentiellement des milliers de séquences) + dépendance à un ordonnanceur absent du dépôt.

### 3. Formule V1 d'estimation d'attente, explicite et bornée

`estimate_wait_minutes(position, average_service_minutes, active_hairdresser_count)` =
`position × durée moyenne des prestations des tickets actifs (waiting + in_progress) ÷ coiffeuses
ACTIVE`, arrondie (jamais tronquée). Filets pour les cas dégénérés : aucune coiffeuse active →
constante documentée (`DEFAULT_WAIT_MINUTES_NO_STAFF = 30`, **jamais** de division par zéro) ; file
encore vide → repli sur la moyenne des prestations **de ce ticket** ; aucune durée exploitable → `0`.
L'estimation est **calculée une fois à l'émission** et **stockée telle quelle** (jamais recalculée en
lecture) : le ticket imprimé (#160) affiche une valeur **stable** même si la file évolue. Heuristique
**assumée perfectible** (pas de progression réelle des prestations en cours, pas de spécialité de
coiffeuse, aucune donnée historique).

### 4. Visibilité gérant par **fusion en lecture**, jamais en écriture

`GET /salons/{salon_id}/queue` **évolue** d'une `list[QueueEntryResponse]` vers un objet à deux clés
`{appointments, walk_in_tickets}`. `appointments` reprend **champ à champ** l'ancien contenu (aucune
régression du contrat RDV) ; `walk_in_tickets` compose une **troisième source**
(`QueueTicketRepository.list_active_for_salon`, tickets du jour hors `expired`) **sans jamais** créer,
mettre à jour ni référencer une ligne `appointments`. Les deux tableaux restent **distincts** (un
walk-in n'a ni `appointment_id` ni créneau ; tri par `ticket_number` vs `start_time`). Rupture de forme
**mineure et assumée** : le consommateur unique (`web-dashboard/.../queue-board.tsx`) est mis à jour
dans la même PR.

### 5. Gardes RBAC — **réutilisation**, aucune nouvelle permission

- « Rejoindre la file » (`POST /salons/{id}/queue/tickets`) : `require_salon_scope` +
  `require_permission(QUEUE_TICKET_CREATE)` — permission **déjà** détenue par le seul `TERMINAL` (#155).
- Prise en charge / clôture (`.../start`, `.../complete`) : `require_salon_scope` +
  `require_permission(APPOINTMENT_UPDATE_STATUS)` — **mêmes acteurs** (coiffeuse + gérant) que le
  démarrage d'un RDV. Aucune permission dédiée `QUEUE_TICKET_MANAGE` créée : la matrice
  `ROLE_PERMISSIONS` n'est pas modifiée.

Aucune route n'entre dans `PUBLIC_ROUTE_PATHS` : « public/terminal » qualifie l'usage (un terminal en
salle d'accueil), pas le régime d'authentification (deny-by-default inchangé).

### 6. Journalisation ciblée

`QUEUE_TICKET_STARTED`/`QUEUE_TICKET_COMPLETED` (entité `queue_ticket`, `metadata={}`) tracent les
**actions humaines** de prise en charge/clôture (miroir `APPOINTMENT_STARTED`). L'**émission** d'un
ticket par la borne n'est **pas** journalisée au journal d'audit gérant (aucune action humaine de
gestion, aucune PII propre au ticket).

### 7. Impression physique du ticket (#160) — packages, sélection imprimante, portée V1

Le ticket **papier** annoncé au point 3 (« M7 assume un ticket papier #160 ») livre
`EscPosTicketPrinterGateway` (`app-mobile/lib/adapters/data/`), qui implémente le port
`TicketPrinterGateway` déjà posé par #159 (`connect`/`print`/`status` + trois exceptions typées neutres).
Décisions structurantes prises pour cette livraison :

- **Deux packages, séparation formatage/transport** : `esc_pos_utils_plus` (générateur ESC/POS pur,
  `TicketEscPosFormatter`, aucune dépendance de transport — testable sans matériel ni plugin) et
  `flutter_thermal_printer` (transport Bluetooth, `EscPosTicketPrinterGateway`). Alternative écartée :
  `esc_pos_bluetooth`, obsolète (~4 ans) et sans story Android 12+ claire.
- **Code page `CP1252`** (Windows-1252/Western Europe, profil `default` d'`esc_pos_utils_plus`) pour les
  accents français du ticket — pas de `PosCodeTable` dédié dans ce package, la table est un simple nom de
  code page résolu par le profil de capacités chargé au runtime.
- **Bluetooth uniquement en V1**, pas d'USB : le parc de bornes n'a pas de port USB accessible côté
  client, et une imprimante thermique 80mm Bluetooth reste le matériel courant. Le port
  `PrinterDeviceScanGateway` isole ce choix — l'USB pourra être ajouté plus tard sans changer le contrat.
- **Sélection de l'imprimante — setup ponctuel, jamais au moment d'imprimer.** Aucun appairage OS
  préalable n'est supposé : `TerminalPrinterSetupScreen` (nouvel état `printerSetup` de
  `TerminalBootstrap`) lance une recherche Bluetooth active, affichée **une seule fois**, juste après la
  première activation de la borne — tant que `TicketPrinterDeviceStore` (persistance sécurisée de
  l'identifiant choisi, même mécanisme que `TerminalCredentialStore`) n'a rien enregistré. Non bloquant
  (« Configurer plus tard » mène quand même à l'accueil, cohérent avec la décision n°9 « toujours en
  direct » de la spec #159) — `EscPosTicketPrinterGateway.connect()` relit ensuite cet identifiant à
  chaque connexion, sans jamais proposer de choix pendant le parcours client.
- **Reprise manuelle après échec (#171)** : `TerminalPrintScreen` affiche un bouton « Réessayer »
  **uniquement** après un échec d'impression (relance `print`), sans remplacer « Terminer » — le client
  peut toujours repartir quel que soit le résultat, seul le cas d'échec que #171 signalait est couvert.
- **Pas d'ETA imprimée** : l'estimation (point 3) reste volatile et propre à l'écran, jamais reportée sur
  le papier. **Pas de PII client** sur le ticket (déjà garanti par `TicketPrintPayload`, #159).
- **Panne papier non détectée** : `flutter_thermal_printer` ne remonte aucun signal dédié « hors papier »
  — un échec d'écriture matériel se traduit toujours par `PrinterWriteFailedException`, jamais
  `PrinterOutOfPaperException` (réservée à un futur plugin/firmware qui l'exposerait).

### 8. Une coiffeuse ne sert qu'un seul ticket `in_progress` à la fois, portée globale (#173)

Rien n'empêchait jusqu'ici d'affecter la même coiffeuse à deux tickets `in_progress`
simultanément — ni le sélecteur « Choisir une coiffeuse » du dashboard gérant (aucun filtre), ni
`StartQueueTicket.execute()` (seules préconditions : ticket `waiting`, coiffeuse `ACTIVE` du
salon), ni la garde TOCTOU du dépôt (`WHERE status = 'waiting'`, ne porte que sur le ticket cible).
Décisions :

- **Contrainte base comme arbitre final**, pas seulement un filtre cosmétique — même patron que
  `CustomerAlreadyExists`/`uq_customer_profiles_salon_phone` (ADR implicite du point 1) : index
  unique partiel `uq_queue_tickets_hairdresser_in_progress` sur `queue_tickets(hairdresser_id)
  WHERE status = 'in_progress'` (migration `0021`), retraduit par `SqlQueueTicketRepository.start()`
  en `HairdresserAlreadyBusy` (`409`) ; pré-contrôle applicatif
  (`QueueTicketRepository.is_hairdresser_busy`) pour un message immédiat, sans attendre la course.
- **Portée volontairement globale, pas par salon** — dérogation délibérée à l'isolation stricte
  §11.2 suivie partout ailleurs dans ce schéma : une personne ne peut physiquement servir qu'un
  seul client à la fois, quel que soit le salon où elle est staff. Aujourd'hui sans conséquence
  pratique observable (`POST .../employees` refuse tout doublon de téléphone, aucune route ne
  permet encore de rattacher une coiffeuse existante à un second salon) mais la contrainte est
  posée correctement dès maintenant plutôt que d'être resserrée plus tard par erreur.
  **Alternative écartée** : contrainte par salon (`UNIQUE (salon_id, hairdresser_id) WHERE status
  = 'in_progress'`) — rejetée car elle autoriserait, si le multi-salon devient possible, qu'une
  même personne apparaisse « en cours » dans deux salons à la fois.
- **Prédicat frontend purement cosmétique** (`isHairdresserBusy`, `web-dashboard/src/domain/
  queue/queue.ts`) : exclut du sélecteur d'assignation une coiffeuse déjà `in_progress` sur un
  autre ticket **du jour consulté**, sans appel serveur dédié — recalculé à chaque rendu à partir
  des tickets déjà chargés par la page. Le filtre toolbar « Filtrer par coiffeuse » reste
  volontairement **non filtré** (une coiffeuse occupée doit rester trouvable pour retrouver son
  ticket en cours) — les deux listes partagent désormais un roster commun plutôt que l'une dérivant
  de l'autre, pour éviter qu'un filtrage se propage involontairement à l'autre usage.

## Conséquences

- **Positif** : parcours walk-in complet et cohérent sans toucher au chemin d'écriture éprouvé de la
  réservation (#21/#22) ; numérotation robuste réutilisant un patron déjà en production ; PII minimisée
  à l'écran partagé (prénom seul, aligné #156) ; aucune nouvelle frontière de transaction ni de droit ;
  impression papier livrée sans exposer de sélection d'imprimante au client (#160) ; une coiffeuse ne
  peut plus être affectée à deux tickets `in_progress` à la fois, garanti au niveau base (#173).
- **Limites assumées (V1)** : l'estimation d'attente est heuristique ; le walk-in **ne pèse pas** dans
  les statistiques revenu/fréquentation (qui s'appuient sur `Appointment`/`Payment.appointment_id`) —
  un travail de schéma dédié serait nécessaire s'il le fallait, hors #157 ; l'**expiration** d'un ticket
  oublié (`waiting → expired`) est un statut **atteignable** mais non déclenché automatiquement (aucun
  ordonnanceur dans le dépôt) ; le **rate-limiting** de la création de tickets relève de la garde
  `TERMINAL` (#155) ou d'un middleware transverse, à vérifier avant généralisation ; l'impression papier
  (#160) est Bluetooth-only et suppose une imprimante déjà sélectionnée au setup, sans détection de panne
  papier ni changement d'imprimante après coup (redémarrage/réinstallation requis, hors #161).
- **Suivis** : facturation liée au ticket (aucun `ticket_id` sur `Payment` — l'encaissement walk-in
  reste un encaissement `service_id`-only classique, déjà possible) ; affinage de l'ETA (données
  historiques) ; transport USB pour l'impression si un besoin terrain apparaît ; changement d'imprimante
  après le setup initial, probablement via le menu de maintenance protégé par PIN gérant que #161 doit
  encore trancher (`showTerminalExitGate`, actuellement inerte) ; la portée globale de la contrainte
  coiffeuse-occupée (#173) reste non exercée en pratique tant qu'aucune route ne permet le staffing
  multi-salon — à revisiter si cette fonctionnalité est introduite.
