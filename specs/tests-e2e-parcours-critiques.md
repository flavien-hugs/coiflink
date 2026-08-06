# Tests e2e des parcours critiques (réservation, gestion RDV gérant, encaissement)

> Issue GitHub **#50** — labels `tests` · priorité **Must** · effort **L** · §5 / §18 Sprint 6 (M6).
> Ce document est une **spécification de plan** : il décrit **quoi** livrer et **comment**, sans
> écrire les tests. Aucune modification de code de production n'est prévue.

## Problem Statement

Le PRD (§5) décrit **trois parcours critiques de bout en bout** qui constituent le cœur du produit :

- **§5.1 — Réservation client** : ouverture de l'app → compte/connexion → recherche d'un salon →
  consultation des prestations → choix d'une prestation → choix date/heure → confirmation →
  notification de confirmation → rappel → visite → confirmation « prestation réalisée » par le salon →
  passage du RDV dans l'historique client.
- **§5.2 — Gestion d'un RDV côté gérant** : connexion web → planning du jour → statuts (confirmés /
  en attente / annulés / terminés) → assignation éventuelle d'un coiffeur → confirmation de l'arrivée
  → « prestation réalisée » → enregistrement du paiement → mise à jour du chiffre d'affaires →
  archivage dans l'historique client.
- **§5.3 — Encaissement** : fin de prestation → sélection du RDV → choix du mode de paiement → saisie
  du montant → vérification de cohérence montant ↔ prestation → enregistrement du paiement → ajout au
  journal de caisse → mise à jour du tableau de bord → reçu généré/récupérable par le client.

Chacune des briques individuelles de ces parcours est aujourd'hui **livrée et testée séparément**
(M3 réservation/statuts/planning, M4 clients/encaissement/journal de caisse, M5 tableau de
bord/notifications) et chaque adaptateur SQL dispose d'une suite e2e PostgreSQL par fonctionnalité
(`test_appointment_notification_e2e.py`, `test_payments_e2e.py`, `test_customer_e2e.py`,
`test_daily_summary_e2e.py`, `test_hairdresser_planning_e2e.py`, `test_receipts_e2e.py`, …).

