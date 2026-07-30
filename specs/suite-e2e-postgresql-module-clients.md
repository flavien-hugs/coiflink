# Suite e2e PostgreSQL du module clients (`SqlCustomerRepository`)

> Issue GitHub #107 — `tech-debt` / `tests`. Ce document est une **spécification de
> plan** : il décrit quoi livrer et comment, sans implémenter le test.

## Problem Statement

Le module « fiche client » (US-4.x, `SqlCustomerRepository`) est le **seul** adapter
de persistance du backend à ne pas disposer d'une suite e2e PostgreSQL, alors que
`salon`, `appointment`, `user`, `salon_member`, `payment`, `cash_journal` et les
transactions plateforme en possèdent une (sautée sans `DATABASE_URL`, exécutée en CI
avec le service Postgres).

Le code client est couvert par des tests **unitaires** (domaine), des tests de **cas
d'usage** (dépôts *fakes* en mémoire) et des tests **API/BFF** (`app.dependency_overrides`
sur un dépôt en mémoire). Aucun de ces niveaux n'exécute le **chemin SQL réel** :

- le filtre d'isolation `(salon_id, id)` contre une vraie base ;
- l'index unique **partiel** `uq_customer_profiles_salon_phone` et la retraduction
  d'une `IntegrityError` (course concurrente perdue) en `CustomerAlreadyExists` ;
