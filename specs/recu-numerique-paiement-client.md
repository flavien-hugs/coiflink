# Reçu numérique de paiement (client) (US-5.5)

> Spécification de planification pour l'issue GitHub **#38 — US-5.5 : Reçu numérique de paiement
> (client)** (`feature` `payments` · **Could** · Effort **S** · PRD §6 Épic 5 / §5.3 « Parcours
> encaissement » / §8.4 « Notifications » / §11.2/§11.3 « Sécurité & PII »). **Dépend de #33**
> (enregistrement d'un paiement, livré). **Cette spec ne produit pas de code** : elle décrit l'approche
> à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 5, US-5.5) pose le besoin : **« en tant que client, je veux recevoir un reçu
numérique après paiement, pour garder une preuve de la transaction »**. Le critère d'acceptation de
l'issue #38 est unique et minimal :

- **Un reçu est généré/envoyé après paiement.**

### État actuel du dépôt (vérifié pour cette spec)

L'**enregistrement d'un paiement est livré** (#33/#34) : `POST /salons/{salon_id}/payments`
(`adapters/inbound/payments.py::record_payment`) crée un `Payment` **`VALIDATED`**, lié à un
RDV/prestation, **montant vérifié cohérent**, inscrit au journal de caisse (ligne `PAYMENT`) et
journalisé (`PAYMENT_RECORDED`). Le paiement porte un champ **`client_id` optionnel**
(`PaymentCommand.client_id`, colonne `payments.client_id` FK `users.id`). **C'est le seul lien
existant entre un paiement et le client à qui adresser un reçu.**

Points structurants découverts en lisant la base de code :

1. **Aucune notion de « reçu » n'existe encore.** Ni domaine, ni endpoint, ni écran. Le client ne
   peut aujourd'hui obtenir **aucune** preuve de son paiement depuis le produit.
2. **La table `notifications` existe déjà** (`adapters/outbound/persistence/models.py::Notification`,
   migration `0001`) : colonnes `user_id`, `salon_id`, `appointment_id`, `type`, `channel`, `title`,
   `message`, `status` (défaut `PENDING`), `sent_at`, `created_at`, avec `CHECK` sur `type`/`channel`/
   `status`. **Mais l'enum `NotificationType` (`domain/enums.py`) ne contient que
   `CONFIRMATION`/`REMINDER`/`CANCELLATION` — pas de valeur `RECEIPT`.** Y écrire une ligne « reçu »
   imposerait donc d'**élargir l'enum + migrer la contrainte `CHECK`**.
3. **L'acheminement réel des notifications (FCM push + SMS via file Redis) est différé en M5**
   (Épic 7, ADR-0006). Le seul adapter de notification livré est un **stub no-op** (`OtpSender` /
   `StubOtpSender`, `adapters/outbound/notifications/`), qui **ne journalise jamais** destinataire ni
   contenu. **Aucun worker de remise n'existe** : rien ne peut être « poussé » à un appareil
   aujourd'hui.

### Le gap que #38 comble

Le critère est **« généré/envoyé »** (généré **ou** envoyé — alternatives). Comme la **remise**
(push/SMS) dépend d'une infra **non encore construite** (M5), l'interprétation MVP fidèle et
livrable est :

> **Générer un reçu numérique récupérable par le client** — une projection en lecture seule dérivée
> du paiement déjà persisté (source de vérité `payments` + prestations liées + identité du salon),
> exposée par un **endpoint d'appartenance** au client authentifié (patron #30 « Mon historique »).

Le reçu est ainsi **« généré » et disponible dès l'enregistrement du paiement**, sans inventer de
canal de remise non implémenté. La **remise proactive** (push/SMS/e-mail) reste un travail de M5
(Épic 7) ; #38 peut, **en option et à confirmer**, poser le *point d'accroche* de cette remise sans
en implémenter l'acheminement (voir *Risks & Open Questions* §1).

## Goals

- **Générer un reçu numérique par paiement, récupérable par le client.** Exposer une lecture
  d'**appartenance** renvoyant, pour le **client authentifié**, le(s) reçu(s) de ses paiements —
  filtre `payments.client_id = principal.id` **imposé serveur** (jamais soumis par le client),
  **sans portée salon** (le client paie potentiellement dans plusieurs salons). Patron identique à
  `GET /appointments/history` (#30).
- **Contenu du reçu = projection en lecture seule, dérivée de sources déjà persistées.** Aucune
  nouvelle écriture, aucune donnée recalculée « à la main » côté client :
  - **montant payé** = `payment.amount` (source de vérité, `NUMERIC(12,2)`, jamais de flottant) ;
  - **devise, mode de paiement, statut, référence, horodatage** = champs du `payment` ;
  - **identité du salon** = `salons.name` (+ éventuellement localisation publique) résolue depuis
    `payment.salon_id` — donnée **non sensible**, déjà exposée par le catalogue public (#18/#19) ;
  - **lignes de prestation** = pour un paiement lié à un **RDV**, les `appointment_services`
    (nom de prestation + `price_at_booking` **figé**) ; pour un paiement lié à une **prestation
    seule**, la prestation (`services.name` + `Service.price`) ;
  - **numéro de reçu** = identifiant stable du reçu (voir *Open Questions* §3 : `payment.id`
    canonique, éventuel libellé cosmétique `REC-…` dérivé).
- **Nouvelle permission de lecture `PAYMENT_READ_OWN`, détenue par le seul `CLIENT`.** Ajoutée à la
  matrice §4.1 (`ROLE_PERMISSIONS`) **sans élargir** aucun autre droit. Ni `MANAGER`, ni
  `HAIRDRESSER`, ni `ADMIN` ne reçoivent ce droit (le gérant lit déjà les transactions via #35 avec
  `CASH_JOURNAL_READ`).
- **Isolation & non-oracle (§11.2/§11.3).** Un client ne voit **que ses** reçus. Un `payment_id` d'un
  autre client (ou inexistant) est **indiscernable** → `404` neutre (aucun oracle d'existence). Un
  paiement **sans `client_id`** (encaissement au comptoir sans client rattaché) n'appartient à
  **aucun** client : il n'apparaît dans le reçu d'aucun client.
- **Aucun secret ni PII tierce dans le reçu, les logs ou les messages.** Le reçu ne contient **que**
  des données que le client possède déjà (son propre paiement, l'identité **publique** du salon,
  les prestations qu'il a réglées). Aucun `recorded_by`, aucune donnée de gestion, aucun autre client.
- **Écran client mobile « Reçu » (recommandé, sécable).** Accessible depuis « Mon historique »
  (#30) / un RDV terminé, consommant le nouvel endpoint, rendant le reçu lisible et
  **partageable/copiable**. Peut être livré séparément si l'orchestrateur préfère un premier jet
  backend-only (voir *Non-Goals* et *Open Questions* §5).
- **Couverture de tests.** Domaine (projection reçu), cas d'usage (appartenance forcée, RDV vs
  prestation seule, paiement sans client), API (`200`/`401`/`403`/`404`), matrice de permissions
  (`PAYMENT_READ_OWN` = client uniquement), e2e PostgreSQL (paiement d'un RDV → reçu récupérable par
  le client ; jamais par un tiers).

## Non-Goals

- **Construire l'infra de remise (push FCM / SMS / e-mail).** L'acheminement proactif d'un reçu
  « envoyé » dépend du worker de notifications (file Redis, ADR-0006) **livré en M5** (Épic 7). #38
  **génère** un reçu **récupérable** ; il n'implémente **aucun** envoi réel. Le stub no-op existant
  n'est pas remplacé.
- **Élargir l'enum `NotificationType` (`RECEIPT`) et écrire une ligne `notifications`** — sauf
  décision explicite (voir *Open Questions* §1). L'approche recommandée **n'écrit rien** ; la variante
  « enqueue d'une notification » est **optionnelle** et implique une **migration de contrainte
  `CHECK`** + un couplage au chemin d'écriture du paiement, ce qui dépasse un effort **S** / priorité
  **Could**.
- **Génération de PDF / document imprimable.** Le reçu MVP est une **projection structurée (JSON)**
  rendue par le client. La génération d'un PDF téléchargeable (police, mise en page, stockage S3) est
  une évolution ultérieure, hors périmètre (voir *Open Questions* §4).
- **Modifier la tranche d'enregistrement (#33/#34).** `RecordPayment`, la ligne `PAYMENT`, l'audit
  `PAYMENT_RECORDED` et l'atomicité restent **intacts** : #38 est une **lecture** additive, il ne
  touche pas le chemin d'écriture (sauf variante optionnelle §1, à ne pas retenir par défaut).
- **Reçu côté gérant / réimpression comptoir.** Le gérant dispose déjà de l'historique filtrable
  (#35) et du journal (#34). Un « ticket » remis à un client de passage (sans compte) est hors
  périmètre (voir *Open Questions* §6).
- **Exposer le montant net d'une correction (#34).** Le reçu reflète le **paiement tel
  qu'enregistré** (`amount` brut + `status`). La logique net/ajustement du journal reste côté gérant
  (voir *Open Questions* §7).
- **Nouvelle table / colonne de paiement.** Le reçu est **dérivé** de `payments` +
  `appointment_services`/`services` + `salons` (toutes existantes). Aucune migration côté paiement.
- **Modifier la matrice de permissions au-delà de l'ajout ciblé.** Seule `PAYMENT_READ_OWN` (CLIENT)
  est ajoutée ; `PAYMENT_RECORD`/`CASH_JOURNAL_READ` restent au `MANAGER`.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Notifications | FCM + SMS via file Redis, **différé M5** ; stub no-op au MVP | [0006](../docs/adr/0006-notifications-fcm-sms.md) |
| Mobile client | Flutter (Android prioritaire) | [0001](../docs/adr/0001-app-mobile-flutter.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0029** (supervision agrégée). Aucun ADR n'existe pour le
reçu ; l'ajout d'une permission et d'un endpoint client d'appartenance justifie un **court ADR**
« Reçu numérique — projection en lecture, remise différée M5 » (voir *Documentation Updates*).

### Patrons à réutiliser tels quels

- **Lecture d'appartenance client sans portée salon** — `GET /appointments/history` (#30,
  `adapters/inbound/appointments.py::list_my_appointment_history`) : garde
  `require_permission(APPOINTMENT_READ_OWN)`, filtre `client_id = principal.id` **imposé serveur**,
  aucun statut/paramètre privilégié soumis, `401`/`403` génériques, écran **vide ≠ erreur**. **Modèle
  direct** pour `GET /me/receipts`.
- **Projection dérivée de montants figés** — #29/#30/#31 agrègent `price_at_booking` /
  `Service.price` en lecture seule via `AppointmentRepository`/`ServiceRepository`, **sans nouvel
  accès à un champ privilégié**. Même approche pour composer les lignes du reçu.
- **Historique filtrable des transactions** — #35 (`application/transactions.py::ListTransactions`,
  `SqlPaymentRepository.list_in_salon`) montre comment renvoyer une **projection** (paiement +
  `client_name` résolu) à partir de `payments` avec jointure ; #38 fait l'analogue **côté client**
  (paiement + salon + lignes de prestation), filtré par `client_id`.
- **Résolution d'un nom non sensible** — `client_name`/`performed_by_name` (#34/#35) résolus
  `id → users.full_name` (colonne non sensible **uniquement**, §11.3) ; ici on résout
  `salon_id → salons.name`.
- **Écriture + lecture dans la même Session** — `get_session` mis en cache par requête ; dépôts
  partageant la Session (patron #17/#20/#28/#33). Le reçu étant **en lecture seule**, aucun commit.
- **Tests** : fakes en mémoire (`tests/conftest.py`), API via `TestClient` +
  `app.dependency_overrides`, e2e adossés à un vrai PostgreSQL (sautés si `DATABASE_URL` absent),
  matrice de permissions figée (`tests/test_permissions*.py`), garde deny-by-default
  (`tests/test_security_guards.py::unprotected_routes`).

### Schéma déjà en place (source de vérité : `models.py`, migration `0001`)

- `payments` : `amount NUMERIC(12,2)`, `currency`, `payment_method`, `status`, `recorded_by`
  **NOT NULL**, `appointment_id`/`service_id`/`client_id` **nullable**, `reference` nullable,
  `created_at` (serveur, timezone-aware), `UNIQUE(salon_id, id)`.
- `appointment_services.price_at_booking NUMERIC(12,2)` — **prix figé** (lignes du reçu d'un RDV).
- `services.name` / `services.price` — nom + prix courant (ligne du reçu d'une prestation seule).
- `salons.name` — identité **publique** du salon (déjà exposée par le catalogue #18/#19).
- `notifications` (existe, migration `0001`) — **non utilisée** par l'approche recommandée ;
  pertinente seulement pour la **variante optionnelle** (voir *Open Questions* §1), qui exigerait
  d'ajouter `RECEIPT` à `NotificationType` + migrer le `CHECK`.

### Contraintes transverses documentées

- **PRD §5.3** : après paiement, transaction au journal ; le PRD mentionne le reçu comme sortie
  côté client. **§8.4** : notifications (canaux, remise). **§11.2** : un client ne voit que **ses**
  données. **§11.3** : non-fuite PII, collecte minimale, pas de log de PII. **§12.1** : réponse API
  < 3 s.
- **ADR-0006** : ne jamais journaliser destinataire ni contenu d'un message ; clés/identifiants
  hors dépôt ; remise asynchrone M5.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**. **Test gate** :
  `scripts/test-gate.sh` (pytest + npm test + flutter test).

## Proposed Implementation

Approche recommandée : **reçu = projection en lecture seule, endpoint d'appartenance client, aucune
écriture, aucune migration.**

### (A) Backend — domaine : projection `Receipt`

- **`domain/receipt.py`** (nouveau) : dataclass `frozen` **pure** `Receipt` (et `ReceiptLine`) :
  - `Receipt` : `receipt_number: str` (voir §3 des questions), `payment_id: uuid.UUID`,
    `salon_id: uuid.UUID`, `salon_name: str`, `amount: Decimal`, `currency: str`,
    `payment_method: str`, `status: str`, `reference: str | None`, `paid_at: datetime`,
    `appointment_id: uuid.UUID | None`, `lines: tuple[ReceiptLine, ...]` ;
  - `ReceiptLine` : `service_name: str`, `amount: Decimal`.
  - Éventuel helper pur `format_receipt_number(payment_id) -> str` (cosmétique, déterministe, **sans
    I/O**) si l'on veut un libellé `REC-…` — sinon `receipt_number = str(payment_id)`.
- Aucun `raise` métier ici : la projection est un assemblage de données déjà validées.

### (B) Backend — port de lecture

- **`application/ports/payment_repository.py`** (étendre) ou **nouveau port
  `receipt_repository.py`** : ajouter deux lectures **filtrées par `client_id`** renvoyant des
  projections `Receipt` (jointures `payments` × `appointment_services`/`services` × `salons`) :
  - `list_receipts_for_client(client_id, *, limit, offset) -> tuple[list[Receipt], int]` — reçus du
    client, **du plus récent au plus ancien**, paginés (bornes `limit`/`offset` comme #35) ;
  - `get_receipt_for_client(client_id, payment_id) -> Receipt | None` — un reçu précis, `None` si le
    paiement n'existe pas **ou** n'appartient pas au client (non-oracle).
  - *Recommandation* : un **port dédié `ReceiptRepository`** (lecture) garde `PaymentRepository`
    focalisé sur l'écriture/l'historique gérant ; à trancher selon la cohérence du dépôt (les deux
    sont acceptables — voir *Open Questions* §2).

### (C) Backend — cas d'usage

- **`application/receipts.py`** (nouveau) : `ListMyReceipts` / `GetMyReceipt` — n'orchestrent que le
  port de lecture, **imposent `client_id = actor_user_id`** (jamais soumis), ne font **aucune**
  écriture ni audit (lecture pure, comme #29/#30/#31). `GetMyReceipt` renvoie la projection ou lève
  une absence neutre (traduite `404` par l'adapter) via `None`.

### (D) Backend — adapter entrant (HTTP)

- **`adapters/inbound/receipts.py`** (nouveau router, ou routes ajoutées à un router client existant) :
  - `GET /me/receipts` — garde `require_permission(Permission.PAYMENT_READ_OWN)`, **pas** de
    `require_salon_scope` (appartenance) ; renvoie une page `ReceiptPageResponse` (items + total +
    bornes), du plus récent au plus ancien.
  - `GET /me/receipts/{payment_id}` — même garde ; `404` neutre si non trouvé/hors appartenance.
  - Schémas Pydantic `ReceiptResponse` / `ReceiptLineResponse` / `ReceiptPageResponse`
    (documentation OpenAPI incluse, montants en **chaîne décimale**).
  - **Aucun** verbe destructif ; **aucun** chemin ajouté à `PUBLIC_ROUTE_PATHS` (un reçu financier
    n'est jamais public).
  - Providers de dépendances (`get_receipt_repository`) adossés à `get_session`, surchargables en
    test.
- **Câblage** : enregistrer le router dans `main.py` (là où les autres routers sont inclus).

### (E) Backend — permission `PAYMENT_READ_OWN`

- **`domain/permissions.py`** : ajouter `PAYMENT_READ_OWN = "PAYMENT_READ_OWN"` à l'enum `Permission`
  et l'insérer **uniquement** dans `ROLE_PERMISSIONS[Role.CLIENT]`. Mettre à jour les tests de
  matrice qui figent §4.1.

### (F) Mobile — écran « Reçu » (recommandé, sécable)

- Étendre la couche réseau cliente (patron #30) : ajouter `GET /me/receipts` /
  `GET /me/receipts/{id}` au client HTTP, un modèle `Receipt`, un point d'entrée depuis « Mon
  historique » (`historique-prestations-client-mobile`) ou la fiche d'un RDV terminé, et un écran
  rendant le reçu (salon, date, lignes, total, mode, référence, numéro) avec action **copier/partager**.
- **Aucun** changement backend induit par le mobile.

### (G) Variante optionnelle (à ne pas retenir par défaut) — « envoyé »

Si l'équipe veut matérialiser le mot **« envoyé »** dès #38 (voir *Open Questions* §1) : à
l'enregistrement du paiement (dans `RecordPayment`, **même unité de travail**), **enqueue** une ligne
`notifications` (`type=RECEIPT`, `channel` = `IN_APP` ou `PUSH`, `status=PENDING`, `user_id =
client_id`, `salon_id`, `appointment_id`, `title`/`message` **neutres, sans montant ni PII**) via un
**port `ReceiptNotifier`** dont l'implémentation concrète reste un **stub no-op** jusqu'au worker M5.
**Coût** : ajouter `RECEIPT` à `NotificationType` + **migration Alembic** de la contrainte `CHECK`
`notifications.type` ; toucher le chemin d'écriture atomique du paiement ; ne remettre `status=SENT`
que lorsque le worker M5 existera. **Recommandation : différer cette variante** (dépasse Could/S) et
la consigner dans l'ADR / M5.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/receipt.py` | **nouveau** — projections `Receipt`/`ReceiptLine` (pures) |
| `coiflink_api/domain/permissions.py` | **+** `PAYMENT_READ_OWN` (enum) et dans `ROLE_PERMISSIONS[CLIENT]` |
| `coiflink_api/application/ports/receipt_repository.py` | **nouveau** (ou étendre `payment_repository.py`) — `list_receipts_for_client`, `get_receipt_for_client` |
| `coiflink_api/application/receipts.py` | **nouveau** — `ListMyReceipts`, `GetMyReceipt` (appartenance forcée) |
| `coiflink_api/adapters/outbound/persistence/receipt_repository.py` | **nouveau** — `SqlReceiptRepository` (jointures `payments`×`appointment_services`/`services`×`salons`, filtre `client_id`) |
| `coiflink_api/adapters/inbound/receipts.py` | **nouveau** — `GET /me/receipts`, `GET /me/receipts/{payment_id}`, schémas, providers |
| `coiflink_api/main.py` | inclure le nouveau router |
| `backend/README.md` | section « Reçu numérique » : endpoints, permission, non-remise (M5) |

### Backend — tests

| Fichier | Contenu |
| --- | --- |
| `tests/test_domain_receipt.py` | **nouveau** — assemblage projection, format du numéro, montants `Decimal` |
| `tests/test_receipts_usecases.py` | **nouveau** — appartenance forcée, RDV vs prestation seule, paiement sans `client_id` invisible, pagination |
| `tests/test_receipts_api.py` | **nouveau** — `200` (liste + détail), `401`, `403` (rôle ≠ CLIENT), `404` (reçu d'un tiers/inexistant, neutre) |
| `tests/test_permissions*.py` | `PAYMENT_READ_OWN` détenue par le **seul** CLIENT ; matrice figée |
| `tests/test_security_guards.py` | `GET /me/receipts*` protégées, **absentes** de `PUBLIC_ROUTE_PATHS` |
| `tests/test_receipts_e2e.py` | **nouveau** — parcours PostgreSQL : paiement d'un RDV → reçu récupérable par le client ; jamais par un autre client (`404`) ; sans jeton `401` |
| `tests/conftest.py` | fake `ReceiptRepository` (ou extension du fake paiement) |

### Backend — à lire (sans modifier)

`adapters/inbound/appointments.py` (`list_my_appointment_history`, patron d'appartenance),
`application/transactions.py` + `adapters/outbound/persistence/payment_repository.py` (`list_in_salon`,
patron de projection jointe), `domain/appointment.py` (`price_at_booking`), `domain/service.py`,
`adapters/outbound/persistence/models.py` (`Payment`, `AppointmentService`, `Service`, `Salon`),
`adapters/inbound/security.py`.

### Mobile (`app-mobile/`) — recommandé, sécable

Client réseau (patron #30) + modèle `Receipt` + point d'entrée depuis « Mon historique » + écran
« Reçu » (copier/partager) + tests `flutter test`. **Aucun** changement backend induit.

### Documentation (racine)

`README.md` (§6 : statut « M4 : reçu numérique de paiement client (US-5.5, #38) »), nouvel ADR
`docs/adr/00XX-recu-numerique-remise-differee.md` + index `docs/adr/README.md`.

## API / Interface Changes

**Nouveaux endpoints (lecture, appartenance client) :**

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `GET` | `/me/receipts` | `PAYMENT_READ_OWN` (client) | `200` page de reçus (plus récent d'abord) · `401` · `403` |
| `GET` | `/me/receipts/{payment_id}` | `PAYMENT_READ_OWN` (client) | `200` reçu · `401` · `403` · `404` (tiers/inexistant, neutre) |

> Chemin exact à confirmer (`/me/receipts` vs `/receipts` vs `/appointments/{id}/receipt`) — voir
> *Open Questions* §5. Le patron d'appartenance sans portée salon (`/me/…` ou `/appointments/…`)
> reste la contrainte structurante.

```jsonc
// GET /me/receipts — 200 (extrait ; montants en chaîne décimale, jamais de flottant)
{
  "items": [
    {
      "receipt_number": "…",              // stable (payment_id canonique ; libellé cosmétique optionnel)
      "payment_id": "…uuid…",
      "salon_id": "…uuid…",
      "salon_name": "Salon Élégance",     // identité publique (catalogue #18/#19)
      "amount": "5000.00",
      "currency": "XOF",
      "payment_method": "CASH",
      "status": "VALIDATED",              // ADJUSTED possible (voir Open Questions §7)
      "reference": "REC-2026-0001",       // ou null
      "paid_at": "2026-07-30T10:15:00Z",  // payment.created_at (serveur)
      "appointment_id": "…uuid… | null",
      "lines": [
        { "service_name": "Coupe homme", "amount": "3000.00" },
        { "service_name": "Barbe",       "amount": "2000.00" }
      ]
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

- **Aucune modification** des endpoints de paiement existants (#33/#34/#35) : le reçu est une
  **lecture additive**. **Aucun** changement de CLI, de variable d'environnement ni de contrat
  inter-paquet backend.
- **Interface web gérant** : **aucune** (le reçu est client). **Interface mobile** : nouvel écran
  consommant l'endpoint (recommandé, sécable).

## Data Model / Protocol Changes

**Aucune, dans l'approche recommandée.** Le reçu est **dérivé** de `payments` +
`appointment_services`/`services` + `salons`, toutes présentes depuis la migration `0001`. Aucune
table, colonne, index ni sérialisation nouvelle côté paiement. Une **permission** est ajoutée au
domaine (`PAYMENT_READ_OWN`) — c'est du code, **pas** du schéma.

> **Variante optionnelle uniquement** (non retenue par défaut, *Open Questions* §1) : matérialiser un
> reçu « envoyé » via une ligne `notifications` **exigerait** d'ajouter la valeur `RECEIPT` à
> `NotificationType` et une **migration Alembic** de la contrainte `CHECK` `notifications.type`. À
> éviter au périmètre Could/S.

## Security & Privacy Considerations

- **Appartenance stricte (§11.2), imposée serveur.** `client_id = principal.id` est **forcé** dans le
  cas d'usage (jamais lu du corps/query, jamais choisi par le client). Un client ne peut récupérer
  **que ses** reçus. Aucune portée salon : un client paie potentiellement dans plusieurs salons, mais
  ne voit jamais un paiement d'un tiers.
- **Non-oracle (§11.3).** `GET /me/receipts/{payment_id}` renvoie `404` **neutre** que le paiement
  n'existe pas **ou** appartienne à un autre client — indiscernable. `401`/`403` **génériques**.
- **Collecte minimale / pas de PII tierce.** Le reçu ne contient **que** des données que le client
  possède : son propre paiement (montant, mode, référence, horodatage), l'identité **publique** du
  salon (`salons.name`, déjà exposée sans authentification par #18/#19), et les prestations qu'il a
  réglées. **Jamais** `recorded_by` (auteur gérant), ni le nom d'un autre client, ni donnée de
  gestion.
- **Nouvelle permission fermée.** `PAYMENT_READ_OWN` est ajoutée à la **seule** entrée `CLIENT` de
  `ROLE_PERMISSIONS` ; deny-by-default (ADR-0015) reste intact ; un test de matrice le fige. Le gérant
  ne gagne **aucun** droit (il lit déjà via #35).
- **Lecture seule, aucune écriture, aucun audit.** #38 n'insère rien (patron #29/#30/#31) : ni
  `payments`, ni `cash_journal`, ni `audit_logs`, ni `notifications` (approche recommandée). La
  consultation d'un reçu n'est pas une action journalisée §11.4.
- **Non-remise assumée et documentée.** Aucun canal de remise (push/SMS/e-mail) n'est activé : rien
  n'est envoyé à un appareil ni à un opérateur tiers, donc **aucune** exposition de PII hors du
  périmètre authentifié du client. Le stub no-op existant n'est pas sollicité.
- **Non-fuite dans logs / messages.** Aucun `print`/`logger` ne reçoit montant, référence ni identité
  ; messages `4xx` **métier et neutres**. Côté mobile, jamais de jeton ni de contenu de reçu
  journalisé.
- **Décimaux exacts.** Montants sérialisés en **chaîne décimale** (`NUMERIC(12,2)`), jamais de
  flottant, cohérents avec #34/#35.

Le dépôt **documente** ces contraintes (PRD §11.2/§11.3, ADR-0006/0015) : #38 les respecte sans en
affaiblir aucune.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O, fakes de `conftest.py`)

- **`tests/test_domain_receipt.py`** (nouveau) : assemblage `Receipt`/`ReceiptLine` (RDV multi-lignes,
  prestation seule), `receipt_number` déterministe, montants `Decimal` (somme des lignes = `amount`
  quand cohérent ; le total affiché reste `payment.amount`, source de vérité).
- **`tests/test_receipts_usecases.py`** (nouveau) : `ListMyReceipts`/`GetMyReceipt` —
  - **appartenance forcée** : le cas d'usage impose `client_id = actor` ; un `client_id` soumis est
    ignoré/inexistant ;
  - **RDV** : lignes = `appointment_services` (`price_at_booking`) ; **prestation seule** : ligne =
    `services.name`/`Service.price` ;
  - **paiement sans `client_id`** : **jamais** renvoyé à un client ;
  - **reçu d'un autre client** : `GetMyReceipt` → `None` (→ `404`) ;
  - **pagination** : ordre plus récent d'abord, bornes `limit`/`offset` ;
  - **lecture seule** : aucun appel d'écriture/audit.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_receipts_api.py`** (nouveau) : `GET /me/receipts` + `/{payment_id}` —
  - `200` liste (plus récent d'abord) et `200` détail (schéma `ReceiptResponse`, montants en chaîne) ;
  - `404` **neutre** (reçu d'un tiers / inexistant) ;
  - `403` rôle ≠ CLIENT (gérant/coiffeur/admin) — message **constant** ; `401` sans jeton.
- **`tests/test_permissions*.py`** : `PAYMENT_READ_OWN` ∈ CLIENT **uniquement** ; absente des trois
  autres rôles ; matrice §4.1 figée.
- **`tests/test_security_guards.py`** : `unprotected_routes(app)` couvre `GET /me/receipts*` ;
  **aucun** chemin reçu dans `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_receipts_e2e.py`** (nouveau, patron existant : données réservées, nettoyage
  avant/après) :
  1. gérant → salon → prestation → RDV d'un **client** → **paiement** (`client_id` = ce client,
     montant = somme `price_at_booking`) → le **client** authentifié récupère son reçu via
     `GET /me/receipts` (et `/{payment_id}`), lignes + total + salon corrects ;
  2. **un autre client** authentifié → `GET /me/receipts` **vide**, `GET /me/receipts/{payment_id}`
     du paiement d'autrui → `404` (non-oracle) ;
  3. **paiement sans `client_id`** (comptoir) → n'apparaît dans aucun reçu client ;
  4. deny-by-default : sans jeton → `401` ; rôle gérant → `403`.

### Mobile (`flutter test`) — recommandé, sécable

- Client réseau : mapping `GET /me/receipts*` (succès / `401` / `403` / `404`), jeton posé, **jamais**
  journalisé.
- Widget « Reçu » : rendu des lignes + total, action copier/partager, état **vide ≠ erreur**.

### Documentation / non-régression

`scripts/test-gate.sh` (pytest + npm test — **web inchangé** — + flutter test) au vert ; `ruff check`
propre ; aucune régression sur les endpoints de paiement (#33/#34/#35).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Reçu numérique (client) » : `GET /me/receipts` /
  `GET /me/receipts/{payment_id}` (permission `PAYMENT_READ_OWN`, appartenance §11.2), contenu du reçu
  (montant, mode, référence, salon, lignes figées), **non-remise** (push/SMS différés M5, ADR-0006),
  exemples `curl` (client → `200` ; tiers → `404`).
- **`README.md`** (racine) — §6 : phrase de statut « M4 : reçu numérique de paiement client (US-5.5,
  #38) — reçu **généré** et **récupérable** par le client (`GET /me/receipts`), dérivé du paiement
  (#33) ; **remise proactive** (push/SMS) différée en M5 (Épic 7) » dans le style existant.
- **`docs/adr/`** — **nouvel ADR** « Reçu numérique — projection en lecture, remise différée M5 » :
  figer (a) le reçu comme **projection dérivée** (pas de nouvelle table), (b) l'endpoint
  d'appartenance + `PAYMENT_READ_OWN`, (c) la **non-remise** au MVP et le renvoi à M5 pour push/SMS,
  (d) la décision de **ne pas** écrire de ligne `notifications` (variante optionnelle) au périmètre
  Could/S. Mettre à jour `docs/adr/README.md`.
- **OpenAPI** — `responses`/docstrings des deux routes documentent `200`/`401`/`403`/`404` neutres.
- **`app-mobile/README.md`** (si l'écran mobile est inclus) — écran « Reçu » et point d'entrée depuis
  « Mon historique ».

## Risks and Open Questions

1. **« Généré » vs « envoyé » — périmètre de la remise.** *Recommandation : livrer la **génération +
   récupération** (endpoint d'appartenance) ; la **remise proactive** (push/SMS/e-mail) est M5
   (Épic 7, ADR-0006).* La variante « enqueue d'une ligne `notifications` » (mot « envoyé » littéral)
   impose d'ajouter `RECEIPT` à `NotificationType` + **migration `CHECK`** + couplage au chemin
   d'écriture atomique du paiement, et **ne peut rien pousser** tant que le worker M5 n'existe pas.
   **À trancher / consigner dans l'ADR** ; recommandation forte : différer.
2. **Port dédié `ReceiptRepository` vs extension de `PaymentRepository`.** *Recommandation : port
   dédié (lecture) pour ne pas mélanger avec l'écriture/l'historique gérant (#35).* Les deux sont
   acceptables ; aligner sur la cohérence du dépôt.
3. **Numéro de reçu.** *Recommandation : `payment.id` comme identifiant canonique* ; un libellé
   cosmétique `REC-…` **déterministe** (dérivé de `payment.id` ou de `payment.reference` si présent)
   est optionnel et **sans** nouvelle colonne. Éviter tout compteur nécessitant une écriture.
4. **Format du reçu (JSON vs PDF).** *Recommandation : JSON structuré au MVP*, rendu par le mobile. Un
   PDF téléchargeable (mise en page, stockage S3 ADR-0005) est une évolution ultérieure — hors Could/S.
5. **Chemin & découpage mobile.** *Recommandation : `/me/receipts` (appartenance) + écran mobile
   depuis « Mon historique ».* Le chemin exact (`/me/receipts` vs `/receipts` vs
   `/appointments/{id}/receipt`) et l'inclusion de l'écran mobile dans #38 (vs backend-only d'abord)
   sont à confirmer avec l'orchestrateur.
6. **Reçu pour un encaissement sans compte client (`client_id` null).** Un paiement au comptoir sans
   client rattaché n'a **aucun** destinataire de reçu numérique. *Recommandation : hors périmètre*
   (un éventuel « ticket » remis par le gérant relèverait d'une évolution côté gérant). À confirmer.
7. **Paiement corrigé (`ADJUSTED`, #34).** *Recommandation : le reçu reflète le **paiement tel
   qu'enregistré** (`amount` brut + `status`) ;* la logique net/ajustement reste côté gérant (#34).
   Faut-il afficher un avertissement « corrigé » au client ? À trancher (impact mineur).
8. **Cohérence somme des lignes = `amount`.** Pour un RDV, la somme des `price_at_booking` égale le
   `payment.amount` (garanti par la cohérence #33). Pour une prestation seule, la ligne unique =
   `Service.price` = `amount`. Le **total affiché reste `payment.amount`** (source de vérité), les
   lignes étant informatives. À documenter.
9. **ADR d'encaissement/reçu.** *Recommandation : oui* — court ADR figeant projection-en-lecture +
   non-remise M5 + refus (au MVP) de la ligne `notifications`. À confirmer.

## Implementation Checklist

1. **Vérifier l'état livré** : relire `adapters/inbound/payments.py` (#33/#34/#35),
   `adapters/inbound/appointments.py::list_my_appointment_history` (#30, patron d'appartenance),
   `domain/permissions.py` (matrice §4.1), `models.py` (`Payment`/`AppointmentService`/`Service`/
   `Salon`/`Notification`), `domain/enums.py` (`NotificationType` **sans** `RECEIPT`). **Trancher** les
   questions ouvertes 1–9 ; consigner dans un **ADR**.
2. **Domaine** : créer `domain/receipt.py` (`Receipt`/`ReceiptLine` purs, helper `receipt_number`) ;
   ajouter `PAYMENT_READ_OWN` à `domain/permissions.py` (enum + `ROLE_PERMISSIONS[CLIENT]`) ; écrire
   `tests/test_domain_receipt.py` et mettre à jour les tests de matrice.
3. **Port de lecture** : `application/ports/receipt_repository.py` (ou extension) —
   `list_receipts_for_client`, `get_receipt_for_client` (filtre `client_id`, projections `Receipt`).
4. **Cas d'usage** : `application/receipts.py` (`ListMyReceipts`/`GetMyReceipt`, `client_id = actor`
   forcé, lecture seule) ; fake `ReceiptRepository` dans `tests/conftest.py` ;
   `tests/test_receipts_usecases.py` (appartenance, RDV/prestation, sans `client_id`, pagination).
5. **Persistance** : `adapters/outbound/persistence/receipt_repository.py` (`SqlReceiptRepository`,
   jointures + filtre `client_id`, tri plus récent d'abord, pagination).
6. **Adapter entrant** : `adapters/inbound/receipts.py` (`GET /me/receipts`,
   `GET /me/receipts/{payment_id}`, schémas Pydantic, providers, `404` neutre) ; inclure le router
   dans `main.py` ; `tests/test_receipts_api.py` et réaffirmer `tests/test_security_guards.py`.
7. **e2e** : `tests/test_receipts_e2e.py` (client récupère son reçu ; tiers → `404` ; sans `client_id`
   invisible ; `401`/`403`). Exécuter `pytest` (+ `DATABASE_URL`) et `ruff check`.
8. **Mobile (recommandé, sécable)** : client réseau `GET /me/receipts*`, modèle `Receipt`, point
   d'entrée depuis « Mon historique », écran « Reçu » (copier/partager), tests `flutter test`.
9. **Documentation** : section `backend/README.md` ; phrase de statut `README.md` racine ; ADR + index ;
   `app-mobile/README.md` si l'écran est inclus.
10. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test **web inchangé** +
    flutter test), `ruff check` ; relire la PR pour garantir qu'**aucun** montant, référence, jeton ni
    PII tierce n'apparaît dans les logs ou les messages, qu'**aucune** route destructive n'est ajoutée,
    qu'**aucun** reçu n'est exposé à un rôle autre que le **client propriétaire**, que **rien n'est
    réellement « envoyé »** (non-remise assumée, M5), et qu'**aucune signature IA** n'a été introduite.