**Le trou** : aucune suite ne stitche ces briques en **un seul parcours continu** partagé (le même
salon, le même client, le même RDV) traversant réservation → cycle de statuts gérant → encaissement →
dashboard → historique/reçu. Une régression d'**intégration entre modules** (p. ex. un RDV `COMPLETED`
qui n'apparaît pas dans l'historique client, un paiement qui ne fait pas monter le CA du dashboard, un
reçu introuvable après encaissement) passerait aujourd'hui **entre les mailles** des suites
par-fonctionnalité. La `docs/strategie-de-tests.md` (issue #6) **positionne** explicitement ces tests
comme le périmètre de #50 (« #50 les câble », colonne *e2e* du tableau « quoi tourne où ») mais les
laisse **à livrer**.

Le critère d'acceptation de #50 est double : (1) **suite e2e verte sur les parcours Must** ; (2)
**intégrée à la CI (#4)**.

## Goals

- Livrer une **suite e2e de parcours** (backend, pile HTTP réelle) couvrant de bout en bout les trois
  parcours Must du §5, chaque parcours enchaînant les endpoints réels dans l'ordre du PRD sur des
  entités **partagées** (un salon, un client, un RDV), contre une **vraie base PostgreSQL** :
  - **§5.1 Réservation client** : inscription/connexion client → `GET /catalog/salons` (recherche) →
    `GET /catalog/salons/{id}` (fiche + prestations) → `GET /catalog/salons/{id}/availability`
    (créneaux) → `POST /salons/{id}/appointments` (RDV `PENDING`) → assertions notification de
    confirmation + rappels persistés (#45/#46) → transition gérant `→ COMPLETED` →
    `GET /appointments/history` montre le RDV terminé.
  - **§5.2 Gestion RDV gérant** : connexion gérant → `GET /salons/{id}/appointments/daily-summary`
    (planning/décompte du jour) → `PUT /salons/{id}/appointments/{rdv}/hairdresser` (assignation) →
    `POST /salons/{id}/appointments/{rdv}/status` `CONFIRMED` (arrivée) → `…/status` `COMPLETED`
    (réalisée) → `POST /salons/{id}/payments` (encaissement) → `GET /salons/{id}/revenue/summary`
    (CA mis à jour) → RDV présent dans l'historique client.
  - **§5.3 Encaissement** : depuis un RDV `COMPLETED`, `POST /salons/{id}/payments` avec mode et
    montant → **vérification de cohérence** montant ↔ prestation (égalité stricte ; écart → `422` sans
    écriture) → une ligne `PAYMENT` au **journal de caisse** → `GET /salons/{id}/payments`
    (historique/transactions) et `GET /salons/{id}/revenue/summary` (dashboard) cohérents →
    `GET /me/receipts` + `GET /me/receipts/{payment_id}` (reçu récupérable par le client).
- **Intégrer la suite à la CI (#4)** de façon que sa réussite soit une **condition de merge**, en
  restant cohérent avec le mécanisme d'exécution e2e déjà en place (job `backend` de `ci.yml` avec
  `DATABASE_URL` défini au niveau du job + service `postgres:16`, `alembic upgrade head` avant
  `pytest`). Cf. décision ouverte 2 (job dédié vs découverte par le `pytest` existant).
- **Mirrorer fidèlement le patron e2e existant** (skip propre sans `DATABASE_URL`, plage de téléphones
  réservée et distincte, nettoyage FK-safe avant/après chaque test, JWT réel de test, argent en chaîne
  `NUMERIC(12,2)`), **sans modifier le code de production**.
- Mettre à jour `docs/strategie-de-tests.md` pour refléter que #50 est **livré** (e2e des parcours
  Must câblés en CI) plutôt que « à venir ».

## Non-Goals

- **Aucune modification du code de production** (routers, cas d'usage, domaine, dépôts SQL, migrations).
  Si un parcours révèle un **vrai défaut d'intégration**, il fait l'objet d'un **ticket distinct** ; ce
  ticket n'ajoute que des tests (et, au plus, du câblage CI + doc).
- **Ne pas dédoublonner** les suites e2e par-fonctionnalité existantes ni les suites
  unitaire/usecase/API. Les parcours ne re-testent pas chaque branche d'erreur d'un endpoint (déjà
  couverte) ; ils vérifient la **continuité inter-modules** (les données produites par une étape sont
  bien consommées par la suivante) et **un** chemin d'erreur structurant par parcours (p. ex. montant
  incohérent au §5.3).
- **Pas de tests e2e d'IU** (Playwright web / `integration_test` Flutter) dans ce ticket : aucune infra
  de ce type n'existe (pas de dépendance Playwright dans `web-dashboard/package.json`, pas de dossier
  `app-mobile/integration_test/`), et la CI n'orchestre pas d'app web/mobile contre un backend vivant.
  Le parcours est exercé au **niveau HTTP du backend** (contrat que consomment web/mobile), cohérent
  avec 100 % des `*_e2e.py` existants. L'e2e d'IU est une extension possible **hors périmètre** (cf.
  décision ouverte 1).
- **Pas de nouveaux endpoints, champs de réponse, permissions, ni migrations.**
- **Pas de tests de sécurité/authz exhaustifs** (RBAC négatif, isolation inter-salons, brute-force,
  journalisation des accès sensibles) : c'est le périmètre distinct de **#51**. Les parcours vérifient
  le chemin **nominal autorisé** ; un seul contrôle deny-by-default (`401` sans jeton) peut être inclus
  par parcours à titre de garde-fou, sans dupliquer #51.
- **Pas de tests de performance/charge** : périmètre de **#52** (budgets §12.1).

## Relevant Repository Context

**Stack (figée par ADR — voir `specs/choix-stack-technique-adr.md`)** : backend Python 3.12 + FastAPI,
SQLAlchemy 2.0, PostgreSQL 16, migrations Alembic, tests `pytest`. Architecture hexagonale
(ports/adapters, ADR-0008). **Aucune décision de stack n'est ouverte** pour le backend. Une décision
**reste ouverte** uniquement si l'on veut étendre l'e2e à l'IU (framework d'e2e web/mobile — non retenu
ici, cf. décision ouverte 1).

**Où vivent les tests e2e** : `backend/tests/test_*_e2e.py`. Configuration `pytest` :
`backend/pyproject.toml` → `[tool.pytest.ini_options] testpaths = ["tests"]`. **Aucun marqueur `e2e`
enregistré** : la convention de sélection e2e est **le nom de fichier** (`*_e2e.py`) **+** un
`@pytest.mark.skipif(not _DATABASE_URL, …)` sur la classe et un `pytest.skip(...)` en fixture.

