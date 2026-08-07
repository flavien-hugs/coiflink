# Modification des informations d'une fiche client (gérant) (US-4.6)

> Spécification de planification pour l'issue GitHub **#144 — US-4.6 : Modification des informations
> d'une fiche client (gérant)** (`feature` · **Must** · Effort **S** · PRD §6 Épic 4 [extension] /
> §7.2 « Clients » / §11.2 / §11.4). **Dépend de #28** (création d'une fiche client, qui a introduit
> les colonnes `full_name`/`phone`/`gender`, la tranche `/salons/{salon_id}/customers` et l'index
> unique partiel `uq_customer_profiles_salon_phone`). **Cette spec ne produit pas de code** : elle
> décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le backlog (§6 Épic 4, extension US-4.6) pose le besoin : **« nom, téléphone, genre optionnel — les
mêmes champs que la création (#28), modifiables après coup »**. Les critères d'acceptation de l'issue
#144 sont :

- Le gérant modifie le **nom**, le **téléphone** et/ou le **genre** d'une fiche client **de son salon**.
- L'unicité `(salon_id, phone)` est **respectée** en cas de changement de téléphone (conflit → **409**,
  message **neutre**, sans le numéro).
- **Isolation par salon** (§11.2) : une fiche hors salon est **indiscernable d'une fiche inexistante**
  (**404**).
- La modification est **journalisée** (§11.4), **sans fuite de PII** dans les métadonnées d'audit.

La fiche client livrée par **#28** porte déjà ces trois champs d'identité : ils sont **saisis à la
création** (`POST /salons/{salon_id}/customers`), stockés dans `customer_profiles`
(`full_name`/`phone`/`gender`), affichés sur la liste (`/gerant/clients`) et l'en-tête de la page de
détail (`/gerant/clients/{id}`). Ce que #28 a explicitement laissé hors périmètre — cf.
[ADR-0026](../docs/adr/0026-fiche-client-portee-salon.md) §*Conséquences* (« ni modification, ni
suppression de fiche ») — c'est l'**édition de ces champs après création**.

Le gap que #144 comble : **une route d'écriture qui édite l'identité d'une fiche existante** (backend)
et un **éditeur d'informations** sur la page de détail gérant (web), en **réutilisant** l'infrastructure
de #28 (validation `domain/customer.py`, permission `CUSTOMER_MANAGE`, portée salon, pré-contrôle
d'unicité `phone_exists` + index unique partiel, journal d'audit) — **sans migration** ni élargissement
de droits.

