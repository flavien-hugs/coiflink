# Note client privée (gérant) (US-4.5)

> Spécification de planification pour l'issue GitHub **#32 — US-4.5 : Note client privée**
> (`feature` · **Could** · Effort **S** · PRD §6 Épic 4 / §7.2 « Clients » / §11.3). **Dépend de #28**
> (création d'une fiche client, qui a introduit la colonne `notes` et la tranche
> `/salons/{salon_id}/customers`). **Cette spec ne produit pas de code** : elle décrit l'approche à
> implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 4, US-4.5) pose le besoin : **« en tant que gérant, je veux ajouter une note privée
sur un client (préférences, allergies, habitudes) »**. Le critère d'acceptation de l'issue #32 est :

- **Le gérant ajoute/édite une note privée non visible du client.**

La section **Clients** du dashboard gérant (PRD §7.2) liste explicitement les « notes internes » parmi
ses fonctions. La fiche client livrée par **#28** porte **déjà** un champ `notes` : il est **saisi à la
création** (`POST /salons/{salon_id}/customers`), stocké dans `customer_profiles.notes`, affiché sur la
liste (`/gerant/clients`) et la page de détail (`/gerant/clients/{id}`), et **jamais** exposé au client
ni à l'application mobile. Ce que #28 a explicitement laissé hors périmètre — en le renvoyant
nommément à **US-4.5 / #32** (cf. `specs/creation-fiche-client-gerant.md` § *Non-Goals* et
[ADR-0026](../docs/adr/0026-fiche-client-portee-salon.md) §10) — c'est l'**édition** de cette note
après création :