**Patron e2e de référence à mirrorer** (le plus proche d'un parcours multi-acteurs) :
`backend/tests/test_appointment_notification_e2e.py` — constantes
(`_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()`, `_TEST_JWT_SECRET` local factice,
`_E2E_PHONE_PREFIX` réservé), `_wipe_test_data()` (DELETE FK-safe borné par le préfixe réservé),
fixture `_e2e_client` (skip sans `DATABASE_URL`, remplace `token_service`/`login_rate_limiter`, wipe
avant/après), `_Fixture` (gérant + coiffeur + deux clients), helpers HTTP (`_register`, `_login`,
`_book`, `_cancel`, `_set_status`, `_modify`) et helpers SQL de lecture directe
(`get_engine()`/`get_sessionmaker()` + `text(...)`). Autres références utiles : `test_payments_e2e.py`
(encaissement + journal de caisse + historique transactions), `test_receipts_e2e.py` (reçu client),
`test_daily_summary_e2e.py` (décompte du jour), `test_hairdresser_planning_e2e.py` (assignation
coiffeur).

**Endpoints réels des parcours** (tous montés dans `backend/coiflink_api/main.py`) :

| Étape PRD | Méthode + route | Acteur / permission | Livré par |
| --- | --- | --- | --- |
| Inscription client | `POST /auth/register` | public | M1 |
| Inscription gérant | `POST /auth/register/manager` | public | M1 |
| Connexion | `POST /auth/login` | public → JWT | #10 |
| Créer un coiffeur | `POST /salons/{salon_id}/employees` | gérant | #13 |
| Recherche/liste salons | `GET /catalog/salons` | public | #18 |
| Fiche salon (+prestations, horaires) | `GET /catalog/salons/{salon_id}` | public | #19 |
| Disponibilités | `GET /catalog/salons/{salon_id}/availability` | public | #21 |
| Réserver (RDV `PENDING`) | `POST /salons/{salon_id}/appointments` | client `APPOINTMENT_BOOK` | #21 |
| Modifier un RDV | `PATCH /appointments/{appointment_id}` | client | #23 |
| Annuler un RDV | `POST /appointments/{appointment_id}/cancellation` | client | #24 |
| Cycle de statuts (gérant) | `POST /salons/{salon_id}/appointments/{id}/status` | gérant `APPOINTMENT_MANAGE` | #25 |
| Assigner un coiffeur | `PUT /salons/{salon_id}/appointments/{id}/hairdresser` | gérant `APPOINTMENT_MANAGE` | #25 |
| Décompte RDV du jour | `GET /salons/{salon_id}/appointments/daily-summary` | gérant `STATS_READ_SALON` | #39 |
| Historique client | `GET /appointments/history` | client `APPOINTMENT_READ_OWN` | #30 |
| Enregistrer un paiement | `POST /salons/{salon_id}/payments` | gérant `PAYMENT_RECORD` | #33 |
| Historique transactions | `GET /salons/{salon_id}/payments` | gérant `CASH_JOURNAL_READ` | #35 |
| CA jour/semaine/mois | `GET /salons/{salon_id}/revenue/summary` | gérant `STATS_READ_SALON` | #40 |
| Reçus du client | `GET /me/receipts`, `GET /me/receipts/{payment_id}` | client `PAYMENT_READ_OWN` | #38 |

**Invariants métier structurants exercés par les parcours (déjà livrés)** :

- **§8.3** : un salon **sans horaire valide n'est pas réservable** (`is_bookable=false`) — le fixture
  doit poser des horaires (`PUT /salons/{id}/opening-hours`, #16) et ≥ 1 prestation active (#17) pour
  que le salon apparaisse au catalogue **et** offre des créneaux.
- **Anti double-réservation (#21)** : garantie par une contrainte d'exclusion PostgreSQL — non retestée
  ici en profondeur (couverte par `test_appointment_concurrency.py`), mais le parcours réserve un
  créneau **libre** issu de `availability`.
- **§8.2 encaissement (#33)** : le montant du paiement doit être **strictement égal** à la somme des
  `price_at_booking` du RDV (ou au `Service.price`) ; tout écart → `422` **sans écriture** (ni
  `payments`, ni `cash_journal`, ni `audit_logs`).
- **Journal de caisse (#34)** : chaque paiement `VALIDATED` inscrit une ligne `PAYMENT` ; le CA (#40)
  dérive du **net signé** des lignes `cash_journal` (une correction le fait baisser).
- **Historique client (#30/#29)** : seul un RDV **`COMPLETED`** entre dans l'historique — d'où
  l'enchaînement `PENDING → CONFIRMED → COMPLETED` avant l'assertion d'historique.
- **Notifications (#45/#46/#47/#48)** : la réservation **émet/trace** (sans envoyer, `sent_at=NULL`)
  une confirmation + des rappels + une notification salon ; le parcours §5.1 peut asserter leur
  **présence** en base (étapes PRD 8–9), sans dupliquer la couverture fine de
  `test_appointment_notification_e2e.py`.
- **Reçu (#38)** : **généré/récupérable dès l'enregistrement** du paiement (aucune remise proactive —
  ADR-0030) ; étape PRD §5.3.9 « reçu généré » (le « ou envoyé » reste différé M5+).

**Fuseau** : `Africa/Abidjan` (UTC+0). Les créneaux passés sont exclus ; le fixture réserve un créneau
**futur** (patron `_next_monday()` observé dans les e2e existants) pour rester déterministe.

**Argent** : `NUMERIC(12,2)` sérialisé **en chaîne** (`"5000.00"`), jamais de flottant.

**Contraintes de nettoyage (mémoire projet)** : depuis #45, une réservation écrit dans `notifications`
avec des FK **RESTRICT** ; `_wipe_test_data()` doit **supprimer `notifications` (et `campaigns` le cas
échéant) AVANT `appointments`/`payments`/`cash_journal`/`users`/`salons`**, sinon le DELETE viole une
FK. L'ordre FK-safe complet est déjà matérialisé dans `test_appointment_notification_e2e.py` et
`test_payments_e2e.py` — le réutiliser tel quel.

**Base e2e locale (mémoire projet)** : lancer contre `coiflink-e2e-pg` sur le **port 55433**
(`coif`/`pw`/`coif`) ; `ruff format` n'est pas imposé (la CI exécute `ruff check` seulement).

## Proposed Implementation

Approche recommandée : **un (ou trois) fichier(s) e2e backend de parcours**, au niveau HTTP
(`TestClient` → routers → cas d'usage → dépôts SQL réels → PostgreSQL), miroir strict du patron
existant. Recommandation : **un seul fichier** `backend/tests/test_critical_journeys_e2e.py`
regroupant trois classes (une par parcours) partageant un module de fixtures — cela maximise la
réutilisation d'un même salon/gérant/coiffeur et minimise le coût d'installation. (Alternative : trois
fichiers `test_journey_booking_e2e.py` / `test_journey_manager_e2e.py` / `test_journey_checkout_e2e.py`
— à trancher, décision ouverte 3.)

### Squelette (miroir du patron)

```python
# backend/tests/test_critical_journeys_e2e.py
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from coiflink_api.adapters.outbound.persistence.session import get_engine, get_sessionmaker
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import InMemoryLoginRateLimiter
from coiflink_api.main import app as main_app

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_TEST_JWT_SECRET = "test-only-journeys-e2e-jwt-secret-not-for-production"
_E2E_PHONE_PREFIX = "+225068999"   # ← plage RÉSERVÉE, à confirmer libre (voir ci-dessous)

def _wipe_test_data() -> None:
    # DELETE FK-safe borné par le préfixe réservé, dans l'ordre :
    #   notifications → campaigns → cash_journal → payments →
    #   appointment_services → appointments → audit_logs →
    #   customer_profiles → services → opening_hours → salon_members →
    #   salon_photos → salons → users
    ...

@pytest.fixture()
def _e2e_client():
    if not _DATABASE_URL:
        pytest.skip("PostgreSQL requis — définissez DATABASE_URL.")
    main_app.dependency_overrides[...] = lambda: JwtTokenService(_TEST_JWT_SECRET)
    main_app.dependency_overrides[...] = lambda: InMemoryLoginRateLimiter()
    _wipe_test_data()
    with TestClient(main_app) as client:
        yield client
    _wipe_test_data()
    main_app.dependency_overrides.clear()

@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestBookingJourneyE2E: ...
@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestManagerAppointmentJourneyE2E: ...
@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestCheckoutJourneyE2E: ...
```

### Fixture partagée (installation d'un salon réservable)

Un helper (patron `_Fixture`) qui, via **les endpoints réels** (jamais d'INSERT brut pour les entités
qui ont un endpoint) :

1. inscrit un **gérant** (`POST /auth/register/manager`) et se connecte ;
2. crée un **salon** (`POST /salons`), pose des **horaires valides** (`PUT /salons/{id}/opening-hours`)
   → salon `is_bookable=true` (§8.3), et une **prestation active** (`POST /salons/{id}/services`,
   durée + prix) ;
3. crée un **coiffeur** (`POST /salons/{id}/employees`) pour l'étape d'assignation §5.2 ;
4. inscrit un **client** (`POST /auth/register`) et se connecte.

Réutiliser les helpers déjà présents dans les e2e voisins (`_register`, `_login`, `_create_salon`,
`_create_service`, `_set_opening_hours`) — les copier/adapter dans le fichier, comme le font les autres
suites (pas de dépendance partagée entre fichiers e2e).

### Parcours §5.1 — Réservation client (`TestBookingJourneyE2E`)

1. Client connecté → `GET /catalog/salons` retourne le salon de test (**ACTIVE**, projection vitrine).
2. `GET /catalog/salons/{id}` → fiche avec la prestation active (prix/durée) et `is_bookable=true`.
3. `GET /catalog/salons/{id}/availability?date=<lundi futur>` → au moins un créneau libre ; en prendre
   un.
4. `POST /salons/{id}/appointments` (prestation + créneau) → `201`, `status=PENDING`, `id` retourné.
5. **Assertions notification (étapes PRD 8–9)** : lecture SQL directe de `notifications` filtrée sur
   l'`appointment_id` → **une** `CONFIRMATION` `PENDING` `sent_at IS NULL` + des `REMINDER` `PENDING`
   (présence, pas de re-vérification exhaustive — déléguée à `test_appointment_notification_e2e.py`).
6. **Transition salon → réalisée (étapes PRD 10–11)** : gérant `POST …/status` `CONFIRMED` puis
   `COMPLETED`.
7. **Historique (étape PRD 12)** : `GET /appointments/history` (jeton **client**) contient le RDV avec
   la prestation et le montant figé (`price_at_booking`, FCFA).
8. Garde-fou deny-by-default : `POST /salons/{id}/appointments` **sans jeton** → `401` (un seul cas,
   pas de matrice authz — c'est #51).

### Parcours §5.2 — Gestion RDV gérant (`TestManagerAppointmentJourneyE2E`)

À partir d'un RDV `PENDING` réservé par le client (réutilise la fixture) :

1. Gérant connecté → `GET /salons/{id}/appointments/daily-summary?date=<jour du RDV>` → décompte
   cohérent (le RDV apparaît dans `by_status["PENDING"]`).
2. `PUT /salons/{id}/appointments/{rdv}/hairdresser` (assigne le coiffeur créé) → `200`, `hairdresser_id`
   posé.
3. `POST …/status` `CONFIRMED` (arrivée) → `200` ; `daily-summary` reflète `CONFIRMED`.
4. `POST …/status` `COMPLETED` (réalisée) → `200`.
5. `POST /salons/{id}/payments` (encaissement du RDV, montant = prix de la prestation) → `201`
   `VALIDATED`.
6. **CA mis à jour (étape PRD 8)** : `GET /salons/{id}/revenue/summary?reference_date=<jour>` → le CA
   du jour a **augmenté** du montant encaissé (comparer avant/après, ou attendre exactement le montant
   sur une base fraîchement nettoyée).
7. **Archivage (étape PRD 9)** : `GET /appointments/history` (client) contient le RDV terminé.

### Parcours §5.3 — Encaissement (`TestCheckoutJourneyE2E`)

À partir d'un RDV `COMPLETED` :

1. **Chemin d'erreur structurant** : `POST /salons/{id}/payments` avec un **montant incohérent** →
   `422`, et **aucune** trace (SQL : `payments`, `cash_journal`, `audit_logs` inchangés) — §8.2/§11.4.
2. **Chemin nominal** : `POST /salons/{id}/payments` avec le **bon montant** + un mode de paiement
   (p. ex. `CASH`) → `201` `VALIDATED`.
3. **Journal de caisse (étape PRD 7)** : SQL → **une** ligne `PAYMENT` liée au paiement ;
   `GET /salons/{id}/payments` (historique/transactions) liste ce paiement, cohérent (montant,
   horodatage, auteur).
4. **Dashboard (étape PRD 8)** : `GET /salons/{id}/revenue/summary` reflète le montant net.
5. **Reçu (étape PRD 9)** : `GET /me/receipts` (jeton **client**) liste le reçu ; `GET
   /me/receipts/{payment_id}` renvoie le détail (montant, mode, statut, prestations figées, identité
   **publique** du salon) — **sans PII tierce**. Un `payment_id` d'un tiers/inexistant → `404` neutre
   (un seul cas, garde-fou d'appartenance).

### Assertions transverses (invariants §11.3/§11.4)

- **Aucune PII ni secret** dans les corps de réponse au-delà du strict nécessaire (les reçus/historique
  exposent des libellés et montants, jamais de numéro de téléphone tiers ni de note interne).
- Les notifications persistées portent des libellés templatés **sans** téléphone ni nom (déjà couvert
  finement ailleurs — assertion légère ici).
- **Atomicité** au §5.3.1 (échec paiement → zéro écriture).

## Affected Files / Packages / Modules

**À créer :**

- `backend/tests/test_critical_journeys_e2e.py` (ou trois fichiers `test_journey_*_e2e.py` — décision
  ouverte 3) — **seul livrable de code**.

**À lire (référence, non modifiés) :**

- `backend/tests/test_appointment_notification_e2e.py` — patron principal (fixtures multi-acteurs,
  `_wipe_test_data` FK-safe, `_book`/`_set_status`/`_modify`/`_cancel`).
- `backend/tests/test_payments_e2e.py`, `test_receipts_e2e.py`, `test_daily_summary_e2e.py`,
  `test_hairdresser_planning_e2e.py` — helpers d'encaissement / reçu / décompte / assignation.
- `backend/coiflink_api/adapters/inbound/{appointments,payments,receipts,catalog,salons,services,employees,stats,auth}.py`
  — surfaces d'endpoints (contrats).
- `backend/coiflink_api/main.py` — montage des routers.
- `backend/coiflink_api/adapters/outbound/persistence/session.py` — `get_engine`/`get_sessionmaker`
  (lectures SQL directes).
- `backend/pyproject.toml` — `[tool.pytest.ini_options]` (+ enregistrement d'un marqueur `e2e` si
  décision ouverte 2b retenue).

**À mettre à jour (documentation) :**

- `docs/strategie-de-tests.md` — passer la ligne « e2e (#50) … CI dédiée (à venir) » à **livré**, et
  décrire comment lancer la suite de parcours localement.
- `.github/workflows/ci.yml` — **uniquement si** la décision ouverte 2b (job/étape e2e dédié) est
  retenue. Le chemin recommandé (2a) ne modifie **pas** le workflow.
- `README.md` — mention facultative de la suite e2e de parcours (M6) dans la section CI/tests.

## API / Interface Changes

**None.** Aucun endpoint, aucun paramètre, aucun schéma de réponse n'est ajouté ou modifié. Les tests
consomment des interfaces HTTP existantes.

Interface **de test / CI** potentiellement touchée (selon décision ouverte 2b) : un éventuel marqueur
`pytest` `e2e` enregistré dans `pyproject.toml` et/ou une commande de sélection
(`pytest -m e2e` ou `pytest tests/test_*_journey_e2e.py`) pour une étape CI dédiée. Aucun changement
d'API applicative.

## Data Model / Protocol Changes

**None.** Aucune migration, aucune table, aucune colonne, aucun changement de format de sérialisation.
Les tests écrivent/lisent via le schéma existant (migrations `0001`–`0009` déjà appliquées par
`alembic upgrade head`) et nettoient leurs propres données par plage de téléphones réservée.

## Security & Privacy Considerations

- **Aucun secret réel** : le JWT de test utilise un secret **factice local** (`_TEST_JWT_SECRET`,
  jamais un secret de production), injecté par `dependency_overrides` comme dans les e2e existants. La
  `docs/strategie-de-tests.md` §6 et `backend/tests/test_secrets_policy.py` imposent qu'**aucun secret
  ni PII n'apparaisse dans la sortie de test** (celle-ci est tronquée et transmise à l'agent en phase
  `resolve`). Les tests ne doivent **jamais** journaliser jeton, mot de passe ou téléphone.
- **PII** : les données de test utilisent une **plage de téléphones réservée** et des noms factices ;
  aucune donnée réelle. Les assertions vérifient **positivement** l'absence de PII tierce dans les
  reçus/notifications (§11.3) plutôt que de l'imprimer.
- **Isolation par salon (§11.2)** et **matrice RBAC négative** : **hors périmètre** (#51). Les parcours
  restent sur le chemin **autorisé** ; au plus un `401` deny-by-default et un `404` neutre
  d'appartenance par parcours, sans dupliquer #51.
- **Non-remise proactive (ADR-0006/0030/0033-0037)** : les parcours assertent que notifications et
  reçus sont **émis/tracés/récupérables** (`sent_at IS NULL`), **jamais** qu'un envoi réel a lieu — le
  périmètre M5 s'arrête à l'émission/trace.
- **CI** : le mot de passe du service Postgres de CI est **éphémère, jetable et non secret** (déjà le
  cas dans `ci.yml`) ; aucun secret n'entre dans le workflow.

Si un doute subsiste sur une contrainte, le repo ne documente **aucune** exigence de résidence/latence
applicable à une suite de tests au-delà de ce qui précède.

## Testing Plan

Ce ticket **est** un ticket de tests ; le « plan de test » est le contenu de la suite e2e livrée
(ci-dessus). En complément :

- **Validation locale** de la nouvelle suite contre PostgreSQL (mémoire projet : `coiflink-e2e-pg`,
  port 55433) :
  ```bash
  cd backend
  DATABASE_URL=postgresql://coif:pw@localhost:55433/coif alembic upgrade head
  DATABASE_URL=postgresql://coif:pw@localhost:55433/coif pytest tests/test_critical_journeys_e2e.py -v
  ```
- **Vérification du skip propre** : `pytest tests/test_critical_journeys_e2e.py` **sans** `DATABASE_URL`
  → tous les cas **skippés** (aucune erreur, aucune tentative de connexion), comme les autres `*_e2e.py`.
- **Vérification du nettoyage** : lancer la suite deux fois de suite → verte les deux fois (idempotence
  du `_wipe_test_data()` FK-safe).
- **Parité CI** : confirmer que la suite s'exécute **réellement** (non skippée) dans le job `backend`
  de `ci.yml` (où `DATABASE_URL` est défini et `alembic upgrade head` précède `pytest`).
- **Lint** : `ruff check .` passe sur le nouveau fichier (`ruff format` non imposé).
- **Non-régression** : `TEST_GATE_PACKAGES="backend" scripts/test-gate.sh` reste vert (le gate ADW
  n'exécute pas l'e2e — pas de `DATABASE_URL` — donc la nouvelle suite y est **skippée**, comportement
  attendu et documenté).

## Documentation Updates

- **`docs/strategie-de-tests.md`** (obligatoire) : mettre à jour la ligne e2e (§1 et §4) — « #50 les
  câble » devient **livré** ; ajouter dans §5 « Comment ajouter un test » une note sur les **e2e de
  parcours** (fichier `test_*_journey_e2e.py`/`test_critical_journeys_e2e.py`, `DATABASE_URL` requis,
  plage de téléphones réservée). Rappeler l'invariant §6 (aucun secret/PII en sortie).
- **`README.md`** (facultatif) : une phrase en §5 « CI applicative » / §6 (roadmap M6) signalant la
  suite e2e des parcours critiques (#50) et son exécution dans le job `backend`.
- **ADR** : **aucun ADR requis** *a priori* — le ticket n'introduit pas de décision d'architecture
  nouvelle (il suit ADR-0008/0009 et le patron e2e établi). **Exception** : si la décision ouverte 1
  (e2e d'IU) ou 2b (job CI e2e dédié + marqueur `e2e`) était retenue comme changement structurant, un
  court ADR documenterait le choix. Par défaut, **pas d'ADR**.

## Risks and Open Questions

1. **Périmètre « e2e » : backend-HTTP vs cross-composants IU.** `docs/strategie-de-tests.md` définit
   l'e2e comme « mobile/web ↔ backend ↔ DB », mais aucune infra d'e2e d'IU n'existe et la CI n'orchestre
   pas d'app vivante. **Recommandation** : livrer les parcours au **niveau HTTP backend** (contrat que
   consomment web/mobile), cohérent avec tous les `*_e2e.py` existants et avec « intégrée à la CI (#4) »
   sans nouvelle infra. L'e2e d'IU (Playwright/`integration_test`) est une **extension hors périmètre**.
   *À confirmer.*
2. **Câblage CI : découverte par le `pytest` existant (2a) vs job/étape e2e dédié (2b).**
   - **2a (recommandé)** : les `*_e2e.py` s'exécutent **déjà** dans le job `backend` de `ci.yml`
     (`DATABASE_URL` défini au niveau du job + `alembic upgrade head` avant `pytest`) ; la nouvelle
     suite est découverte **sans modifier le workflow**, et le job `backend` est déjà un **status check
     requis** (README §CI). C'est le chemin le plus simple et le plus cohérent.
   - **2b (optionnel)** : enregistrer un marqueur `e2e` et ajouter une **étape/job CI e2e nommé**
     (visibilité d'un check dédié « e2e » explicitement requis). Plus visible, mais duplique
     l'exécution et impose un réglage de protection de branche (hors dépôt). *À trancher — 2a par
     défaut, 2b si l'on veut un check e2e distinct.*
3. **Un fichier (trois classes) vs trois fichiers.** Un fichier partage mieux la fixture (un seul
   salon/gérant/coiffeur) ; trois fichiers isolent chaque parcours et parallélisent. **Recommandation :
   un fichier** `test_critical_journeys_e2e.py`. *À confirmer.*
4. **Plage de téléphones réservée.** Les préfixes déjà pris incluent `+225069998`, `+225070000/998`,
   `+225071999`…`+225079999`, `+225074997/8/9`, `+225076995…999`, `+225077998`. Choisir une plage
   **libre** (candidat : `+225068999`, ou `+225068997/8` si trois fichiers) et **la confirmer libre**
   par un `grep` au moment de l'implémentation, pour éviter les collisions de nettoyage entre suites qui
   partagent la même base CI.
5. **Assertion « CA mis à jour ».** Sur une base nettoyée par plage réservée, le salon de test est
   isolé : le CA du jour **avant** paiement est `0` et **après** égale le montant. Comparer
   **avant/après** (robuste) plutôt qu'attendre une valeur absolue si d'autres suites partagent la
   fenêtre — mais la borne par plage réservée rend l'attente absolue sûre. *Choix d'implémentation.*
6. **Déterminisme temporel.** Réserver un créneau **futur** (`_next_monday()` + créneau issu de
   `availability`) évite l'exclusion des créneaux passés et les effets de bord d'horloge ; ne pas
   coder en dur une date proche du présent.
7. **Ordre FK-safe du nettoyage.** Depuis #45/#49, `notifications` et `campaigns` référencent
   `appointments`/`salons`/`users` en **RESTRICT** : réutiliser **exactement** l'ordre de DELETE des
   e2e récents, sinon le `_wipe_test_data()` échoue. *Blocage classique — vérifié à l'implémentation.*
8. **Coût/durée CI.** Ajouter trois parcours multi-étapes allonge légèrement le job `backend`. Impact
   attendu faible (quelques secondes) ; garder les scénarios **minimaux** (un chemin nominal + un
   chemin d'erreur structurant par parcours), la couverture fine restant dans les suites
   par-fonctionnalité.

## Implementation Checklist

1. **Lire** `backend/tests/test_appointment_notification_e2e.py` (patron principal),
   `test_payments_e2e.py`, `test_receipts_e2e.py`, `test_daily_summary_e2e.py`,
   `test_hairdresser_planning_e2e.py` — relever `_wipe_test_data()` (ordre FK-safe), les fixtures
   multi-acteurs et les helpers HTTP.
2. **Choisir et confirmer** une plage de téléphones **libre** (`grep -rhoE "\+22507[0-9]{4}|\+22506[0-9]{4}" backend/tests/*_e2e.py | sort -u`) ; réserver `_E2E_PHONE_PREFIX`.
3. **Créer** `backend/tests/test_critical_journeys_e2e.py` : constantes (`_DATABASE_URL`,
   `_TEST_JWT_SECRET` factice, `_E2E_PHONE_PREFIX`), `_wipe_test_data()` FK-safe (notifications →
   campaigns → cash_journal → payments → appointment_services → appointments → audit_logs →
   customer_profiles → services → opening_hours → salon_members → salon_photos → salons → users),
   fixture `_e2e_client` (skip sans `DATABASE_URL`, override `token_service`/`login_rate_limiter`, wipe
   avant/après).
4. **Écrire la fixture d'installation** (gérant + salon **réservable** [horaires + prestation] +
   coiffeur + client) via les **endpoints réels**.
5. **`TestBookingJourneyE2E` (§5.1)** : catalogue → fiche → disponibilités → réservation `PENDING` →
   assertion présence confirmation/rappels (SQL) → transition gérant `CONFIRMED`→`COMPLETED` →
   historique client ; + `401` deny-by-default.
6. **`TestManagerAppointmentJourneyE2E` (§5.2)** : `daily-summary` → assignation coiffeur → `CONFIRMED`
   → `COMPLETED` → paiement → `revenue/summary` (CA ↑) → historique client.
7. **`TestCheckoutJourneyE2E` (§5.3)** : montant incohérent → `422` + **zéro** écriture (SQL) → montant
   correct → `201` → ligne `PAYMENT` au journal + `GET /payments` → `revenue/summary` → `GET /me/receipts`
   + détail ; + `404` neutre d'appartenance.
8. **Assertions transverses** : absence de PII/secret dans corps et notifications ; atomicité au §5.3.1.
9. **Valider localement** (skip sans `DATABASE_URL` ; vert deux fois de suite contre Postgres port
   55433) et **`ruff check .`**.
10. **Câbler la CI (2a)** : vérifier que la suite s'exécute (non skippée) dans le job `backend` de
    `ci.yml` — **aucune modification de workflow** attendue. *(Optionnel 2b : enregistrer un marqueur
    `e2e` dans `pyproject.toml` et ajouter une étape/job e2e dédié.)*
11. **Mettre à jour `docs/strategie-de-tests.md`** (e2e #50 = livré) et, facultatif, `README.md`.
12. **Ne pas** modifier le code de production ; si un parcours révèle un défaut d'intégration réel,
    **ouvrir un ticket distinct** et documenter le constat (ne pas « corriger » sous couvert de #50).