- la jointure + group-by multi-lignes de `list_visits` (historique #29 et stats #31) ;
- la traçabilité `CUSTOMER_NOTE_UPDATED` sans PII écrite en base, l'atomicité
  mutation + audit, le deny-by-default (`401`) et l'isolation inter-salons (`403`) ;
- le round-trip de la migration `0005` (déjà vérifié manuellement, cf. correctif
  `op.f()` post-#28).

Plusieurs specs livrées (#28/#29/#31/#32) annonçaient explicitement
`tests/test_customer_e2e.py` sans jamais le livrer. Le trou s'élargit à chaque
nouvelle fonctionnalité posée sur ce module.

## Goals

- Livrer **`backend/tests/test_customer_e2e.py`**, miroir strict des e2e existants
  (skip propre sans `DATABASE_URL`, plage de téléphones réservée, nettoyage FK avant
  et après chaque test), sans modifier le code de production.
- Couvrir le **chemin SQL réel** de `SqlCustomerRepository` pour :
  - l'isolation par salon en profondeur (même téléphone autorisé dans deux salons ;
    accès inter-salons → `403` générique ; `404` seulement après validation de portée) ;
  - l'unicité `(salon_id, phone)` **garantie en base** sous course concurrente
    (retraduction `IntegrityError` → `CustomerAlreadyExists` → `409`) ;
  - `list_visits` : jointure `appointments` × `appointment_services` × `services`,
    group-by multi-lignes, ordre, refiltrage `salon_id`, fiche walk-in / hors salon
    → historique vide ;
  - la mise à jour de note privée : traçabilité `CUSTOMER_NOTE_UPDATED` **sans PII**,
    atomicité, deny-by-default (`401`) et isolation (`403`/`404`) ;
  - le round-trip `upgrade`/`downgrade` de la migration `0005`.
- Rester **cohérent avec la CI** : le fichier doit s'exécuter dans le même job e2e
  Postgres (aucune modification du workflow n'est attendue au-delà de la découverte
  automatique par `pytest`).

## Non-Goals

- **Aucune modification du code de production** (`SqlCustomerRepository`, adapters
  entrants, cas d'usage, domaine, migration `0005`). Si un vrai défaut est révélé par
  un test, il fait l'objet d'un ticket distinct — ce ticket n'ajoute que des tests.
- Ne pas réécrire ni dédoublonner les suites unitaires / cas d'usage / API existantes
  (`test_domain_customer.py`, `test_customer_usecases.py`, `test_customer_api.py`,
  `test_customer_history_api.py`, `test_customer_stats_api.py`). Elles restent la
  couverture principale ; l'e2e ne couvre **que** ce que les *fakes* ne peuvent pas.
- Ne pas ajouter d'endpoint, de champ de réponse, ni de nouvelle permission.
- Ne pas tester les stats/préférences (#31) au-delà du fait qu'elles réutilisent la
  même brique SQL `list_visits` que l'historique : un scénario stats de bout en bout
  suffit à démontrer le refiltrage salon partagé, sans dupliquer l'agrégation déjà
  couverte par `test_customer_stats_api.py`.

## Relevant Repository Context

**Stack** (déjà figée par ADR — voir `specs/choix-stack-technique-adr.md`) : backend
Python + FastAPI, SQLAlchemy 2.0, PostgreSQL, migrations Alembic, tests `pytest`.
Architecture hexagonale (ports/adapters). Aucune décision de stack n'est ouverte pour
ce ticket.

**Code sous test :**

- `backend/coiflink_api/adapters/outbound/persistence/customer_repository.py` —
  `SqlCustomerRepository` :
  - `create` : `INSERT` + `flush` sans commit ; `IntegrityError` sur
    `uq_customer_profiles_salon_phone` → `rollback` puis `CustomerAlreadyExists`
    (message neutre, **jamais** le numéro) ; toute autre `IntegrityError` remonte
    telle quelle. Détection via `_is_phone_duplicate` (SQLSTATE `23505` + nom de
    contrainte `uq_customer_profiles_salon_phone`).
  - `find_by_id` / `list_for_salon` / `count_for_salon` / `phone_exists` : filtrés
    sur `salon_id`.
  - `update_notes` : `SELECT (salon_id, id)` → `CustomerNotFound` si absent ; écrit
    **seulement** `notes` ; `flush` sans commit ; `refresh` de `updated_at`.
  - `list_visits` : projette `customer_profiles.user_id` filtré `(id, salon_id)` ;
    `user_id IS NULL` (walk-in **ou** hors salon) → `()` ; sinon jointure
    `appointments` (refiltrée `salon_id` + `client_id = user_id` + `status IN …`)
    × `appointment_services` × `services`, tri
    `appointment_date DESC, start_time DESC, id DESC, service created_at ASC, service_id ASC`,
    puis regroupement multi-lignes → `CustomerVisit(services=…, total_amount=…)`.
- `backend/coiflink_api/adapters/inbound/customers.py` — router
  `/salons/{salon_id}/customers` ; toutes les routes déclarent
  `require_permission(CUSTOMER_MANAGE)` **et** `require_salon_scope`. Réponses :
  `201`/`200`/`401`/`403`/`404`/`409`/`422`. `user_id` **jamais** exposé.
- `backend/migrations/versions/0005_customer_gender.py` — colonne `gender` (+ `CHECK`
  `ck_customer_profiles_gender`) et index unique partiel
  `uq_customer_profiles_salon_phone` (`postgresql_where = phone IS NOT NULL`).
- `backend/coiflink_api/domain/audit.py` — `AuditAction.CUSTOMER_CREATED` et
  `CUSTOMER_NOTE_UPDATED` ; entrées **neutres** (`metadata` vide, pas de PII, §11.3/§11.4).

**Patron e2e de référence** (à mirrorer fidèlement) :
`backend/tests/test_cash_discrepancies_e2e.py` — constantes
(`_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()`, `_TEST_JWT_SECRET`,
préfixe téléphone réservé, secret JWT de test local), `_wipe_test_data()` (DELETE dans
l'ordre des FK, borné par le préfixe réservé), fixture `_e2e_client` (skip sans
`DATABASE_URL`, remplace `token_service`/`login_rate_limiter`, wipe avant/après),
helpers API (`_register_manager`, `_register_client`, `_login`, `_create_salon`,
`_create_service`), helpers SQL d'insertion directe (`get_engine()` + `text(...)` +
`conn.commit()`), classe `@pytest.mark.skipif(not _DATABASE_URL, …)`.

**Patron concurrence de référence** :
`backend/tests/test_appointment_concurrency.py` — `ThreadPoolExecutor` +
`threading.Barrier` sur deux `Session` distinctes (`get_sessionmaker`) pour provoquer
une **vraie** course base ; puis vérification qu'exactement une ligne subsiste.

**Conventions de nommage / conventions e2e observées :**

- Skip propre : `if not _DATABASE_URL: pytest.skip(...)` en fixture **et**
  `@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")`
  sur la classe.
- Plage de numéros **réservée et distincte** par fichier e2e. Préfixes déjà pris :
  `+225071999`, `+225072999`, `+225073999`, `+225074997/8/9`, `+225075999`,
  `+225076996/7/8`. Choisir un préfixe **non utilisé**, p. ex. **`+225077998`**
  (numéros locaux `077998xxxx`) — à confirmer comme libre au moment de l'implémentation.
- Toutes les données de test se rattachent à des salons dont le propriétaire porte le
  préfixe réservé ; `_wipe_test_data()` supprime par `owner_id`/`actor_user_id`/`phone LIKE prefix%`.
- Argent en `NUMERIC(12,2)` sérialisé **en chaîne** (`"5000.00"`), jamais de flottant.

## Proposed Implementation

Créer `backend/tests/test_customer_e2e.py` en copiant la charpente de
`test_cash_discrepancies_e2e.py`, adaptée aux fiches clients. Détail par bloc.

### 1. Charpente & fixture

- Constantes : `_DATABASE_URL`, `_TEST_JWT_SECRET` (secret **de test local** dédié,
  jamais de production), préfixe réservé `_E2E_PHONE_PREFIX = "+225077998"` (à
  confirmer libre), numéros locaux dérivés (`_PHONE_A`, `_PHONE_B`, `_PHONE_CLIENT`,
  et un numéro « client fiché » `_CUSTOMER_PHONE` pour l'unicité), `_PASSWORD`,
  noms de salons `_SALON_NAME_A`/`_B`.
- `_wipe_test_data()` : DELETE dans l'ordre des FK, borné par le préfixe. Ordre
  suggéré : `audit_logs` (par `salon_id` **et** par `actor_user_id`) →
  `appointment_services` → `appointments` → `customer_profiles` → `services` →
  `salon_members` (par `salon_id` **et** `user_id`) → `salons` → `users`. Vérifier
  l'ordre réel des contraintes FK au moment de l'implémentation (miroir du wipe de
  `test_cash_discrepancies_e2e.py`, en ajoutant `customer_profiles`).
- Fixture `_e2e_client` : skip sans `DATABASE_URL` ; remplace
  `main_app.state.token_service` par un `JwtTokenService(_TEST_JWT_SECRET, …)` et
  `login_rate_limiter` par un `InMemoryLoginRateLimiter(...)` ; wipe avant/après ;
  restaure les états d'origine.

### 2. Helpers API (réutilisés des e2e existants)

`_register_manager(phone)`, `_register_client(phone, full_name)`, `_login(phone)`,
`_create_salon(token, name)`, `_create_service(token, salon_id, name, price)`, et des
wrappers HTTP fiches : `_create_customer(token, salon_id, **body)` (POST),
`_update_note(token, salon_id, customer_id, notes)` (PUT),
`_get_history(token, salon_id, customer_id)` (GET `.../appointments`),
`_get_stats(token, salon_id, customer_id)` (GET `.../stats`).

### 3. Helpers SQL d'insertion directe (bypass des gardes HTTP)

L'API ne crée que des fiches **walk-in** (`user_id = NULL`) et n'expose pas
`appointments` terminés à volonté. Pour exercer `list_visits`, insérer / mettre à jour
directement en base :

- `_link_customer_to_user(customer_id, user_id)` : `UPDATE customer_profiles SET user_id = :uid`
  — **indispensable** pour que `list_visits` retourne des visites (sinon `user_id IS NULL`
  → tuple vide). Le `user_id` doit être celui d'un **client enregistré** (FK
  `customer_profiles.user_id → users.id` et cohérence avec `appointments.client_id`).
- `_insert_appointment(salon_id, client_id, date, start, end, status)` et
  `_insert_appointment_service(salon_id, appointment_id, service_id, price)` — repris
  tels quels de `test_cash_discrepancies_e2e.py` (colonne `slot` générée : ne pas
  l'insérer).
- `_fetch_audit_rows(salon_id, action)` : `SELECT` sur `audit_logs` filtré
  `(salon_id, action)` retournant `actor_user_id`, `entity_type`, `entity_id`,
  `metadata`, `created_at` — pour assertions de traçabilité **sans PII**.

### 4. Classe de tests `TestCustomerE2E` (`@pytest.mark.skipif`)

Scénarios minimaux (regrouper par thème) :

**A. Isolation par salon en profondeur (§11.2, ADR-0026)**

1. **Même téléphone autorisé dans deux salons** : gérant A crée une fiche
   `phone = _CUSTOMER_PHONE` dans salon A ; gérant B crée une fiche **même téléphone**
   dans salon B → **les deux `201`** (l'index partiel est `(salon_id, phone)`, pas
   global).
2. **Doublon dans le même salon** : deuxième POST même `(salon_id, phone)` → `409`
   `CustomerAlreadyExists`, message neutre **sans** le numéro.
3. **Lecture inter-salons** : gérant A tente `GET .../customers/{id_du_salon_B}` sur
   **son** salon A → `404` (fiche hors salon indiscernable d'inexistante, filtre
   `(salon_id, id)` du dépôt). Avec le `salon_id` du salon B dans le chemin →
   `403` générique (portée refusée **avant** tout accès fiche).
4. **`401`** : `GET .../customers` sans jeton → `401` (deny-by-default, ADR-0015).

**B. Unicité du téléphone garantie en base — course concurrente**

5. Deux insertions concurrentes de la même `(salon_id, phone)` via **deux `Session`
   distinctes** (`get_sessionmaker`) et `SqlCustomerRepository.create`, alignées sur un
   `threading.Barrier` (patron `test_appointment_concurrency.py`) → exactement **1**
   succès et **1** `CustomerAlreadyExists` ; vérifier ensuite qu'**une seule** ligne
   `customer_profiles` porte ce `(salon_id, phone)`. (Variante HTTP possible : deux
   `POST` concurrents → exactement un `201` et un `409` ; conserver au moins la
   version dépôt qui exerce directement la retraduction `IntegrityError`.)
6. (Optionnel, si aisé) vérifier que le message d'erreur / les logs **ne contiennent
   pas** le numéro soumis.

**C. `list_visits` — jointure + group-by multi-lignes (historique #29)**

7. Fiche **liée** (`_link_customer_to_user`) avec plusieurs RDV `COMPLETED`
   multi-prestations : `GET .../appointments` renvoie les visites **groupées** par
   RDV (une entrée par RDV, `services` = plusieurs lignes), `total_amount` = somme des
   `price_at_booking`, **ordre récent d'abord** (`date DESC, start_time DESC`), et
   ordre stable des prestations dans une visite.
8. **Refiltrage salon** : un RDV du **même compte client** dans un **autre salon**
   n'apparaît **jamais** dans l'historique du salon A (jointure refiltrée `salon_id`).
9. **Fiche walk-in** (`user_id = NULL`) → `items: []`, `total_visits: 0`,
   `last_visit_at: null`, `total_amount: "0"` — comportement normal, pas d'erreur, et
   **aucun** oracle sur l'existence d'un compte.
10. **Statuts non terminés** (`PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW`) exclus de
    l'historique (seuls les `COMPLETED` comptent — aligné sur la logique #29).
11. **Stats partagent la brique** : un `GET .../stats` sur la même fiche liée renvoie
    un classement cohérent avec l'historique (mêmes visites, refiltrage salon), sans
    exposer `user_id`/`client_id` — un seul scénario pour démontrer le partage `list_visits`.

**D. Mise à jour de note privée (#32)**

12. **Persistance & replace** : PUT note « A » puis PUT note « B » → la fiche renvoie
    « B » ; PUT `null`/vide → `notes = NULL` (effacement). Vérifier en base que seule
    la colonne `notes` a changé (nom/téléphone/genre inchangés) et `updated_at` régénéré.
13. **Traçabilité sans PII** : après un PUT réussi, `audit_logs` contient **une** ligne
    `CUSTOMER_NOTE_UPDATED` avec le bon `actor_user_id` (le gérant), `salon_id`,
    `entity_type = customer`, `entity_id = customer_id`, et **`metadata` vide** — la
    note (potentiellement données de santé) **n'apparaît nulle part** dans la ligne
    d'audit. Assertion explicite : le texte de la note n'est présent dans **aucune**
    colonne d'`audit_logs`.
14. **Atomicité** : mutation + audit committés ensemble (une fiche mise à jour ⇒
    exactement une entrée d'audit correspondante).
15. **Isolation / deny-by-default** : PUT sur une fiche d'un autre salon → `404`
    **après** portée (ou `403` si le `salon_id` du chemin est hors périmètre du
    gérant) ; PUT sans jeton → `401` **et aucune** entrée d'audit / aucune mutation.

**E. Round-trip de la migration `0005`**

16. Exercer `upgrade`/`downgrade`/`upgrade` de la révision `0005` contre la vraie base
    (patron : Alembic `command.downgrade`/`command.upgrade` en programmatique, ou
    `op`-round-trip équivalent) et vérifier qu'aucune erreur `op.f()` /
    double-préfixage ne survient et que l'index partiel + le `CHECK` réapparaissent.
    Si aucun helper de round-trip Alembic n'existe déjà dans les tests, isoler ce
    scénario dans son propre test (marqué skip sans `DATABASE_URL`) et **restaurer
    `head`** en fin de test pour ne pas laisser la base migrée à l'envers pour les
    autres tests du job. **Décision à confirmer** : mécanisme exact du round-trip (API
    Alembic programmatique vs. sous-processus) — voir Open Questions.

## Affected Files / Packages / Modules

**À créer :**

- `backend/tests/test_customer_e2e.py` — la suite e2e (seul livrable de code).

**À lire (référence, non modifiés) :**

- `backend/tests/test_cash_discrepancies_e2e.py` (charpente e2e à mirrorer).
- `backend/tests/test_appointment_concurrency.py` (patron de course base).
- `backend/coiflink_api/adapters/outbound/persistence/customer_repository.py`.
- `backend/coiflink_api/adapters/inbound/customers.py`.
- `backend/coiflink_api/adapters/outbound/persistence/session.py`
  (`get_engine`, `get_sessionmaker`).
- `backend/coiflink_api/adapters/outbound/persistence/models.py`
  (`CustomerProfile`, `Appointment`, `AppointmentService`, `Service`, colonnes exactes).
- `backend/coiflink_api/domain/audit.py` (`CUSTOMER_NOTE_UPDATED`, `entity_type`).
- `backend/migrations/versions/0005_customer_gender.py` et `migrations/env.py`
  (convention de nommage, round-trip).
- `backend/tests/conftest.py` (fixtures et gestion `DATABASE_URL`).
- Specs de référence : `specs/creation-fiche-client-gerant.md`,
  `specs/historique-visites-client-gerant.md`,
  `specs/prestations-preferees-client-stats.md`, `specs/note-client-privee-gerant.md`,
  `specs/plan-tests-configuration-test-gate.md`.
- `docs/adr/0026-fiche-client-portee-salon.md` (anti-oracle, isolation).

## API / Interface Changes

None. Ce ticket n'ajoute que des tests ; aucun endpoint, schéma de réponse, option CLI
ni permission n'est modifié.

## Data Model / Protocol Changes

None. Aucune migration ni changement de schéma. Le test de round-trip `0005` exécute
des migrations **existantes** contre une base de test jetable et restaure `head` ;
il ne modifie pas le schéma versionné.

## Security & Privacy Considerations

- **Pas de PII au journal (§11.3/§11.4, ADR-0019).** Le test de traçabilité doit
  **affirmer** l'absence de la note (et de tout nom/téléphone) dans `audit_logs`
  (`metadata` vide, aucune colonne ne porte le texte de la note). C'est l'invariant
  central du #32.
- **Pas de secret en clair.** Utiliser un `_TEST_JWT_SECRET` **dédié au test local**,
  documenté comme tel, jamais un secret de production. Ne rien logguer de sensible.
- **Isolation §11.2 / anti-oracle (ADR-0026).** Les assertions doivent confirmer que
  l'accès inter-salons renvoie un `403` **générique** (portée) et que le `404` (fiche
  hors salon) n'arrive **qu'après** validation de portée — jamais un oracle sur
  l'existence d'une fiche ou d'un compte. `user_id`/`client_id` ne doivent **jamais**
  apparaître dans les réponses HTTP inspectées.
- **Deny-by-default (ADR-0015).** Toute route sans jeton → `401`, et aucune mutation /
  aucun audit ne doit en résulter.
- **Données de test cloisonnées.** Plage de téléphones réservée + wipe avant/après pour
  ne jamais toucher de données réelles ; toutes rattachées au préfixe réservé.

## Testing Plan

Le livrable **est** un test. Portée :

- **e2e (PostgreSQL réel, sauté sans `DATABASE_URL`)** — nouveau
  `tests/test_customer_e2e.py`, scénarios A–E ci-dessus. Exécution :

  ```
  cd backend
  DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
  DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_customer_e2e.py -v
  ```

- **Non-régression** : la suite complète doit rester verte **sans** `DATABASE_URL`
  (le fichier skippe proprement) et **avec** (`pytest -q` en CI Postgres). Vérifier que
  le nettoyage laisse la base propre et que le test de round-trip `0005` restaure
  `head` (aucun effet de bord sur les autres fichiers e2e du job).
- **Lint/format** : respecter le style du dépôt (imports triés, `ruff`/formatteur du
  projet), docstrings de module et de classe dans le ton des e2e existants (français,
  références aux US / § / ADR).

## Documentation Updates

- **Aucune doc produit/README/ADR fonctionnelle à changer** : le comportement testé
  existe déjà. Optionnel : mettre à jour la case « e2e livré » dans les specs qui la
  mentionnaient (#28/#29/#31/#32) si le dépôt suit ce suivi — sinon s'abstenir.
- La docstring de module de `test_customer_e2e.py` sert de documentation locale
  (prérequis `DATABASE_URL`, plage réservée, ce qui est couvert vs. couvert ailleurs).

## Risks and Open Questions

- **Mécanisme du round-trip `0005` (à confirmer).** Aucune suite e2e existante ne fait
  de round-trip Alembic. Options : (a) API programmatique `alembic.command`
  down/up avec un `Config` pointant `DATABASE_URL` ; (b) helper `op`-level ; (c)
  scénario minimal vérifiant seulement la présence/re-création de l'index partiel et du
  `CHECK`. **Risque** : laisser la base à une révision inférieure pour les autres tests
  du job → impérativement restaurer `head` en `finally`, ou isoler sur une base dédiée.
  Choisir l'option la plus simple qui ne perturbe pas les autres tests.
- **`list_visits` exige `user_id` non nul.** L'API ne crée que des fiches walk-in : le
  lien fiche→compte doit être posé **directement en base** (`_link_customer_to_user`).
  Vérifier les contraintes réelles (`uq_customer_profiles_salon_user`, FK
  `user_id → users.id`) et l'existence d'un `users.id` valide (client enregistré) pour
  ne pas violer une autre contrainte.
- **Provocation d'une vraie course base.** La retraduction `IntegrityError` →
  `CustomerAlreadyExists` n'est fiable que sous parallélisme réel (deux connexions).
  Réutiliser strictement le patron `ThreadPoolExecutor` + `Barrier` de
  `test_appointment_concurrency.py` ; sinon le pré-contrôle `phone_exists` masquerait la
  course et le test ne couvrirait pas le chemin `IntegrityError`.
- **Préfixe téléphone réservé.** `+225077998` proposé comme libre ; **confirmer** qu'il
  ne collisionne avec aucun autre fichier e2e au moment de l'implémentation (les
  préfixes utilisés évoluent).
- **Ordre du wipe FK.** Vérifier l'ordre exact des contraintes (`customer_profiles`
  référencée par rien de critique ici, mais `appointments.client_id → users`,
  `appointment_services → appointments/services/salons`) pour éviter les erreurs de FK
  au nettoyage.
- **Aucun défaut attendu.** Si un test échoue en révélant un vrai bug du code de
  production, **ne pas** corriger le code dans ce ticket : ouvrir un ticket dédié et
  documenter (le périmètre est « tests uniquement »).

## Implementation Checklist

1. Lire `test_cash_discrepancies_e2e.py`, `test_appointment_concurrency.py`,
   `customer_repository.py`, `customers.py`, `models.py`, `audit.py`, `session.py`,
   `0005_customer_gender.py`, `env.py` et `conftest.py`.
2. Confirmer un préfixe de téléphone réservé **libre** (proposition `+225077998`) et
   l'ordre des contraintes FK pour le wipe.
3. Créer `backend/tests/test_customer_e2e.py` avec la docstring de module (prérequis
   `DATABASE_URL`, plage réservée, périmètre de couverture).
4. Implémenter constantes + `_wipe_test_data()` (inclure `customer_profiles` et
   l'audit par `actor_user_id`) + fixture `_e2e_client` (skip sans `DATABASE_URL`,
   override `token_service`/`login_rate_limiter`, wipe avant/après).
5. Ajouter les helpers API (`_register_manager/_register_client/_login/_create_salon/
   _create_service/_create_customer/_update_note/_get_history/_get_stats`).
6. Ajouter les helpers SQL (`_link_customer_to_user`, `_insert_appointment`,
   `_insert_appointment_service`, `_fetch_audit_rows`).
7. Écrire les tests du bloc **A** (isolation : même téléphone 2 salons `201`/`201`,
   doublon même salon `409`, lecture inter-salon `404`/`403`, `401`).
8. Écrire le test du bloc **B** (course concurrente → 1 succès + 1
   `CustomerAlreadyExists`, une seule ligne subsiste ; pas de numéro dans l'erreur).
9. Écrire les tests du bloc **C** (`list_visits` : group-by multi-lignes, ordre,
   refiltrage salon, walk-in vide, statuts non terminés exclus, stats partagent la brique).
10. Écrire les tests du bloc **D** (note : replace/effacement, seule `notes` change,
    audit `CUSTOMER_NOTE_UPDATED` sans PII, atomicité, `403`/`404`/`401` sans mutation
    ni audit).
11. Écrire le test du bloc **E** (round-trip `0005`, avec restauration de `head` en
    `finally`).
12. Exécuter localement **sans** `DATABASE_URL` (tout skippe proprement), puis **avec**
    (`alembic upgrade head` puis `pytest tests/test_customer_e2e.py -v`).
13. Lancer la suite complète (`pytest -q`) pour confirmer l'absence de régression et de
    fuite de données de test ; lint/format selon le style du dépôt.
14. Ne modifier **aucun** fichier de production ; si un vrai défaut est révélé, le
    consigner pour un ticket distinct.