Aujourd'hui, **aucune route ne modifie une fiche existante en dehors de la note** : la tranche
`customers` (#28) expose `POST` (création), plusieurs `GET` (liste #28, fiche #28, historique #29, stats
#31) et **une seule écriture** — `PUT /salons/{salon_id}/customers/{customer_id}/notes` (édition de la
note privée, #32). Les champs d'identité `full_name`/`phone`/`gender` sont donc **figés** après la
création : le seul moyen de corriger une faute de frappe sur un nom, un numéro erroné ou un genre serait
de recréer une fiche — impossible (l'unicité `(salon_id, phone)` la refuse quand le numéro est repris) et
destructeur (l'historique #29/#31 est rattaché à la fiche via son `user_id`).

État actuel du dépôt (après #28 → #32 / #49), vérifié pour cette spec :

- **Backend** : `domain/customer.py` porte déjà **toute la validation d'identité réutilisable telle
  quelle** — `validate_customer_name` (obligatoire, trim, ≤ `CUSTOMER_NAME_MAX_LENGTH = 255`),
  `normalize_customer_phone` (optionnel, E.164 via `domain/phone.py`, vide → `None`), `normalize_gender`
  (optionnel, énumération fermée `GENDER_VALUES`, vide → `None`). `application/customers.py` expose
  `CreateCustomer` (avec **pré-contrôle d'unicité** `phone_exists` → `CustomerAlreadyExists`),
  `UpdateCustomerNote` (**le patron d'écriture ciblée le plus proche**), `ListSalonCustomers`,
  `GetCustomer`, `GetCustomerVisitHistory`, `GetCustomerServiceStats` — mais **aucune mutation
  d'identité**. `SqlCustomerRepository` implémente `create` (avec retraduction de l'`IntegrityError` du
  doublon de téléphone en `CustomerAlreadyExists`), `find_by_id`, `phone_exists`, `update_notes` — mais
  **aucun `update` d'identité**. `adapters/inbound/customers.py` câble `POST` + `GET` + `PUT …/notes`
  sous `/salons/{salon_id}/customers`.
- **Web** : `src/domain/customer/customer.ts` (validation `validateCustomer` — parité domaine — et
  `validateNote`), `src/application/ports/customer-gateway.ts` + `src/adapters/api/
  http-customer-gateway.ts` (`list`/`create`/`get`/`history`/`stats`/`updateNote`, **pas** de mise à jour
  d'identité), BFF `app/api/salons/[id]/customers/[customerId]/route.ts` (**export `PUT` = note**), page
  de détail `app/(gerant)/gerant/clients/[customerId]/page.tsx` dont l'`CustomerHeader` affiche
  `fullName`/`phone`/`gender` **en lecture seule**. Le formulaire de **création** `customer-form.tsx`
  (nom/téléphone/genre/notes) et l'éditeur de **note** `customer-note-form.tsx` sont les deux patrons UI
  à réutiliser.
- **Mobile** : les fiches clients **n'apparaissent nulle part** — l'application cliente n'a aucun accès.
  Cet invariant (fiche interne au salon) est acquis et **ne doit pas** être affaibli.
- **Schéma** : `full_name` (`String(255) NOT NULL`), `phone` (`String(32) NULL`), `gender`
  (`String(16) NULL` + `CHECK` dérivé de `enums.Gender`), l'index unique **partiel**
  `uq_customer_profiles_salon_phone … WHERE phone IS NOT NULL` et `updated_at` (`onupdate=func.now()`)
  existent depuis les migrations `0001`/`0005`. **Aucune migration n'est nécessaire** pour #144.

## Goals

- **Éditer les champs d'identité d'une fiche existante.** Nouvel endpoint modifiant `full_name`
  (obligatoire, non vide), `phone` (optionnel, E.164, `null`/vide efface) et `gender` (optionnel, enum
  fermé, `null`/vide efface) d'une fiche `(salon_id, customer_id)`, réponse `200` avec la fiche à jour
  (`CustomerResponse`, `updated_at` régénéré).
- **Respecter l'unicité `(salon_id, phone)` au changement de téléphone.** Si le nouveau numéro
  (normalisé E.164) est déjà porté par **une autre** fiche du salon → **`409`** `CustomerAlreadyExists`,
  message **neutre** (« Une fiche existe déjà pour ce numéro dans ce salon. », **sans** le numéro,
  §11.3). Deux garanties, comme #28 : le **pré-contrôle applicatif** `phone_exists` (409 explicite dans
  le cas nominal) **et** l'index unique partiel base (filet de la **course concurrente**, l'`IntegrityError`
  du perdant est retraduite). Conserver son **propre** numéro (téléphone inchangé) ne déclenche **jamais**
  de faux `409`.
- **Portée salon imposée par le chemin (§11.2), défense en profondeur.** La route est imbriquée sous
  `/salons/{salon_id}/…` (hérite de `require_salon_scope`) **et** le dépôt refiltre `(salon_id,
  customer_id)` en SQL. Une fiche d'un autre salon est **indiscernable d'une fiche inexistante** :
  `403` générique hors périmètre, `404` **après** validation de portée. Aucun oracle d'existence.
- **Seule l'identité est éditable par cette route.** `full_name`/`phone`/`gender` sont modifiables ;
  `notes` **n'est pas** touchée (elle garde sa route dédiée `PUT …/notes`, #32) ; `user_id`, `salon_id`,
  `id`, `total_visits`, `last_visit_at`, `created_at` sont **inchangés** et tout champ privilégié présent
  au corps est **ignoré** (`extra="ignore"`).
- **Réutilise `CUSTOMER_MANAGE` sans l'élargir.** La route déclare `require_permission(CUSTOMER_MANAGE)`
  + `require_salon_scope`, comme les routes #28/#32. `ROLE_PERMISSIONS` (§4.1) **n'est pas modifiée** :
  seul le `MANAGER` édite les fiches (ni `CLIENT`, ni `HAIRDRESSER`, ni `ADMIN`).
- **Modification journalisée (§11.4), sans PII.** Chaque édition enregistre une `AuditEntry`
  (`CUSTOMER_UPDATED`, entité `customer`) dans la **même unité de travail** que l'écriture. `metadata`
  ne porte que les **noms des champs modifiés** (`{"changed": ["phone", "gender"]}`, patron
  `SALON_UPDATED` #20) — **jamais** les valeurs (ni ancien nom, ni ancien/nouveau numéro, ni genre) :
  « sans fuite de PII dans les métadonnées d'audit » (critère d'acceptation).
- **Fiche jamais exposée au client (invariant conservé).** Aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` ;
  la fiche reste hors du catalogue public (#18/#19), de la disponibilité (#21) et de **toutes** les
  routes de l'application mobile. `user_id` n'est **jamais** exposé (anti-oracle ADR-0026).
- **Éditeur d'informations sur la page de détail gérant.** `/gerant/clients/{customerId}` rend l'en-tête
  `full_name`/`phone`/`gender` **éditable** (pré-rempli, `router.refresh()` après succès, mention
  d'unicité du téléphone). Le jeton d'accès reste lu **côté serveur** depuis le cookie `httpOnly`
  (invariant #14).
- **Couverture de tests.** Backend : cas d'usage (portée, unicité au changement, no-op de numéro, audit
  sans PII, `404`), API (`200`/`401`/`403`/`404`/`409`/`422`), e2e PostgreSQL (persistance, conflit de
  téléphone `409` sans écriture, isolation inter-salons, traçabilité sans PII). Web : gateway HTTP,
  Route Handler BFF, éditeur d'informations, page de détail.

## Non-Goals

- **Édition de la note privée.** Couverte par **#32** (route dédiée `PUT …/notes`). #144 **n'édite que**
  l'identité (`full_name`/`phone`/`gender`) et **ne touche pas** `notes`.
- **Suppression d'une fiche client (`DELETE`).** Hors périmètre ; l'effacement / droit à l'oubli relève
  du durcissement M6 (#52), comme documenté par ADR-0026 §*Conséquences*.
- **Rattachement de la fiche à un compte utilisateur (`user_id`).** Explicitement écarté par ADR-0026
  (§Décision 3, anti-oracle) : #144 ne rattache ni ne modifie `user_id`. Le pré-contrôle d'unicité
  n'interroge **jamais** `users` par téléphone (il ne lit que `customer_profiles`, comme #28).
- **Historique de révisions / versioning des champs.** L'audit trace **qu'**une édition a eu lieu (qui,
  quand, quelle fiche, quels champs *par leur nom*) mais **pas** les valeurs successives. Aucun journal
  des anciennes valeurs (ce serait stocker de la PII dans `audit_logs`, contraire à §11.3/§11.4).
- **Recherche / filtre serveur enrichi sur la liste.** #144 n'ajoute aucun critère de recherche ; le
  filtrage de `/gerant/clients` reste celui livré par #28.
- **Fusion de fiches doublons.** En cas de `409` (numéro déjà fiché), aucune fusion automatique n'est
  proposée — hors périmètre (échappatoire documentée par ADR-0026 §Décision 6 : ficher sans téléphone).
- **Modification de la matrice de permissions §4.1.** `CUSTOMER_MANAGE` existe déjà : #144 la réutilise
  sur une route de plus, sans l'élargir.
- **Nouvelle migration / changement de schéma.** Les colonnes et l'index unique partiel existent déjà
  (`0001`/`0005`). #144 **n'ajoute aucune migration**.
- **Verrou optimiste / gestion de concurrence applicative (`If-Match`).** Dernière écriture gagnante
  (peu d'éditeurs concurrents sur une fiche d'un salon) ; à documenter comme suivi éventuel (Risks §7).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Journal d'audit | Table `audit_logs` + port `AuditLog`, entrées **neutres** | [0019](../docs/adr/0019-journalisation-audit-et-prestations.md) |
| Fiche client | Ressource salon-scopée, `user_id` non exposé, unicité `(salon_id, phone)` | [0026](../docs/adr/0026-fiche-client-portee-salon.md) |
| Modification d'informations (précédent) | `PUT /salons/{id}` — diff neutre `{"changed": [...]}`, journalisée | [0022](../docs/adr/0022-modification-informations-salon.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

La stack et l'architecture sont **finalisées** : aucun choix de langage, framework ou outillage n'est
ouvert. La seule décision de conception restant à trancher est **la forme de la route** (verbe HTTP /
sémantique) et **le contenu de `metadata`** (voir *Risks and Open Questions*).

### Backend — patrons à réutiliser tels quels

- **Écriture d'identité avec pré-contrôle d'unicité (`CreateCustomer`, `application/customers.py:86`)** :
  `_validate(command)` (nom → téléphone → genre → notes, **avant** tout accès base) → `if phone is not
  None and repository.phone_exists(salon_id, phone): raise CustomerAlreadyExists` → `repository.create(...)`
  → `audit.record(CUSTOMER_CREATED)`. **#144 reprend exactement cette chaîne de validation et
  d'unicité**, mais sur une fiche existante (résolue d'abord) et en **n'exécutant le pré-contrôle que si
  le numéro change** (voir *Proposed Implementation*).
- **Écriture ciblée journalisée (`UpdateCustomerNote`, `application/customers.py:141`)** : validation
  domaine **avant** écriture → `repository.update_notes(...)` (résout `(salon_id, customer_id)`,
  `CustomerNotFound` **avant** l'audit) → `audit.record(CUSTOMER_NOTE_UPDATED)`, `metadata={}`. **Le
  patron structurel le plus proche** (résolution dans le salon, 404 avant audit, atomicité).
- **Modification d'informations avec diff neutre (`UpdateSalon`, `application/salons.py:217`)** :
  validation → `find_by_id` (404 si absent, portée déjà validée) → `_changed_fields(current, changes)`
  (compare les **noms** de champs, **jamais** les valeurs) → `repository.update(...)` →
  `audit.record(SALON_UPDATED, metadata={"changed": changed})`. **Le patron sémantique le plus proche**
  (c'est la « modification des informations générales » sœur, mais pour le salon) — à reprendre pour le
  `metadata.changed` de `CUSTOMER_UPDATED`.
- **Retraduction du doublon de téléphone en base (`SqlCustomerRepository.create`,
  `adapters/outbound/persistence/customer_repository.py:55`)** : `flush()` dans un `try`, `except
  IntegrityError` → `_is_phone_duplicate(exc)` (SQLSTATE `23505` **et** contrainte
  `uq_customer_profiles_salon_phone`) → `rollback()` + `raise CustomerAlreadyExists(...)`. Toute autre
  `IntegrityError` est **relevée telle quelle**. **À reprendre à l'identique** dans le nouvel `update`
  d'identité (filet de la course concurrente).
- **Filtre d'isolation `(salon_id, id)` (`update_notes`/`find_by_id`)** : `select(...).where(salon_id ==
  …, id == …)` ; `row is None` → `CustomerNotFound`. `flush()` **sans** `commit()` (le commit est piloté
  par `get_session` → atomicité avec l'audit) ; `refresh(row)` recharge `updated_at` régénéré.
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.CUSTOMER_MANAGE)`
  + `require_salon_scope` ; `403` **générique et constant** (`« Accès refusé. »`) pour rôle insuffisant
  **comme** pour accès inter-salons ; l'invariant deny-by-default est vérifié mécaniquement par
  `unprotected_routes(app)` (`test_security_guards.py`) — **une route ajoutée sans garde fait échouer les
  tests**.
- **Journalisation §11.4** : port `application/ports/audit_log.py`, entrée `domain/audit.py::AuditEntry`
  (`action`, `actor_user_id`, `salon_id`, `entity_type`, `entity_id`, `metadata`), adapter `SqlAuditLog` ;
  `get_audit_log` et le dépôt métier partagent la **même** `Session` (FastAPI met `get_session` en cache
  par requête) → commit/rollback atomique. `ENTITY_TYPE_CUSTOMER` est déjà déclaré (`domain/audit.py`).
- **Erreurs de domaine déjà présentes** (`domain/errors.py`) : `InvalidCustomerName`, `InvalidPhone`,
  `InvalidCustomerGender`, `CustomerNotFound`, `CustomerAlreadyExists`. **Aucune nouvelle erreur** n'est
  nécessaire — toutes existent depuis #28 et sont déjà mappées HTTP par l'adapter entrant
  (`_VALIDATION_ERRORS` → 422 ; `CustomerNotFound` → 404 ; `CustomerAlreadyExists` → 409).
- **Tests** : fakes en mémoire dans `tests/conftest.py` (`FakeCustomerRepository` avec `create`,
  `find_by_id`, `phone_exists`, `update_notes`, drapeau `raise_conflict` simulant la course concurrente ;
  `FakeAuditLog`, `FakeSalonScopeRepository`…) ; tests d'API via `TestClient` + `app.dependency_overrides` ;
  **tests e2e** (`test_customer_e2e.py`) adossés à un vrai PostgreSQL, sautés si `DATABASE_URL` est absent,
  avec plage de téléphones réservée et nettoyage avant/après.

### Web gérant — patrons à réutiliser (#28 / #32)

- `app/(gerant)/gerant/clients/[customerId]/page.tsx` = **Server Component** : lit le cookie
  (`createCookieSessionStore().read()`), appelle les gateways HTTP côté serveur (`get`/`history`/`stats`),
  rend l'UI. `CustomerHeader` affiche `fullName`/`phone`/`gender` **en lecture seule** — **à rendre
  éditable**. Un composant `Tabs` organise déjà « Note privée » / « Historique des visites » /
  « Prestations préférées ».
- `src/adapters/ui/customer-form.tsx` (**création**) : `<input>` nom/téléphone + `SearchableSelect` genre,
  validation `validateCustomer` côté client, `POST` vers le BFF, mapping des statuts (dont `409` →
  « Une fiche existe déjà pour ce numéro dans ce salon. »), `router.refresh()` au succès. **Modèle direct**
  de l'éditeur d'identité (pré-rempli, `PATCH`/`PUT`).
- `src/adapters/ui/customer-note-form.tsx` (**édition ciblée**) : `<textarea>` pré-remplie, poste au BFF,
  `router.refresh()`, mention « visible uniquement par le salon ». **Modèle** du câblage éditeur ↔ BFF.
- `src/adapters/api/http-customer-gateway.ts` : `fetch` vers le backend avec `Authorization: Bearer`,
  résultat en **union discriminée** (`{ ok:true, … } | { ok:false, reason:"invalid"|"duplicate"|
  "forbidden"|"unauthenticated"|"not-found"|"unavailable" }`). `create` **mappe déjà** `409 →
  "duplicate"` — à reprendre pour la mise à jour d'identité.
- BFF : `app/api/salons/[id]/customers/[customerId]/route.ts` **exporte déjà `PUT` = note** (#32). Le
  handler de mise à jour d'identité **s'ajoute au même fichier** sous un **autre verbe** (voir *Risks §1*)
  pour éviter toute collision avec la note ; il revalide le corps (parité `validateCustomer`), lit le
  jeton du cookie `httpOnly`, appelle le gateway, renvoie des messages **neutres** en français.
- `src/domain/customer/customer.ts` : `validateCustomer` (nom/téléphone/genre/notes) — réutilisable ;
  une aide `validateProfile` (identité seule, sans `notes`) peut être extraite, ou `validateCustomer`
  réutilisée en ignorant `notes`.

### Contraintes transverses documentées

- **PRD §11.2** : « un gérant ne peut voir que les données de son salon ».
- **PRD §11.3** : collecte **minimale**, journalisation des accès sensibles, messages neutres sans PII.
- **PRD §11.4** : journalisation des actions importantes (entrées **neutres**, ADR-0019).
- **PRD §12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA** (code, commits, PR).
- **Test gate** : `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI applicative `ci.yml`
  (ruff, pytest, round-trip Alembic contre PostgreSQL 16, build/lint/test web).

## Proposed Implementation

> Décision de conception recommandée (à confirmer, *Risks §1*) : **`PATCH /salons/{salon_id}/customers/
> {customer_id}`** côté backend, verbe **`PATCH`** côté BFF web (la note conserve son `PUT …/notes` et
> son `PUT` BFF). Le corps porte les **trois champs d'identité** (`full_name` obligatoire, `phone`/`gender`
> nullables) : le formulaire est **pré-rempli** des valeurs courantes, si bien que « modifier le nom, le
> téléphone **et/ou** le genre » se ramène à renvoyer le triplet avec les seuls champs voulus changés.
> Cette forme **évite l'ambiguïté « champ omis vs `null` »** d'un vrai PATCH partiel tout en gardant un
> verbe qui signale « on ne touche qu'à l'identité, pas à la note ». Le reste de la spec est indépendant
> du verbe finalement retenu.

### (A) Backend — domaine

Aucune nouvelle entité, aucune nouvelle validation. `validate_customer_name`, `normalize_customer_phone`
et `normalize_gender` (`domain/customer.py`) couvrent déjà l'intégralité de la validation d'identité.
**Réutiliser telles quelles.** Aucune nouvelle erreur (`domain/errors.py` : toutes présentes).

**`domain/audit.py`** : ajouter une valeur d'action :

```python
# Fiche client — #144 (US-4.6). Modification des champs d'identité (nom, téléphone,
# genre) d'une fiche existante. Journalisée au titre de §11.4 (« Modification »).
# `metadata` ne porte que les NOMS des champs modifiés (`{"changed": [...]}`, patron
# SALON_UPDATED) — jamais une valeur (ni nom, ni numéro, ni genre) : §11.3/§11.4.
CUSTOMER_UPDATED = "CUSTOMER_UPDATED"
```

`ENTITY_TYPE_CUSTOMER` existe déjà — **le réutiliser**. Compléter `tests/test_domain_audit.py`.

### (B) Backend — port de persistance

**`application/ports/customer_repository.py`** — ajouter une méthode au `Protocol` `CustomerRepository` :

```python
def update(
    self,
    salon_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    full_name: str,
    phone: str | None,
    gender: str | None,
) -> Customer: ...
```

Docstring : filtre `(salon_id, customer_id)` (isolation §11.2) ; lève `CustomerNotFound` si la fiche est
absente du salon (jamais un oracle) ; lève `CustomerAlreadyExists` si l'index unique partiel
`uq_customer_profiles_salon_phone` est violé — **y compris le perdant d'une course concurrente**
(l'`IntegrityError` est retraduite, jamais propagée) ; `phone = None`/`gender = None` **effacent** le
champ ; **seules** les colonnes d'identité sont écrites (`notes`/`user_id`/compteurs inchangés).

> Alternative de découpage (mineure) : passer un petit objet de valeurs (`CustomerIdentityUpdate`) au
> lieu de trois kwargs — à trancher à l'implémentation, cohérent avec `SalonUpdate` de #20.

### (C) Backend — adapter de persistance

**`adapters/outbound/persistence/customer_repository.py::SqlCustomerRepository`** — implémenter `update`
(fusion des patrons `update_notes` et `create`) :

```python
def update(self, salon_id, customer_id, *, full_name, phone, gender):
    row = self._session.scalar(
        select(models.CustomerProfile).where(
            models.CustomerProfile.salon_id == salon_id,
            models.CustomerProfile.id == customer_id,
        )
    )
    if row is None:
        raise CustomerNotFound("Fiche client introuvable.")
    row.full_name = full_name
    row.phone = phone
    row.gender = gender
    try:
        self._session.flush()          # UPDATE + contraintes, sans commit
    except IntegrityError as exc:
        if _is_phone_duplicate(exc):   # course concurrente perdue : filet base
            self._session.rollback()
            raise CustomerAlreadyExists(
                "Une fiche existe déjà pour ce numéro dans ce salon."
            ) from exc
        raise                           # toute autre IntegrityError remonte
    self._session.refresh(row)          # recharge updated_at régénéré (onupdate)
    return _to_domain(row)
```

`_is_phone_duplicate` et `_to_domain` existent déjà — **les réutiliser**. Mettre à jour la mienne du
même numéro n'entraîne **aucune** violation d'index (même ligne).

### (D) Backend — cas d'usage

**`application/customers.py`** — ajouter `UpdateCustomer` (fusion `CreateCustomer` + `UpdateSalon`) :

```python
class UpdateCustomer:
    """Modifie l'identité (nom/téléphone/genre) d'une fiche du salon et journalise (§11.4, US-4.6, #144)."""

    def __init__(self, repository: CustomerRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(self, salon_id, customer_id, command: CustomerCommand, *, actor_user_id) -> Customer:
        # 1. Validation domaine AVANT tout accès base (aucune écriture ni audit si invalide).
        full_name = validate_customer_name(command.full_name)
        phone = normalize_customer_phone(command.phone)
        gender = normalize_gender(command.gender)

        # 2. Résout la fiche DANS le salon (404 après portée si hors salon/inconnue).
        current = self._repository.find_by_id(salon_id, customer_id)
        if current is None:
            raise CustomerNotFound("Fiche client introuvable.")

        # 3. Pré-contrôle d'unicité UNIQUEMENT si le numéro change (jamais de faux 409
        #    contre soi-même). En concurrence, l'index base tranche (repository.update).
        if phone is not None and phone != current.phone and self._repository.phone_exists(salon_id, phone):
            raise CustomerAlreadyExists("Une fiche existe déjà pour ce numéro dans ce salon.")

        # 4. Diff NEUTRE (noms de champs uniquement — jamais de valeur, §11.3/§11.4).
        changed = [
            name for name, before, after in (
                ("full_name", current.full_name, full_name),
                ("phone", current.phone, phone),
                ("gender", current.gender, gender),
            ) if before != after
        ]

        customer = self._repository.update(
            salon_id, customer_id, full_name=full_name, phone=phone, gender=gender
        )
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.CUSTOMER_UPDATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_CUSTOMER,
                entity_id=customer.id,
                metadata={"changed": changed},   # NOMS de champs — aucune PII
            )
        )
        return customer
```

- Réutilise la `CustomerCommand` existante (`full_name`/`phone`/`gender`/`notes`) — `notes` est **ignoré**
  par ce cas d'usage (l'adapter entrant ne le renseignera pas ; #144 ne touche pas la note). Une variante
  plus stricte crée une commande dédiée sans `notes` — décision mineure (*Risks §6*).
- La validation précède **toute** écriture ; `CustomerNotFound` précède l'audit ; l'unicité est
  contrôlée **avant** l'`update` (409 nominal) et **garantie** par l'index (409 concurrent). Aucune trace
  d'audit n'est produite pour une cible inexistante, invalide ou en conflit.
- Ajouter `UpdateCustomer` à `__all__` et à l'import de l'adapter entrant.

### (E) Backend — adapter entrant (HTTP)

**`adapters/inbound/customers.py`** — ajouter au router existant (`prefix="/salons"`) :

- Schéma Pydantic `UpdateCustomerRequest` :

  ```python
  class UpdateCustomerRequest(BaseModel):
      model_config = ConfigDict(extra="ignore")   # ignore salon_id/id/user_id/notes/compteurs
      full_name: str = Field(min_length=1, max_length=CUSTOMER_NAME_MAX_LENGTH, examples=["Awa Koné"])
      phone: str | None = Field(default=None, examples=["0700000000"])
      gender: str | None = Field(default=None, examples=[GENDER_VALUES[0]])
  ```

- Route (verbe recommandé `PATCH`, *Risks §1*) :

  ```python
  @router.patch(
      "/{salon_id}/customers/{customer_id}",
      response_model=CustomerResponse,
      summary="Modifier l'identité d'une fiche client (nom, téléphone, genre)",
      responses={
          401: {"description": "Jeton absent, invalide ou expiré"},
          403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
          404: {"description": "Fiche introuvable (portée déjà validée)"},
          409: {"description": "Une fiche porte déjà ce téléphone dans ce salon"},
          422: {"description": "Nom, téléphone ou genre invalides"},
      },
  )
  def update_customer(
      salon_id, customer_id, payload: UpdateCustomerRequest,
      repository=Depends(get_customer_repository),
      audit_log=Depends(get_audit_log),
      _scope=Depends(require_salon_scope),
      principal=Depends(require_permission(Permission.CUSTOMER_MANAGE)),
  ) -> CustomerResponse:
      try:
          customer = UpdateCustomer(repository, audit_log).execute(
              salon_id, customer_id,
              CustomerCommand(full_name=payload.full_name, phone=payload.phone, gender=payload.gender),
              actor_user_id=principal.id,
          )
      except _VALIDATION_ERRORS as exc:
          raise HTTPException(422, detail=str(exc)) from exc
      except CustomerNotFound as exc:
          raise HTTPException(404, detail=str(exc)) from exc
      except CustomerAlreadyExists as exc:
          raise HTTPException(409, detail=str(exc)) from exc
      return _customer_response(customer)
  ```

- Réutilise `_customer_response`, `CustomerResponse`, `require_salon_scope`,
  `require_permission(CUSTOMER_MANAGE)`, `_VALIDATION_ERRORS` (déjà présents). **Aucun** chemin ajouté à
  `PUBLIC_ROUTE_PATHS`. Le router `customers` est déjà `include`d dans `main.py` : **aucun câblage
  supplémentaire**.

### (F) Web gérant — éditeur d'identité

1. **Port & gateway** — `src/application/ports/customer-gateway.ts` : ajouter `updateProfile(salonId,
   customerId, input): Promise<UpdateProfileResult>` où `input` est `{ fullName; phone: string | null;
   gender: Gender | null }` et `UpdateProfileResult` est l'union `{ ok:true; customer } | { ok:false;
   reason:"invalid"|"duplicate"|"forbidden"|"unauthenticated"|"not-found"|"unavailable" }` (mêmes motifs
   que `CreateCustomerResult`). `src/adapters/api/http-customer-gateway.ts` : implémenter `updateProfile`
   (`PATCH` vers `${customersUrl(salonId)}/${customerId}`, corps `{ full_name, phone, gender }`, mapping
   `200 → ok` / `401` / `403` / `404 → not-found` / `409 → duplicate` / `422 → invalid` / `→ unavailable`),
   **sans jamais** journaliser le jeton ni la PII.
2. **BFF** — `app/api/salons/[id]/customers/[customerId]/route.ts` : **ajouter un export `PATCH`** au
   fichier existant (le `PUT` = note reste inchangé). Le handler lit le corps (`{ full_name/fullName,
   phone, gender }`), revalide via `validateCustomer` (en ignorant `notes`) — parité domaine —, lit le
   jeton du cookie `httpOnly`, appelle `gateway.updateProfile(...)`, renvoie un corps **neutre** (`409`
   « Une fiche existe déjà pour ce numéro dans ce salon. », `422` « Fiche client invalide. », `403`
   « Action non autorisée sur ce salon. », `404` « Fiche client introuvable. »). Miroir du handler `PUT`
   note.
3. **UI** — `src/adapters/ui/customer-profile-form.tsx` (client component) : `<input>` nom (requis) /
   téléphone + `SearchableSelect` genre, **pré-remplis** des valeurs courantes (props `initialFullName`,
   `initialPhone`, `initialGender`) ; bouton « Enregistrer les modifications » ; poste `PATCH` au BFF ;
   `router.refresh()` au succès ; mapping `409` → message d'unicité, `422`/`403`/`404`/`401`/défaut →
   messages neutres. Calqué sur `customer-form.tsx`.
4. **Page de détail** — `app/(gerant)/gerant/clients/[customerId]/page.tsx` : rendre l'identité éditable.
   *Recommandation* : ajouter un onglet **« Informations »** (premier `Tabs`) contenant
   `CustomerProfileForm` (props `salonId`, `customerId`, valeurs initiales de `customerResult.customer`),
   en gardant `CustomerHeader` comme récapitulatif en tête. La note (#32), l'historique (#29) et les
   préférées (#31) restent inchangés.
5. **Domaine (option)** — `src/domain/customer/customer.ts` : au besoin, extraire `validateProfile`
   (nom/téléphone/genre, sans `notes`) réutilisée par le BFF et le formulaire ; sinon réutiliser
   `validateCustomer` en passant `notes: null`.

### (G) Documentation

- `backend/README.md` : compléter la section « Clients » avec la route d'édition d'identité (permission,
  portée, réponses `200`/`401`/`403`/`404`/`409`/`422`, unicité au changement de téléphone, audit
  `CUSTOMER_UPDATED` `metadata.changed` sans valeur).
- `web-dashboard/README.md` : mentionner l'édition de l'identité sur `/gerant/clients/{id}` et le verbe
  ajouté au BFF `app/api/salons/[id]/customers/[customerId]`.
- `README.md` (racine) : phrase de statut §6 (M4 : modification de la fiche client, #144).
- `docs/adr/0026-fiche-client-portee-salon.md` : note de suivi « modification des champs d'identité
  livrée par #144 » (l'ADR §*Conséquences* dit aujourd'hui « ni modification, ni suppression de fiche
  (l'édition de la note privée est US-4.5/#32) » — à amender). Pas de nouvel ADR (voir *Open Questions §5*).
- **OpenAPI** : le `summary`/`responses`/docstring de la route documentent la nouvelle API (`/docs`).

## Affected Files / Packages / Modules

### Backend (`backend/`) — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/audit.py` | `AuditAction.CUSTOMER_UPDATED` (réutilise `ENTITY_TYPE_CUSTOMER`) |
| `coiflink_api/application/ports/customer_repository.py` | méthode `update(salon_id, customer_id, *, full_name, phone, gender)` au `Protocol` |
| `coiflink_api/application/customers.py` | cas d'usage `UpdateCustomer` (+ `__all__`) |
| `coiflink_api/adapters/outbound/persistence/customer_repository.py` | `SqlCustomerRepository.update` (filtre `(salon_id, id)`, `CustomerNotFound`, filet `IntegrityError` → `CustomerAlreadyExists`) |
| `coiflink_api/adapters/inbound/customers.py` | schéma `UpdateCustomerRequest` + route `PATCH …/{customer_id}` + import `UpdateCustomer` |
| `tests/conftest.py` | `FakeCustomerRepository.update` (404 hors salon ; `CustomerAlreadyExists` si un **autre** fiche du salon a le nouveau numéro ; sinon remplace + bump `updated_at`) |
| `tests/test_customer_usecases.py` | cas `UpdateCustomer` (portée, unicité au changement, no-op de numéro, effacement, audit `changed` sans PII, 404) |
| `tests/test_customer_api.py` | `200`/`401`/`403`/`404`/`409`/`422`, corps privilégié (dont `notes`) ignoré |
| `tests/test_customer_e2e.py` | persistance, conflit `409` sans écriture, isolation inter-salons, traçabilité sans PII |
| `tests/test_domain_audit.py` | `CUSTOMER_UPDATED` couverte |
| `backend/README.md` | route d'édition d'identité dans la section « Clients » |

### Backend — à lire (sans modifier) pour rester fidèle aux patrons

`application/customers.py` (`CreateCustomer`, `UpdateCustomerNote`), `application/salons.py`
(`UpdateSalon`, `_changed_fields`), `adapters/outbound/persistence/customer_repository.py`
(`create`, `update_notes`, `_is_phone_duplicate`, `_to_domain`), `adapters/inbound/security.py`,
`domain/customer.py` (`validate_customer_name`/`normalize_customer_phone`/`normalize_gender`),
`adapters/inbound/customers.py` (routes #28/#32).

### Web (`web-dashboard/`)

À créer : `src/adapters/ui/customer-profile-form.tsx`, `test/customer-profile-bff.test.ts`,
`test/customer-profile-form.test.tsx` (si le socle de test composant le permet).
À modifier : `src/application/ports/customer-gateway.ts` (`updateProfile` + `UpdateProfileResult`),
`src/adapters/api/http-customer-gateway.ts` (`updateProfile`),
`app/api/salons/[id]/customers/[customerId]/route.ts` (**ajout d'un export `PATCH`**, le `PUT` note
inchangé), `app/(gerant)/gerant/clients/[customerId]/page.tsx` (onglet « Informations » éditable),
`src/domain/customer/customer.ts` (option : `validateProfile`),
`test/http-customer-gateway.test.ts` (mapping `updateProfile`), `web-dashboard/README.md`.

### Documentation (racine)

`README.md`, `docs/adr/0026-fiche-client-portee-salon.md` (note de suivi).

## API / Interface Changes

**Un nouvel endpoint REST**, protégé (`CUSTOMER_MANAGE` + portée salon) ; aucune route existante n'est
modifiée ; aucun chemin n'entre dans `PUBLIC_ROUTE_PATHS`.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `PATCH` *(recommandé, cf. Risks §1)* | `/salons/{salon_id}/customers/{customer_id}` | `CUSTOMER_MANAGE` + portée | `200` fiche à jour · `401` · `403` · `404` fiche hors salon/inconnue · `409` téléphone déjà fiché dans ce salon · `422` nom/téléphone/genre invalides |

```jsonc
// PATCH /salons/{salon_id}/customers/{customer_id} — corps
{
  "full_name": "Awa Koné",           // requis, non vide, ≤ 255
  "phone": "0700000000",             // string | null ; null/"" efface ; normalisé E.164 côté serveur
  "gender": "FEMALE"                 // "FEMALE" | "MALE" | "OTHER" | null ; null/"" efface
}

// 200 — réponse (identique à GET fiche : CustomerResponse)
{
  "id": "…uuid…",
  "salon_id": "…uuid…",
  "full_name": "Awa Koné",
  "phone": "+2250700000000",
  "gender": "FEMALE",
  "notes": "…inchangée…",            // NON éditée par cette route (#32 la gère)
  "last_visit_at": null,
  "total_visits": 0,
  "created_at": "2026-07-24T09:00:00Z",
  "updated_at": "2026-08-07T11:30:00Z"   // régénéré à l'édition
}
```

- Champs privilégiés du corps (`salon_id`, `id`, `user_id`, `notes`, `total_visits`, `last_visit_at`,
  `created_at`, `updated_at`) : **ignorés** (`extra="ignore"`). Seuls `full_name`/`phone`/`gender` sont pris
  en compte.
- `user_id` **n'est pas exposé** (anti-oracle, ADR-0026), cohérent avec les routes #28/#32.
- Message `409` **neutre** : « Une fiche existe déjà pour ce numéro dans ce salon. » — **jamais** le numéro.

**Interface web (BFF, interne à Next.js)** : `PATCH /api/salons/[id]/customers/[customerId]` (ajouté au
Route Handler existant, dont le `PUT` = note reste inchangé). **Aucune** modification de CLI, de variable
d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**Aucune.** Les colonnes `customer_profiles.full_name` (`String(255) NOT NULL`), `phone`
(`String(32) NULL`), `gender` (`String(16) NULL` + `CHECK` genre) et l'index unique **partiel**
`uq_customer_profiles_salon_phone … WHERE phone IS NOT NULL` existent depuis les migrations `0001`/`0005`
et sont déjà écrits à la création (#28). #144 se contente de les **mettre à jour** — **pas de migration**,
pas de nouveau `CHECK`, pas d'index, pas de changement de sérialisation. `updated_at` est régénéré par le
`onupdate=func.now()` existant du modèle ORM.

## Security & Privacy Considerations

**Ce module modifie des données personnelles** (nom, téléphone, genre — PII, §11.3). C'est sa principale
sensibilité et l'origine des garde-fous ci-dessous.

- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur la route (portée **chargée en
  base**, jamais déduite du corps) **et** filtre `(salon_id, customer_id)` en SQL dans `update`. Un accès
  inter-salons renvoie le **`403` générique et constant** (`« Accès refusé. »`), identique à un rôle
  insuffisant : aucun oracle. Le `404` (fiche introuvable) n'est renvoyé qu'**après** validation de portée.
  Un test e2e inter-salons l'exige explicitement.
- **Unicité `(salon_id, phone)` respectée, sans divulgation.** Le pré-contrôle `phone_exists` (409
  explicite au cas nominal, **uniquement si le numéro change**) **et** l'index unique partiel base (filet
  de la course concurrente, `IntegrityError` retraduite) garantissent qu'aucune édition ne crée deux
  fiches pour un même numéro. Le message `409` est **neutre** — il ne reprend **jamais** le numéro (§11.3).
  Conserver son propre numéro ne déclenche **aucun** faux conflit (test dédié).
- **Permission `CUSTOMER_MANAGE` seule (§4.1).** Détenue par le seul `MANAGER` ; `ROLE_PERMISSIONS`
  **n'est pas modifiée**. Ni le `CLIENT`, ni le `HAIRDRESSER`, ni l'`ADMIN` n'éditent les fiches
  (supervision ≠ exploitation, ADR-0015).
- **Aucune PII dans le journal d'audit (§11.4, ADR-0019).** `CUSTOMER_UPDATED` porte `actor_user_id`
  (UUID opaque), `salon_id`, `entity_type="customer"`, `entity_id` et **`metadata = {"changed": [...]}`**
  — **noms de champs uniquement** (`"full_name"`/`"phone"`/`"gender"`), **jamais** l'ancienne ou la
  nouvelle valeur. C'est le sens exact de « sans fuite de PII dans les métadonnées d'audit » (critère
  d'acceptation) ; un test l'exige (assertion : aucune valeur d'identité n'apparaît dans `metadata`).
- **Aucune PII ni secret dans les logs / messages d'erreur.** Aucun `print`/`logger` ne reçoit le corps
  de requête ni les valeurs d'identité ; les messages `4xx` restent **métier et neutres** (« Fiche
  client invalide. », « Une fiche existe déjà pour ce numéro dans ce salon. ») sans reprendre nom ni
  numéro. Le BFF et le gateway web ne journalisent jamais le jeton, l'en-tête `Authorization` ni la PII.
- **Validation avant écriture.** `validate_customer_name`/`normalize_customer_phone`/`normalize_gender`
  bornent et normalisent **avant** toute mutation : un champ invalide ne produit ni écriture, ni entrée
  d'audit (budget §12.1).
- **Atomicité mutation + audit.** L'écriture (`flush()` sans `commit()`) et l'`AuditEntry` partagent la
  **même** `Session` : soit les deux sont committées, soit aucune (patron #17/#20/#28/#32). Un `409`
  concurrent déclenche un `rollback()` — aucune trace d'audit pour une mutation avortée.
- **Fiche jamais exposée au client (invariant conservé).** Aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` ;
  la fiche n'apparaît ni au catalogue public (#18/#19), ni dans la disponibilité (#21), ni dans **aucune**
  route de l'application mobile. `user_id` n'est **jamais** exposé.
- **Pas d'oracle d'existence de compte.** Comme #28, la route n'interroge **jamais** `users` par
  téléphone (`phone_exists` ne lit que `customer_profiles`) et n'expose pas `user_id` : éditer une fiche
  n'apprend rien sur l'existence d'un compte.
- **Jeton jamais exposé côté web (#14).** La page de détail et le Route Handler BFF lisent le cookie
  `httpOnly` **côté serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais journalisé.

Le dépôt **documente** ces contraintes (PRD §11.2/§11.3/§11.4, ADR-0015/0019/0022/0026) : #144 les
respecte sans en affaiblir aucune.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **`tests/test_customer_usecases.py`** (fakes de `conftest.py`) :
  - édition nominale : `update` reçoit le `salon_id` de **portée** et les champs **normalisés** ;
    `CUSTOMER_UPDATED` enregistrée **une fois**, bon `actor_user_id`/`salon_id`/`entity_id`, et
    `metadata == {"changed": [...]}` contenant **les noms** des champs modifiés (aucune valeur) ;
  - **numéro inchangé** : réédition avec le même téléphone → **pas** de `409`, `phone_exists` non
    déterminant (`changed` n'inclut pas `phone`) ;
  - **numéro changé libre** : nouveau numéro non fiché → `200`, `changed` inclut `phone` ;
  - **numéro changé en conflit** : numéro déjà porté par une **autre** fiche du salon →
    `CustomerAlreadyExists`, **aucune** écriture ni audit ;
  - **effacement** : `phone`/`gender` = `""`/`None`/`"   "` → `None` (champ effacé), `changed` reflète ;
  - **nom vide** → `InvalidCustomerName`, **aucune** écriture ni audit ; **genre hors enum** →
    `InvalidCustomerGender` ; **téléphone malformé** → `InvalidPhone` ;
  - fiche d'un **autre salon** / inconnue → `CustomerNotFound`, **aucun** audit ;
  - **`notes` non touchée** : l'édition ne modifie pas la note existante.
- **`tests/test_domain_audit.py`** : `CUSTOMER_UPDATED` présente et cohérente (valeur d'enum, entité
  `customer`).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_customer_api.py`** : `200` + corps attendu (identité mise à jour, `updated_at` changé,
  `notes` **inchangée**, **pas de `user_id`**) ; corps portant `salon_id`/`id`/`user_id`/`notes`/
  `total_visits`/`last_visit_at` → **ignorés** ; `409` numéro déjà fiché (message **neutre**, sans le
  numéro) ; `422` nom vide / téléphone malformé / genre hors enum ; `404` fiche d'un autre salon ; `403`
  hors portée / rôle non `MANAGER` (message **constant**) ; `401` sans jeton ; effacement
  (`phone: null`, `gender: null`) → `200`.
- **`tests/test_security_guards.py`** : l'invariant `unprotected_routes(app) == []` couvre
  automatiquement la nouvelle route ; vérifier qu'**aucun** chemin `customers` n'entre dans
  `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_customer_e2e.py`** (patron existant, plage de téléphones réservée, nettoyage
  avant/après) :
  1. parcours : inscription gérant → connexion → création salon → **création de fiche** → **édition
     nom/genre** → `GET` fiche renvoie les nouvelles valeurs ; effacement (`phone: null`) laisse
     `phone = NULL` en base ;
  2. **conflit de téléphone** : créer deux fiches A et B ; éditer A avec le numéro de B → **`409`** et A
     **inchangée** en base (aucune écriture partielle) ; éditer A avec un **nouveau** numéro libre →
     `200` ; ré-éditer A en conservant son propre numéro → `200` (pas de faux `409`) ;
  3. **isolation inter-salons** : le jeton du gérant B est refusé (`403` générique) sur la fiche du salon
     de A ;
  4. **traçabilité** : une ligne `audit_logs` `CUSTOMER_UPDATED` avec le bon acteur, `metadata.changed`
     ne contenant que des **noms de champs**, et **aucune** valeur d'identité (assertion explicite : nom
     et numéro **n'apparaissent pas** dans `metadata`) ;
  5. deny-by-default : sans jeton → `401`.
- **Migration** : **aucune** (pas de changement de schéma) — rien à couvrir côté Alembic.

### Web (`vitest`)

- `test/http-customer-gateway.test.ts` : mapping `updateProfile` (`200 → ok`, `409 → "duplicate"`,
  `403 → "forbidden"`, `401 → "unauthenticated"`, `404 → "not-found"`, `422 → "invalid"`,
  `→ "unavailable"`), en-tête `Authorization` posé, **jeton jamais renvoyé** dans le résultat.
- `test/customer-profile-bff.test.ts` : `401` sans cookie ; `422` corps invalide (nom vide, genre hors
  enum) ; `409`/`403`/`404` propagés avec message **neutre** (sans numéro) ; **aucune PII ni jeton** dans
  les réponses d'erreur ; effacement (`phone: null`) accepté.
- `test/customer-profile-form.test.tsx` (si le socle le permet) : pré-remplissage des valeurs courantes,
  message d'unicité sur `409`, `router.refresh()` déclenché au succès.

### Documentation / non-régression

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre ; `npm run
  lint && npm run build` (sortie standalone) inchangé ; l'application mobile (`flutter test`) reste
  **verte et inchangée** (aucune exposition de fiche).

## Documentation Updates

- **`backend/README.md`** — section « Clients » : ajouter la route d'édition d'identité (`PATCH`
  recommandé, permission `CUSTOMER_MANAGE`, portée §11.2, réponses `200`/`401`/`403`/`404`/`409`/`422`,
  unicité au changement de téléphone, audit `CUSTOMER_UPDATED` `metadata.changed` sans valeur), avec un
  exemple `curl` et la règle « `null`/vide efface `phone`/`gender` ».
- **`web-dashboard/README.md`** — mentionner l'édition de l'identité sur `/gerant/clients/{id}`
  (onglet « Informations ») et le verbe ajouté au BFF `app/api/salons/[id]/customers/[customerId]`.
- **`README.md`** (racine) — §6 : phrase de statut « M4 : modification de la fiche client (US-4.6, #144)
  — nom/téléphone/genre éditables, unicité `(salon_id, phone)` respectée, journalisée sans PII » dans le
  style des paragraphes existants.
- **`docs/adr/0026-fiche-client-portee-salon.md`** — amender §*Conséquences* (« ni modification, ni
  suppression de fiche… ») par une note de suivi : la **modification des champs d'identité** est livrée
  par #144 (la suppression restant hors périmètre / M6) ; **pas** de nouvel ADR (voir *Open Questions §5*).
- **OpenAPI** — `summary`/`responses`/docstring de la route documentent la nouvelle API (`/docs`).

## Risks and Open Questions

1. **Verbe HTTP et forme de la route.** *Recommandation : `PATCH /salons/{salon_id}/customers/
   {customer_id}`* — la note (#32) occupe déjà `PUT …/notes` (backend) et `PUT` sur le BFF base
   `[customerId]`; utiliser `PATCH` pour l'identité **évite toute collision de verbe** sur le même chemin
   BFF et signale « modification partielle de la fiche (identité, pas la note) ». Le corps porte le
   **triplet complet** (`full_name` requis, `phone`/`gender` nullables) préfilé côté UI, ce qui évite
   l'ambiguïté « champ omis vs `null` » d'un PATCH partiel strict. **Alternatives** : (a) `PUT
   /salons/{salon_id}/customers/{customer_id}` (remplacement d'identité, miroir exact d'`UpdateSalon` #20)
   — mais le BFF `PUT` base est déjà la note, imposant un chemin BFF distinct ou le déplacement du BFF
   note ; (b) vrai `PATCH` partiel avec sémantique « champ absent = inchangé » (nécessite un sentinel
   Pydantic pour distinguer `null` d'« absent »). **À trancher avant l'implémentation** ; backend et BFF
   doivent rester cohérents.
2. **Contenu de `metadata` d'audit.** *Recommandation : `metadata = {"changed": [noms de champs]}`*
   (patron `SALON_UPDATED` #20/ADR-0022, et lecture directe du critère « sans fuite de PII dans les
   métadonnées » — donc des métadonnées **présentes mais non-PII**). **Alternative** : `metadata = {}`
   (parité `CUSTOMER_CREATED`/`CUSTOMER_NOTE_UPDATED`) — plus pauvre en traçabilité. À **proscrire**
   absolument : toute **valeur** de champ (ancien/nouveau nom, numéro, genre) — ce serait de la PII au
   journal, contraire à §11.3/§11.4. Décision à confirmer.
3. **Unicité au changement de téléphone — logique exacte.** *Recommandation : pré-contrôle `phone_exists`
   **uniquement si le nouveau numéro (normalisé) diffère du courant**, filet base pour la concurrence.*
   Comme le numéro courant appartient à la fiche éditée, `phone_exists(salon_id, nouveau_numéro)` renvoyant
   `True` implique **une autre** fiche → `409` ; on n'a donc **pas besoin** d'une variante « exclure soi ».
   Conserver son propre numéro → pas de pré-contrôle, pas de faux `409` ; mettre à jour la même ligne ne
   viole pas l'index. **À valider par un test dédié** (no-op de numéro).
4. **Effacement de `phone`/`gender`.** *Recommandation : `null`/chaîne vide efface le champ* (`= NULL`),
   cohérent avec la normalisation #28 (`normalize_customer_phone`/`normalize_gender` : vide → `None`). Le
   **nom** reste **obligatoire** (jamais effaçable). **À confirmer** si l'effacement du téléphone doit
   être interdit (peu probable — la colonne est nullable, clients walk-in).
5. **Un ADR est-il requis ?** #144 est **additif** : une route d'écriture réutilisant colonnes,
   permission, pré-contrôle d'unicité et patron d'audit de #28, **sans migration** ni décision
   d'architecture nouvelle (le seul point de conception, l'unicité au changement, découle directement
   d'ADR-0026 §Décision 6). Par parité avec #29/#31/#32 (aucun ADR), *recommandation : pas de nouvel ADR*
   — replier la décision dans `backend/README.md` et une note de suivi dans ADR-0026. **À confirmer** ;
   si l'équipe préfère tracer la sémantique « unicité au changement » et le choix de verbe, un court
   ADR-0039 est possible (le salon a eu ADR-0022 pour son équivalent).
6. **Commande dédiée vs `CustomerCommand` réutilisée.** *Recommandation : réutiliser `CustomerCommand`*
   (le cas d'usage ignore `notes`) pour limiter la surface. **Alternative** : une `CustomerIdentityCommand`
   sans `notes` (plus explicite). Décision mineure, à trancher à l'implémentation.
7. **Concurrence.** Deux éditions simultanées de la même fiche : **dernière écriture gagnante** (pas de
   verrou optimiste). Acceptable pour une fiche d'un salon (peu d'éditeurs concurrents). Pas d'`If-Match`/
   version au MVP — à documenter comme suivi si le besoin émerge.
8. **Test de composant web.** Selon la maturité du socle `vitest`/testing-library du `web-dashboard`, le
   test de `customer-profile-form.tsx` peut être limité ; à défaut, couvrir la logique via le BFF et le
   gateway (comme #28/#32 l'ont fait). Vérifier l'existant avant d'ajouter une dépendance de test.

## Implementation Checklist

1. **Lire** `application/customers.py` (`CreateCustomer`, `UpdateCustomerNote`), `application/salons.py`
   (`UpdateSalon`, `_changed_fields`), `adapters/outbound/persistence/customer_repository.py`
   (`create`, `update_notes`, `_is_phone_duplicate`), `adapters/inbound/customers.py`,
   `domain/customer.py` (validations d'identité) — s'imprégner des patrons.
2. **Trancher** les questions ouvertes 1 à 6 (verbe HTTP, `metadata`, logique d'unicité, effacement, ADR,
   commande) et consigner la décision dans `backend/README.md` (et ADR-0026 en note de suivi).
3. **Audit** : ajouter `AuditAction.CUSTOMER_UPDATED` à `domain/audit.py` (réutilise
   `ENTITY_TYPE_CUSTOMER`) ; compléter `tests/test_domain_audit.py`.
4. **Port** : ajouter `update(salon_id, customer_id, *, full_name, phone, gender)` au `Protocol`
   `application/ports/customer_repository.py` (docstring : isolation, `CustomerNotFound`,
   `CustomerAlreadyExists` concurrent, effacement, colonnes d'identité uniquement).
5. **Cas d'usage** : ajouter `UpdateCustomer` à `application/customers.py` (valide **avant** écriture ;
   `find_by_id` → `CustomerNotFound` avant audit ; pré-contrôle d'unicité **si le numéro change** ; diff
   neutre `changed` ; `metadata={"changed": changed}`) ; l'ajouter à `__all__`.
6. **Fakes & tests applicatifs** : ajouter `FakeCustomerRepository.update` à `tests/conftest.py` (404
   hors salon ; `CustomerAlreadyExists` si un **autre** fiche du salon porte le nouveau numéro ; sinon
   remplace + bump `updated_at`) ; écrire les cas de `tests/test_customer_usecases.py` (portée, unicité au
   changement, no-op de numéro, effacement, invalides, audit sans PII, `404`).
7. **Adapter sortant** : implémenter `SqlCustomerRepository.update` (filtre `(salon_id, id)`,
   `CustomerNotFound` si absent, filet `IntegrityError` → `_is_phone_duplicate` → `CustomerAlreadyExists`,
   `flush()` sans `commit()`, `refresh()`).
8. **Adapter entrant** : ajouter `UpdateCustomerRequest` (`extra="ignore"`, `full_name` requis) et la
   route (`PATCH …/{customer_id}` recommandé) à `adapters/inbound/customers.py`
   (`require_salon_scope` + `require_permission(CUSTOMER_MANAGE)`, mapping `422`/`404`/`409`) ; importer
   `UpdateCustomer` ; **ne pas** toucher `PUBLIC_ROUTE_PATHS` ni la route note.
9. **Tests API & e2e** : compléter `tests/test_customer_api.py` puis `tests/test_customer_e2e.py`
   (persistance, conflit `409` sans écriture, no-op de numéro, isolation inter-salons, traçabilité sans
   PII, deny-by-default) ; exécuter `pytest` (+ `DATABASE_URL` pour l'e2e) et `ruff check`.
10. **Web — port & gateway** : ajouter `updateProfile` + `UpdateProfileResult` à
    `src/application/ports/customer-gateway.ts` et `src/adapters/api/http-customer-gateway.ts` (mapping
    `409 → duplicate`) (+ test de mapping dans `test/http-customer-gateway.test.ts`).
11. **Web — BFF** : ajouter un export `PATCH` à `app/api/salons/[id]/customers/[customerId]/route.ts`
    (revalidation `validateCustomer` sans `notes`, messages neutres, `PUT` note inchangé) +
    `test/customer-profile-bff.test.ts`.
12. **Web — UI** : créer `src/adapters/ui/customer-profile-form.tsx` (pré-rempli, `PATCH`, `router.refresh()`,
    message d'unicité sur `409`) ; brancher un onglet « Informations » dans
    `app/(gerant)/gerant/clients/[customerId]/page.tsx`.
13. **Documentation** : sections dédiées dans `backend/README.md` et `web-dashboard/README.md` ; phrase de
    statut dans le `README.md` racine ; note de suivi dans ADR-0026.
14. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + **flutter test
    inchangé**), `ruff check`, `npm run lint && npm run build` ; relire la PR pour s'assurer qu'**aucune
    PII et aucun secret** (nom, numéro, jeton) n'apparaissent dans les logs, l'audit
    (`metadata.changed` = noms de champs seulement) ou les messages d'erreur (`409` sans le numéro), que
    la fiche **n'est exposée à aucune route publique/mobile**, et qu'**aucune signature IA** n'a été
    introduite.