- **Aucune route d'écriture ne modifie une fiche existante.** La tranche `customers` (#28) n'expose que
  `POST` (création) et des `GET` (lecture liste/fiche, plus historique #29 et stats #31). Il n'existe
  **ni `PUT`, ni `PATCH`, ni `DELETE`** : une note saisie à la création est **figée**. Le seul moyen de
  corriger une note aujourd'hui serait de recréer une fiche — impossible (l'unicité `(salon_id, phone)`
  la refuse) et destructeur (l'historique #29 est rattaché à la fiche).
- **L'UI de détail affiche la note en lecture seule.** `app/(gerant)/gerant/clients/[customerId]/page.tsx`
  rend `customer.notes` dans un `<p>` statique (`CustomerHeader`) : aucun champ éditable, aucun bouton.

Le gap que #32 comble : **une route d'édition ciblée de la note privée** (backend) et **un éditeur de
note** sur la page de détail gérant (web), en **réutilisant** l'infrastructure de #28 (colonne `notes`,
validation `normalize_notes`, permission `CUSTOMER_MANAGE`, portée salon, journal d'audit) — **sans
migration** ni élargissement de droits.

État actuel du dépôt (après #28 → #31), vérifié pour cette spec :

- **Backend** : `domain/customer.py::normalize_notes` (trim, vide → `None`, ≤ `NOTES_MAX_LENGTH = 2000`)
  existe et est testé ; `SqlCustomerRepository` implémente `create`/`find_by_id`/`list_for_salon`/
  `count_for_salon`/`phone_exists`/`list_visits` mais **aucun `update`** ; `application/customers.py`
  expose `CreateCustomer`/`ListSalonCustomers`/`GetCustomer`/`GetCustomerVisitHistory`/
  `GetCustomerServiceStats` mais **aucune mutation d'une fiche** ; `adapters/inbound/customers.py`
  câble `POST` + `GET` sous `/salons/{salon_id}/customers`. Le patron d'écriture-avec-diff-neutre
  existe déjà ailleurs (`UpdateSalon` → `SALON_UPDATED`, `application/salons.py:217` ; `UpdateService`
  → `SERVICE_UPDATED`, `application/services.py`).
- **Web** : `src/domain/customer/customer.ts` (validation + types), `src/application/ports/
  customer-gateway.ts` + `src/adapters/api/http-customer-gateway.ts` (`list`/`create`/`get`/`history`/
  `stats`, **pas** d'`update`), BFF `app/api/salons/[id]/customers/route.ts` (`GET`/`POST` seulement —
  il **n'existe pas** de fichier `app/api/salons/[id]/customers/[customerId]/route.ts`), page de détail
  en lecture seule.
- **Mobile** : la note **n'apparaît nulle part** — l'application cliente n'a aucun accès aux fiches
  clients. Cet invariant (« non visible du client ») est acquis et **ne doit pas** être affaibli.
- **Schéma** : `customer_profiles.notes` est `TEXT NULL` (migration `0001`). **Aucune migration n'est
  nécessaire** pour #32.

## Goals

- **Éditer la note privée d'une fiche existante.** Nouvel endpoint **`PUT /salons/{salon_id}/customers/
  {customer_id}/notes`** remplaçant la note : corps `{"notes": string | null}`, réponse `200` avec la
  fiche à jour. Une chaîne vide/`null` **efface** la note (`notes = NULL`) — c'est ainsi que « éditer »
  couvre aussi « retirer ».
- **Portée salon imposée par le chemin (§11.2), défense en profondeur.** La route est imbriquée sous
  `/salons/{salon_id}/…` (hérite de `require_salon_scope`) **et** le dépôt refiltre `(salon_id,
  customer_id)` en SQL. Une fiche d'un autre salon est **indiscernable d'une fiche inexistante** :
  `403` générique hors périmètre, `404` **après** validation de portée. Aucun oracle d'existence.
- **Aucune autre donnée éditable par cette route.** Seule `notes` est modifiable ; `full_name`,
  `phone`, `gender`, `user_id`, `salon_id`, `total_visits`, `last_visit_at`, `id` sont **inchangés** et
  tout champ privilégié présent au corps est **ignoré** (`extra="ignore"`). L'édition du nom, du
  téléphone ou du genre reste **hors périmètre** (aucune US ne la demande à ce stade).
- **Réutilise `CUSTOMER_MANAGE` sans l'élargir.** La route déclare `require_permission(CUSTOMER_MANAGE)`
  + `require_salon_scope`, comme les routes #28. `ROLE_PERMISSIONS` (§4.1) **n'est pas modifiée** : seul
  le `MANAGER` édite les notes (ni `CLIENT`, ni `HAIRDRESSER`, ni `ADMIN`).
- **Édition journalisée (§11.3/§11.4), sans PII.** Chaque édition enregistre une `AuditEntry` **neutre**
  (`CUSTOMER_NOTE_UPDATED`, entité `customer`, `metadata = {}`) dans la **même unité de travail** que
  l'écriture — la note peut contenir des données de santé (allergies) : sa modification est un « accès
  sensible » §11.3. Ni le contenu de la note, ni l'ancienne valeur n'entrent au journal.
- **Note jamais exposée au client (invariant renforcé).** Aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` ;
  la note reste hors du catalogue public (#18/#19), de la disponibilité (#21) et de **toutes** les
  routes de l'application mobile. L'UI web réaffirme « visible uniquement par le salon ».
- **Éditeur de note sur la page de détail gérant.** `/gerant/clients/{customerId}` remplace l'affichage
  statique de la note par un panneau éditable (saisir / modifier / effacer, `router.refresh()` après
  succès). Le jeton d'accès reste lu **côté serveur** depuis le cookie `httpOnly` (invariant #14).
- **Couverture de tests.** Backend : cas d'usage (portée, audit sans PII, effacement, `404`), API
  (`200`/`401`/`403`/`404`/`422`), e2e PostgreSQL (persistance, isolation inter-salons, traçabilité sans
  PII). Web : gateway HTTP, Route Handler BFF, éditeur de note, page de détail.

## Non-Goals

- **Édition du nom, du téléphone ou du genre d'une fiche.** #32 n'édite **que** la note. Une édition
  générale de fiche (et la revalidation d'unicité `(salon_id, phone)` associée) reste une évolution
  ultérieure, hors de cette issue `Could`.
- **Suppression d'une fiche client (`DELETE`).** Hors périmètre ; l'effacement / droit à l'oubli relève
  du durcissement M6 (#52), comme documenté par ADR-0026.
- **Historique de révisions de la note / versioning.** L'audit trace **qu'**une édition a eu lieu (qui,
  quand, quelle fiche) mais **pas** le contenu successif. Aucun journal des valeurs de note (ce serait
  stocker de la PII/santé dans `audit_logs`, contraire à §11.3/§11.4).
- **Chiffrement applicatif au repos des notes.** Décision **déjà différée** par ADR-0026 (§11.3 « si
  nécessaire ») : le chiffrement disque/sauvegardes plateforme (ADR-0011) reste la couverture au MVP,
  l'accès étant restreint par `CUSTOMER_MANAGE`. #32 **ne change pas** cet arbitrage (à reprendre en M6,
  #52).
- **Exposition de la note à l'application mobile / au client.** Explicitement **interdit** par le critère
  d'acceptation (« non visible du client ») : aucune route mobile ni publique n'est ajoutée ou modifiée.
- **Recherche / filtre serveur sur le contenu des notes.** Le filtre de la liste `/gerant/clients` reste
  **client-side** sur la page déjà chargée (comportement #28) ; aucune recherche plein texte serveur
  n'est ajoutée (elle toucherait à la PII et mérite sa propre revue, cf. ADR-0026 §9).
- **Modification de la matrice de permissions §4.1.** `CUSTOMER_MANAGE` existe déjà : #32 la réutilise
  sur une route de plus, sans l'élargir.
- **Nouvelle migration / changement de schéma.** La colonne `customer_profiles.notes` existe déjà
  (`TEXT NULL`, `0001`). #32 **n'ajoute aucune migration**.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Journal d'audit | Table `audit_logs` + port `AuditLog`, entrées **neutres** | [0019](../docs/adr/0019-journalisation-audit-et-prestations.md) |
| Fiche client | Ressource salon-scopée, note interne non exposée, chiffrement différé | [0026](../docs/adr/0026-fiche-client-portee-salon.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0026** (fiche client). #29/#31 n'ont **pas** produit d'ADR :
étant des lectures dérivées de #28, ils ont documenté leurs choix dans les README de paquet. #32 étant
purement additif (une route d'écriture ciblée, sans schéma), **aucun ADR n'est requis** — voir *Risks
and Open Questions* §5.

### Backend — patrons à réutiliser tels quels

- **Écriture-avec-diff-neutre (`UpdateSalon`, `application/salons.py:217`)** — le gabarit le plus proche :
  validation domaine → `find_by_id` (`404` si absent, portée déjà validée par la garde HTTP) →
  `repository.update(...)` → `audit_log.record(SALON_UPDATED, metadata={"changed": [...]})`. `UpdateService`
  (`application/services.py`) suit le même schéma. #32 en est une variante à **un seul champ** (`notes`).
- **Fiche client (#28)** : `domain/customer.py::normalize_notes` (**à réutiliser tel quel**),
  `application/customers.py` (`GetCustomer` pour résoudre la fiche dans le salon),
  `application/ports/customer_repository.py` (port `Protocol`), `adapters/outbound/persistence/
  customer_repository.py::SqlCustomerRepository` (filtre `(salon_id, id)`, `flush()` **sans** `commit()`),
  `adapters/inbound/customers.py` (router `prefix="/salons"`, gardes, mapping d'erreurs `422`/`404`).
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.X)` +
  `require_salon_scope` ; `403` **générique et constant** (`« Accès refusé. »`) pour rôle insuffisant
  **comme** pour accès inter-salons ; l'invariant deny-by-default est vérifié mécaniquement par
  `unprotected_routes(app)` (`test_security_guards.py`) — **une route ajoutée sans garde fait échouer les
  tests**.
- **Journalisation §11.4** : port `application/ports/audit_log.py`, entrée `domain/audit.py::AuditEntry`
  (`action`, `actor_user_id`, `salon_id`, `entity_type`, `entity_id`, `metadata`), adapter `SqlAuditLog` ;
  `get_audit_log` et le dépôt métier partagent la **même** `Session` (FastAPI met `get_session` en cache
  par requête) → commit/rollback atomique. `ENTITY_TYPE_CUSTOMER` et `AuditAction.CUSTOMER_CREATED` sont
  déjà déclarés (`domain/audit.py`).
- **Écritures `flush()` sans `commit()`** : le commit est piloté par `get_session` (cf.
  `SqlServiceRepository.update`), condition de l'atomicité mutation + audit.
- **Tests** : fakes en mémoire dans `tests/conftest.py` (`FakeCustomerRepository`, `FakeAuditLog`,
  `FakeSalonScopeRepository`…) ; tests d'API via `TestClient` + `app.dependency_overrides` ; **tests
  e2e** adossés à un vrai PostgreSQL, sautés si `DATABASE_URL` est absent, avec plage de téléphones
  réservée et nettoyage avant/après.

### Web gérant — patrons à réutiliser (#28)

- `app/(gerant)/gerant/clients/[customerId]/page.tsx` = **Server Component** : lit le cookie
  (`createCookieSessionStore().read()`), appelle les gateways HTTP côté serveur (`get`/`history`/`stats`),
  rend l'UI (dont `CustomerHeader` qui affiche `customer.notes` en lecture seule — **à rendre éditable**).
- `src/adapters/api/http-customer-gateway.ts` : `fetch` vers le backend avec `Authorization: Bearer`,
  résultat en **union discriminée** (`{ ok:true, … } | { ok:false, reason:"forbidden"|"unauthenticated"|
  "invalid"|"not-found"|"unavailable" }`) — jamais d'exception qui remonterait un détail réseau à l'UI.
- BFF : `app/api/salons/[id]/customers/route.ts` (`GET`/`POST`) — **modèle** pour un nouveau
  `app/api/salons/[id]/customers/[customerId]/route.ts` (`PATCH`/`PUT` note) ; revalidation du corps
  (parité domaine), lecture du jeton du cookie `httpOnly`, messages d'erreur **neutres** en français.
- Formulaires client-side + `router.refresh()` après mutation (cf. `customer-form.tsx`).
- `src/domain/customer/customer.ts` : `NOTES_MAX_LENGTH`, `validateCustomer` — la borne des notes y est
  déjà ; une validation dédiée `validateNote` (ou réutilisation de la borne) suffit.

### Contraintes transverses documentées

- **PRD §11.2** : « un gérant ne peut voir que les données de son salon ».
- **PRD §11.3** : collecte **minimale**, journalisation des accès sensibles, chiffrement au repos « si
  nécessaire », note interne non exposée au client (ADR-0026 §10).
- **PRD §11.4** : journalisation des actions importantes (entrées **neutres**, ADR-0019).
- **PRD §12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA** (code, commits, PR).
- **Test gate** : `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI applicative `ci.yml`
  (ruff, pytest, round-trip Alembic contre PostgreSQL 16, build/lint/test web).

## Proposed Implementation

### (A) Backend — domaine

Aucune nouvelle entité. `domain/customer.py::normalize_notes` couvre déjà la validation (trim, vide →
`None`, ≤ `NOTES_MAX_LENGTH`, message neutre). **Réutiliser tel quel.**

**`domain/audit.py`** : ajouter `AuditAction.CUSTOMER_NOTE_UPDATED = "CUSTOMER_NOTE_UPDATED"`
(commentaire : §11.3 « accès sensibles » — la note peut contenir des données de santé). `ENTITY_TYPE_
CUSTOMER` existe déjà — **le réutiliser**.

> **`domain/errors.py`** : `CustomerNotFound` et `InvalidCustomerNotes` existent déjà (#28). **Aucune
> nouvelle erreur** n'est nécessaire.

### (B) Backend — port de persistance

**`application/ports/customer_repository.py`** — ajouter une méthode au `Protocol` :

```python
def update_notes(
    self, salon_id: uuid.UUID, customer_id: uuid.UUID, notes: str | None
) -> Customer: ...
```

Docstring : filtre `(salon_id, customer_id)` (isolation §11.2) ; lève `CustomerNotFound` si la fiche est
absente du salon (jamais un oracle d'existence). `notes = None` **efface** la note.

### (C) Backend — adapter de persistance

**`adapters/outbound/persistence/customer_repository.py::SqlCustomerRepository`** — implémenter
`update_notes` (miroir de `SqlServiceRepository.update`) :

```python
def update_notes(self, salon_id, customer_id, notes):
    stmt = select(models.CustomerProfile).where(
        models.CustomerProfile.salon_id == salon_id,
        models.CustomerProfile.id == customer_id,
    )
    row = self._session.scalar(stmt)
    if row is None:
        raise CustomerNotFound("Fiche client introuvable.")
    row.notes = notes
    self._session.flush()      # INSERT/UPDATE sans commit (atomicité avec l'audit)
    self._session.refresh(row) # recharge updated_at régénéré côté serveur
    return _to_domain(row)
```

`_get_row`/`find_by_id` existe déjà comme select filtré ; on peut factoriser une aide privée `_get_row`
comme dans `SqlServiceRepository`. Importer `CustomerNotFound` (déjà défini dans `domain/errors.py`).

### (D) Backend — cas d'usage

**`application/customers.py`** — ajouter `UpdateCustomerNote` :

```python
class UpdateCustomerNote:
    """Édite la note privée d'une fiche du salon et journalise (§11.3/§11.4)."""

    def __init__(self, repository: CustomerRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(self, salon_id, customer_id, notes, *, actor_user_id) -> Customer:
        normalized = normalize_notes(notes)                # None si vide → efface la note
        customer = self._repository.update_notes(salon_id, customer_id, normalized)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.CUSTOMER_NOTE_UPDATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_CUSTOMER,
                entity_id=customer.id,
                metadata={},   # aucune PII : ni contenu, ni ancienne valeur (§11.3/§11.4)
            )
        )
        return customer
```

- La validation (`normalize_notes`, lève `InvalidCustomerNotes`) précède **toute** écriture : une note
  hors borne ne produit ni mutation ni audit.
- `update_notes` lève `CustomerNotFound` **avant** l'audit si la fiche est hors salon/inconnue → aucune
  trace pour une cible inexistante. (Alternative : résoudre d'abord via `GetCustomer` puis
  `update_notes` ; retenir la voie la plus simple qui garantit « pas d'audit sans écriture ».)
- Ajouter `UpdateCustomerNote` à `__all__`.

### (E) Backend — adapter entrant (HTTP)

**`adapters/inbound/customers.py`** — ajouter une route au router existant (`prefix="/salons"`) :

- Schéma Pydantic `UpdateCustomerNoteRequest` :

  ```python
  class UpdateCustomerNoteRequest(BaseModel):
      model_config = ConfigDict(extra="ignore")   # ignore tout champ privilégié
      notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH,
                                examples=["Allergie au réactif X. Préfère le samedi matin."])
  ```

- Route :

  ```python
  @router.put(
      "/{salon_id}/customers/{customer_id}/notes",
      response_model=CustomerResponse,
      summary="Éditer la note privée d'une fiche client (non visible du client)",
      responses={401: {...}, 403: {...}, 404: {...}, 422: {...}},
  )
  def update_customer_note(
      salon_id, customer_id, payload: UpdateCustomerNoteRequest,
      repository=Depends(get_customer_repository),
      audit_log=Depends(get_audit_log),
      _scope=Depends(require_salon_scope),
      principal=Depends(require_permission(Permission.CUSTOMER_MANAGE)),
  ) -> CustomerResponse:
      try:
          customer = UpdateCustomerNote(repository, audit_log).execute(
              salon_id, customer_id, payload.notes, actor_user_id=principal.id
          )
      except InvalidCustomerNotes as exc:
          raise HTTPException(422, detail=str(exc)) from exc
      except CustomerNotFound as exc:
          raise HTTPException(404, detail=str(exc)) from exc
      return _customer_response(customer)
  ```

- Réutilise `_customer_response`, `CustomerResponse`, `require_salon_scope`,
  `require_permission(CUSTOMER_MANAGE)` déjà présents. **Aucun** chemin ajouté à `PUBLIC_ROUTE_PATHS`.
  `InvalidCustomerNotes` est déjà dans `_VALIDATION_ERRORS` — le mapping `422` peut passer par le
  tuple existant.

Le router `customers` est déjà `include`d dans `main.py` (#28) : **aucun câblage supplémentaire** — la
nouvelle route s'ajoute au router existant.

### (F) Web gérant — éditeur de note

1. **Port & gateway** — `src/application/ports/customer-gateway.ts` : ajouter `updateNote(salonId,
   customerId, notes: string | null): Promise<UpdateNoteResult>` (union discriminée avec `reason:
   "invalid" | "forbidden" | "unauthenticated" | "not-found" | "unavailable"`).
   `src/adapters/api/http-customer-gateway.ts` : implémenter `updateNote` (`PUT` vers
   `${customersUrl(salonId)}/${customerId}/notes`, corps `{ notes }`, mapping `200 → ok` /
   `401/403/404/422/…`), **sans jamais** journaliser le jeton ni le contenu de la note.
2. **BFF** — **nouveau** `app/api/salons/[id]/customers/[customerId]/route.ts` avec un handler `PATCH`
   (ou `PUT`) : lit le corps (`{ notes }`), revalide la borne (parité `NOTES_MAX_LENGTH`), lit le jeton
   du cookie `httpOnly`, appelle `gateway.updateNote(...)`, renvoie un corps neutre (`422` « Note
   invalide. », `403` « Action non autorisée sur ce salon. », `404` « Fiche client introuvable. »).
   Choisir la même méthode HTTP que le backend (recommandé : **`PUT`**, sémantique *replace*).
3. **UI** — `src/adapters/ui/customer-note-form.tsx` (client component) : `<textarea>` pré-rempli avec la
   note courante, boutons « Enregistrer » / « Effacer » ; poste au BFF, `router.refresh()` au succès ;
   mention « visible uniquement par le salon — jamais partagé avec le client » (comme `customer-form.tsx`).
4. **Page de détail** — `app/(gerant)/gerant/clients/[customerId]/page.tsx` : remplacer le `<p>` statique
   de `CustomerHeader` par le nouveau panneau éditable `CustomerNoteForm` (prop `salonId`, `customerId`,
   `initialNotes={customer.notes}`). Le reste (historique #29, préférées #31) est inchangé.
5. **Domaine (option)** — `src/domain/customer/customer.ts` : au besoin, extraire une aide `validateNote`
   (borne `NOTES_MAX_LENGTH`) réutilisée par le BFF et le formulaire ; sinon réutiliser la borne
   existante.

### (G) Documentation

- `backend/README.md` : compléter la section « Clients » avec la route
  `PUT /salons/{salon_id}/customers/{customer_id}/notes` (permission, portée, réponses, audit
  `CUSTOMER_NOTE_UPDATED`).
- `web-dashboard/README.md` : mentionner l'édition de la note sur `/gerant/clients/{id}` et le nouveau
  BFF `app/api/salons/[id]/customers/[customerId]`.
- `README.md` (racine) : phrase de statut §6 (M4 : édition de la note client privée, #32).
- `docs/adr/0026-fiche-client-portee-salon.md` : au besoin, une note de suivi « édition livrée par #32 »
  (l'ADR mentionne déjà que l'édition de la note privée est US-4.5/#32). Pas de nouvel ADR (voir *Open
  Questions* §5).
- **OpenAPI** : le `summary`/`responses`/docstring de la route documentent la nouvelle API (visible sur
  `/docs`), y compris le `422`.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/audit.py` | `AuditAction.CUSTOMER_NOTE_UPDATED` (réutilise `ENTITY_TYPE_CUSTOMER`) |
| `coiflink_api/application/ports/customer_repository.py` | méthode `update_notes(salon_id, customer_id, notes)` au `Protocol` |
| `coiflink_api/application/customers.py` | cas d'usage `UpdateCustomerNote` (+ `__all__`) |
| `coiflink_api/adapters/outbound/persistence/customer_repository.py` | `SqlCustomerRepository.update_notes` |
| `coiflink_api/adapters/inbound/customers.py` | schéma `UpdateCustomerNoteRequest` + route `PUT …/notes` |
| `tests/conftest.py` | `FakeCustomerRepository.update_notes` |
| `tests/test_customer_usecases.py` | cas `UpdateCustomerNote` (portée, audit sans PII, effacement, 404) |
| `tests/test_customer_api.py` | `200`/`401`/`403`/`404`/`422`, corps privilégié ignoré |
| `tests/test_customer_e2e.py` | persistance, isolation inter-salons, traçabilité sans PII |
| `tests/test_domain_audit.py` | `CUSTOMER_NOTE_UPDATED` couverte |
| `backend/README.md` | route d'édition de note dans la section « Clients » |

### Backend — à lire (sans modifier) pour rester fidèle aux patrons

`application/salons.py` (`UpdateSalon`), `application/services.py` (`UpdateService`),
`adapters/outbound/persistence/service_repository.py` (`update`/`_get_row`),
`adapters/inbound/security.py`, `domain/customer.py` (`normalize_notes`),
`adapters/inbound/customers.py` (routes #28).

### Web (`web-dashboard/`)

À créer : `app/api/salons/[id]/customers/[customerId]/route.ts` (BFF `PUT`/`PATCH` note),
`src/adapters/ui/customer-note-form.tsx`, `test/customer-note-bff.test.ts`,
`test/customer-note-form.test.tsx` (si le socle de test composant le permet).
À modifier : `src/application/ports/customer-gateway.ts` (`updateNote`),
`src/adapters/api/http-customer-gateway.ts` (`updateNote`),
`app/(gerant)/gerant/clients/[customerId]/page.tsx` (panneau éditable),
`src/domain/customer/customer.ts` (option : `validateNote`),
`test/http-customer-gateway.test.ts` (mapping `updateNote`), `web-dashboard/README.md`.

### Documentation (racine)

`README.md`, éventuellement `docs/adr/0026-fiche-client-portee-salon.md` (note de suivi).

## API / Interface Changes

**Un nouvel endpoint REST**, protégé (`CUSTOMER_MANAGE` + portée salon) ; aucune route existante n'est
modifiée ; aucun chemin n'entre dans `PUBLIC_ROUTE_PATHS`.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `PUT` | `/salons/{salon_id}/customers/{customer_id}/notes` | `CUSTOMER_MANAGE` + portée | `200` fiche à jour · `401` · `403` · `404` fiche hors salon/inconnue · `422` note trop longue |

```jsonc
// PUT /salons/{salon_id}/customers/{customer_id}/notes — corps
{
  "notes": "Allergie au réactif X. Préfère le samedi matin."  // string | null ; null/"" efface la note ; ≤ 2000 caractères
}

// 200 — réponse (identique à GET fiche : CustomerResponse)
{
  "id": "…uuid…",
  "salon_id": "…uuid…",
  "full_name": "Awa Koné",
  "phone": "+2250700000000",
  "gender": "FEMALE",
  "notes": "Allergie au réactif X. Préfère le samedi matin.",
  "last_visit_at": null,
  "total_visits": 0,
  "created_at": "2026-07-24T09:00:00Z",
  "updated_at": "2026-07-27T11:30:00Z"   // régénéré à l'édition
}
```

- Champs privilégiés du corps (`salon_id`, `id`, `user_id`, `full_name`, `phone`, `gender`,
  `total_visits`, `last_visit_at`) : **ignorés** (`extra="ignore"`). Seule `notes` est prise en compte.
- `user_id` **n'est pas exposé** (anti-oracle, ADR-0026), cohérent avec les routes #28.

**Interface web (BFF, interne à Next.js)** : `PUT` (ou `PATCH`) `/api/salons/[id]/customers/
[customerId]`. **Aucune** modification de CLI, de variable d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**Aucune.** La colonne `customer_profiles.notes` (`TEXT NULL`) existe depuis la migration `0001` et est
déjà écrite à la création (#28). #32 se contente de la **mettre à jour** — **pas de migration**, pas de
`CHECK`, pas d'index, pas de changement de sérialisation. `updated_at` est régénéré par le `onupdate`
existant du modèle ORM.

## Security & Privacy Considerations

**Ce module modifie des données personnelles potentiellement sensibles** : la note peut contenir des
informations de santé (allergies, US-4.5). C'est sa principale sensibilité et l'origine de plusieurs
garde-fous.

- **Note jamais visible du client (critère d'acceptation, invariant renforcé).** Aucun chemin ajouté à
  `PUBLIC_ROUTE_PATHS` ; la note n'apparaît ni au catalogue public (#18/#19), ni dans la disponibilité
  (#21), ni dans **aucune** route de l'application mobile (`GET /appointments/history` #30 ne renvoie
  jamais de note). L'édition ne crée qu'une route **gérant** protégée.
- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur la route (portée **chargée en
  base**, jamais déduite du corps) **et** filtre `(salon_id, customer_id)` en SQL dans `update_notes`. Un
  accès inter-salons renvoie le **`403` générique et constant** (`« Accès refusé. »`), identique à un
  rôle insuffisant : aucun oracle. Le `404` (fiche introuvable) n'est renvoyé qu'**après** validation de
  portée.
- **Permission `CUSTOMER_MANAGE` seule (§4.1).** Détenue par le seul `MANAGER` ; `ROLE_PERMISSIONS`
  **n'est pas modifiée**. Le `HAIRDRESSER` et l'`ADMIN` n'éditent pas les notes (supervision ≠
  exploitation, ADR-0015).
- **Aucune PII dans le journal d'audit (§11.4, ADR-0019).** `CUSTOMER_NOTE_UPDATED` porte `actor_user_id`
  (UUID opaque), `salon_id`, `entity_type="customer"`, `entity_id` et **`metadata = {}`** — jamais le
  contenu de la note, ni l'ancienne valeur, ni un booléen sur sa présence. Un test l'exige explicitement.
- **Aucune PII ni secret dans les logs / messages d'erreur.** Aucun `print`/`logger` ne reçoit le corps
  de requête ni le contenu de la note ; les messages `4xx` restent **métier et neutres** (« Note
  invalide. » sans reprendre le texte). Le BFF et le gateway web ne journalisent jamais le jeton, l'en-
  tête `Authorization` ni la note.
- **Validation avant écriture.** `normalize_notes` borne (`≤ 2000`) et refuse un corps non borné **avant**
  toute mutation : une note invalide ne produit ni écriture, ni entrée d'audit (budget §12.1).
- **Atomicité mutation + audit.** L'écriture (`flush()` sans `commit()`) et l'`AuditEntry` partagent la
  **même** `Session` : soit les deux sont committées, soit aucune (patron #17/#20/#28).
- **Chiffrement applicatif au repos : toujours différé.** #32 n'y touche pas — ADR-0026 (§10) le reporte
  à M6 (#52) ; l'accès reste restreint par `CUSTOMER_MANAGE` et le chiffrement plateforme (ADR-0011).
- **Jeton jamais exposé côté web (#14).** La page de détail et le Route Handler BFF lisent le cookie
  `httpOnly` **côté serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais
  journalisé.
- **Pas d'oracle d'existence de compte.** Comme #28, la route n'interroge **jamais** `users` par
  téléphone et n'expose pas `user_id` : éditer une note n'apprend rien sur l'existence d'un compte.

Le dépôt **documente** ces contraintes (PRD §11.2/§11.3/§11.4, ADR-0015/0019/0026) : #32 les respecte
sans en affaiblir aucune.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **`tests/test_customer_usecases.py`** (fakes de `conftest.py`) :
  - édition nominale : `update_notes` reçoit le `salon_id` de **portée** et la note **normalisée** ;
    `CUSTOMER_NOTE_UPDATED` enregistrée **une fois**, bon `actor_user_id`/`salon_id`/`entity_id`, et
    **`metadata == {}`** (aucune PII) ;
  - **effacement** : `notes = ""`/`None`/`"   "` → `update_notes(..., None)` (note effacée) ;
  - note **trop longue** (> 2000) → `InvalidCustomerNotes`, **aucune** écriture ni audit ;
  - fiche d'un **autre salon** / inconnue → `CustomerNotFound`, **aucun** audit ;
  - trim/normalisation cohérente avec `normalize_notes`.
- **`tests/test_domain_audit.py`** : `CUSTOMER_NOTE_UPDATED` présente et cohérente (valeur d'enum,
  entité `customer`).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_customer_api.py`** : `200` + corps attendu (note mise à jour, `updated_at` changé, **pas
  de `user_id`**) ; corps portant `full_name`/`phone`/`gender`/`salon_id`/`user_id` → **ignorés** (seule
  la note change) ; `422` note trop longue ; `404` fiche d'un autre salon ; `403` hors portée / rôle non
  `MANAGER` (message **constant**) ; `401` sans jeton ; effacement (`notes: null`) → `200` avec `notes:
  null`.
- **`tests/test_security_guards.py`** : l'invariant `unprotected_routes(app) == []` couvre
  automatiquement la nouvelle route ; vérifier qu'**aucun** chemin `customers` n'entre dans
  `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_customer_e2e.py`** (patron existant, plage de téléphones réservée, nettoyage
  avant/après) :
  1. parcours : inscription gérant → connexion → création salon → **création de fiche** → **édition de
     la note** → la consultation (`GET` fiche) renvoie la nouvelle note ; l'effacement (`notes: null`)
     laisse `notes = NULL` en base ;
  2. **isolation inter-salons** : le jeton du gérant B est refusé (`403` générique) sur la note de la
     fiche du salon de A ;
  3. **traçabilité** : une ligne `audit_logs` `CUSTOMER_NOTE_UPDATED` avec le bon acteur, et **aucune
     PII** dans `metadata` (assertion explicite : le contenu de la note **n'apparaît pas**) ;
  4. deny-by-default : sans jeton → `401`.
- **Migration** : **aucune** (pas de changement de schéma) — rien à couvrir côté Alembic.

### Web (`vitest`)

- `test/http-customer-gateway.test.ts` : mapping `updateNote` (`200 → ok`, `403 → "forbidden"`,
  `401 → "unauthenticated"`, `404 → "not-found"`, `422 → "invalid"`), en-tête `Authorization` posé,
  **jeton jamais renvoyé** dans le résultat.
- `test/customer-note-bff.test.ts` : `401` sans cookie ; `422` note trop longue ; `403`/`404` propagés
  avec message neutre ; **aucune PII ni jeton** dans les réponses d'erreur ; `notes: null` accepté
  (effacement).
- `test/customer-note-form.test.tsx` (si le socle le permet) : pré-remplissage avec la note courante,
  bouton « Effacer » vide le champ, `router.refresh()` déclenché au succès.

### Documentation / non-régression

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre ; `npm run
  lint && npm run build` (sortie standalone) inchangé ; l'application mobile (`flutter test`) reste
  **verte et inchangée** (aucune exposition de note).

## Documentation Updates

- **`backend/README.md`** — section « Clients » : ajouter la ligne
  `PUT /salons/{salon_id}/customers/{customer_id}/notes` (permission `CUSTOMER_MANAGE`, portée §11.2,
  réponses `200`/`401`/`403`/`404`/`422`, audit `CUSTOMER_NOTE_UPDATED` sans PII), avec un exemple `curl`
  et la règle « `null`/vide efface la note ».
- **`web-dashboard/README.md`** — mentionner l'édition de la note sur `/gerant/clients/{id}` et le
  nouveau BFF `app/api/salons/[id]/customers/[customerId]` (Server Component + Route Handler,
  `router.refresh()`).
- **`README.md`** (racine) — §6 : phrase de statut « M4 : édition de la note client privée (US-4.5, #32)
  — note interne éditable, jamais visible du client » dans le style des paragraphes existants.
- **`docs/adr/0026-fiche-client-portee-salon.md`** — note de suivi facultative (« édition de la note
  livrée par #32 ») ; **pas** de nouvel ADR (voir *Open Questions* §5).
- **OpenAPI** — `summary`/`responses`/docstring de la route documentent la nouvelle API (`/docs`).

## Risks and Open Questions

1. **Méthode HTTP et forme de la route.** *Recommandation : `PUT /salons/{salon_id}/customers/
   {customer_id}/notes`* — sous-ressource dédiée à sémantique *replace* (une note = un texte remplacé),
   qui signale sans ambiguïté que **seule** la note est éditable et laisse la porte ouverte à un futur
   `PATCH /customers/{id}` général (édition nom/téléphone/genre) sans collision. **Alternative** :
   `PATCH /salons/{salon_id}/customers/{customer_id}` avec `{ "notes": … }` (édition partielle
   générique). À trancher avant l'implémentation ; le backend et le BFF web doivent utiliser la **même**
   méthode.
2. **Contenu de `metadata` d'audit.** *Recommandation : `metadata = {}`* (le nom d'action
   `CUSTOMER_NOTE_UPDATED` porte déjà l'information), cohérent avec `CUSTOMER_CREATED`. **Alternative
   consistante** : `{"changed": ["notes"]}` (patron `SALON_UPDATED`). À **proscrire** absolument : tout
   indicateur du **contenu** (`{"note_present": …}`, longueur, ancienne valeur) — ce serait de la
   PII/santé au journal, contraire à §11.3/§11.4.
3. **Effacement de la note.** L'énoncé dit « ajoute/édite ». *Recommandation : `null`/chaîne vide efface
   la note* (`notes = NULL`) — « éditer » couvre naturellement « retirer une note obsolète ». Un `DELETE`
   dédié n'est pas nécessaire. **À confirmer** si l'effacement doit être interdit (peu probable).
4. **Édition sur no-op (note inchangée).** *Recommandation : accepter et journaliser quand même* (simple,
   et l'intention d'édition est significative), comme `UpdateSalon` qui journalise même si le diff est
   vide. **Alternative** : sauter l'audit si la note est identique (moins de bruit) — décision mineure, à
   trancher à l'implémentation.
5. **Un ADR est-il requis ?** #32 est **purement additif** : une route d'écriture ciblée réutilisant la
   colonne, la permission et le patron d'audit de #28, **sans migration** ni décision d'architecture
   nouvelle. *Recommandation : pas de nouvel ADR* — replier la (courte) décision dans `backend/README.md`
   et une note de suivi dans ADR-0026 (qui prévoit déjà l'édition de la note par #32). **À confirmer.**
6. **Périmètre : note seule vs édition de fiche.** L'issue `Could` ne demande **que** la note.
   *Recommandation : s'y tenir strictement* — l'édition du nom/téléphone/genre (et la revalidation
   d'unicité `(salon_id, phone)`) est un périmètre distinct, plus risqué, sans US associée. **À
   confirmer** ; si l'édition générale est souhaitée, elle mérite sa propre issue.
7. **Concurrence.** Deux éditions simultanées de la même note : dernière écriture gagnante (pas de
   verrou optimiste). Acceptable pour une note interne d'un salon (peu d'éditeurs concurrents). Pas de
   `If-Match`/version au MVP — à documenter comme suivi si besoin.
8. **Test de composant web.** Selon la maturité du socle `vitest`/testing-library du `web-dashboard`, le
   test du `customer-note-form.tsx` peut être limité ; à défaut, couvrir la logique via le BFF et le
   gateway (comme #28 l'a fait). Vérifier ce qui est déjà en place avant d'ajouter une dépendance de
   test.

## Implementation Checklist

1. **Lire** `application/salons.py` (`UpdateSalon`), `application/services.py` (`UpdateService`),
   `adapters/outbound/persistence/service_repository.py` (`update`/`_get_row`),
   `adapters/inbound/customers.py`, `domain/customer.py` (`normalize_notes`) — s'imprégner des patrons.
2. **Trancher** les questions ouvertes 1 à 6 (méthode HTTP, `metadata`, effacement, no-op, ADR,
   périmètre) et consigner la décision dans `backend/README.md` (et ADR-0026 en note de suivi).
3. **Audit** : ajouter `AuditAction.CUSTOMER_NOTE_UPDATED` à `domain/audit.py` (réutilise
   `ENTITY_TYPE_CUSTOMER`) ; compléter `tests/test_domain_audit.py`.
4. **Port** : ajouter `update_notes(salon_id, customer_id, notes)` au `Protocol`
   `application/ports/customer_repository.py`.
5. **Cas d'usage** : ajouter `UpdateCustomerNote` à `application/customers.py` (valide via
   `normalize_notes` **avant** écriture, `metadata={}`) ; l'ajouter à `__all__`.
6. **Fakes & tests applicatifs** : ajouter `FakeCustomerRepository.update_notes` à `tests/conftest.py` ;
   écrire les cas de `tests/test_customer_usecases.py` (portée, audit sans PII, effacement, note trop
   longue, `404`).
7. **Adapter sortant** : implémenter `SqlCustomerRepository.update_notes` (filtre `(salon_id, id)`,
   `CustomerNotFound` si absent, `flush()` sans `commit()`, `refresh()`).
8. **Adapter entrant** : ajouter `UpdateCustomerNoteRequest` (`extra="ignore"`, `max_length`) et la route
   `PUT …/notes` à `adapters/inbound/customers.py` (`require_salon_scope` +
   `require_permission(CUSTOMER_MANAGE)`, mapping `422`/`404`) ; **ne pas** toucher `PUBLIC_ROUTE_PATHS`.
9. **Tests API & e2e** : compléter `tests/test_customer_api.py` puis `tests/test_customer_e2e.py`
   (persistance, isolation inter-salons, traçabilité sans PII, deny-by-default) ; exécuter `pytest`
   (+ `DATABASE_URL` pour l'e2e) et `ruff check`.
10. **Web — port & gateway** : ajouter `updateNote` à `src/application/ports/customer-gateway.ts` et
    `src/adapters/api/http-customer-gateway.ts` (+ test de mapping dans
    `test/http-customer-gateway.test.ts`).
11. **Web — BFF** : créer `app/api/salons/[id]/customers/[customerId]/route.ts` (`PUT`/`PATCH` note,
    revalidation borne, messages neutres) + `test/customer-note-bff.test.ts`.
12. **Web — UI** : créer `src/adapters/ui/customer-note-form.tsx` ; brancher le panneau éditable dans
    `app/(gerant)/gerant/clients/[customerId]/page.tsx` (remplacer le `<p>` statique) ; `router.refresh()`
    au succès ; mention « visible uniquement par le salon ».
13. **Documentation** : sections dédiées dans `backend/README.md` et `web-dashboard/README.md` ; phrase
    de statut dans le `README.md` racine ; note de suivi dans ADR-0026.
14. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + **flutter test
    inchangé**), `ruff check`, `npm run lint && npm run build` ; relire la PR pour s'assurer qu'**aucune
    PII et aucun secret** (contenu de note, jeton) n'apparaissent dans les logs, l'audit ou les messages
    d'erreur, que la note **n'est exposée à aucune route publique/mobile**, et qu'**aucune signature IA**
    n'a été introduite.
