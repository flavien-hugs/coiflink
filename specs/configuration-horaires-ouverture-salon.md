# Configuration des horaires d'ouverture d'un salon (US-2.2, issue #16)

> Issue GitHub **#16** — `feature` · Priorité **Must** · Effort **M** · PRD §6 Épic 2
> Dépend de **#15** (création d'un salon) — livré.
> Deuxième item du jalon **M2** (salons & prestations).

## Problem Statement

La création d'un salon est livrée (#15) : un gérant crée son salon (`POST /salons`), qui naît
`status=ACTIVE` avec `opening_hours=NULL`. La règle §8.3 est déjà **matérialisée mais pas encore
activable** : le prédicat de domaine `is_bookable(status, opening_hours)` renvoie `False` tant que
`opening_hours` est vide, et le dashboard affiche le bandeau « Ce salon n'est pas encore réservable :
configurez vos horaires d'ouverture ». Le backend expose déjà `opening_hours` en lecture (colonne
JSONB `salons.opening_hours`, déjà au schéma #3 ; renvoyée par `GET /salons` et `GET /salons/{id}`).

**Mais aucune route ni cas d'usage ne permet d'écrire ces horaires** : la colonne reste
définitivement `NULL`, `is_bookable` reste toujours `False`, et le bandouleau du dashboard ne peut
jamais disparaître de l'écran Paramètres. Conséquences concrètes :

- le second critère d'acceptation de #15 (« un salon sans horaire n'est pas réservable ») est
  matérialisé mais son **complément** — pouvoir *configurer* les horaires pour rendre le salon
  réservable — n'existe pas ;
- tout M3 (rendez-vous #21+) est bloqué en amont : sans horaires enregistrés, aucun salon ne pourra
  jamais devenir réservable ;
- la section **Paramètres** du dashboard promet « Vous pourrez ajouter [...] vos horaires
  d'ouverture ensuite » (texte livré par #15) — une promesse aujourd'hui sans écran.

US-2.2 demande de **configurer les horaires d'ouverture** : horaires par jour, jours fermés, pauses,
jours exceptionnels. Les critères d'acceptation sont : **(1)** les horaires sont enregistrés par
salon ; **(2)** un salon sans horaire ne peut pas recevoir de réservation (§8.3).

## Goals

1. **Enregistrer les horaires d'un salon** : une route d'écriture (`PUT /salons/{salon_id}/opening-hours`)
   qui persiste une structure d'horaires validée dans la colonne existante `salons.opening_hours`.
2. **Porter les quatre dimensions de US-2.2** :
   - **horaires par jour** : pour chaque jour de la semaine, une liste d'intervalles d'ouverture ;
   - **jours fermés** : un jour sans intervalle est fermé ;
   - **pauses** : plusieurs intervalles dans un même jour (le trou entre deux intervalles *est* la
     pause — ex. `08:00–12:00` puis `14:00–18:00`) ;
   - **jours exceptionnels** : des surcharges datées (fermeture exceptionnelle un jour donné, ou
     horaires exceptionnels pour une date précise).
3. **Activer la règle §8.3 de bout en bout** : après enregistrement d'horaires valides, la réponse API
   et le dashboard doivent refléter `is_bookable=true` (le bandeau « pas encore réservable » disparaît)
   — **sans ajouter aucune logique de réservation** (celle-ci est #21+).
4. **Valider rigoureusement la structure** dans le domaine pur (heures bien formées, intervalles
   ordonnés et non chevauchants, dates d'exception valides) et rejeter toute forme incohérente en
   `422`, avec des messages **neutres** (ni PII, ni détail SQL).
5. **Réutiliser le socle existant sans le réinventer** : permission `SALON_UPDATE` (le gérant la
   détient déjà), garde `require_salon_scope`, patron de router/cas d'usage/dépôt de #15, lecture
   déjà en place (`GET /salons/{id}`).
6. **Permettre au gérant de configurer ses horaires depuis le dashboard** (#14), sous la section
   **Paramètres** (PRD §7.2 : « Informations générales · Horaires · Jours fermés · Photos ·
   Localisation »).
7. **Ne pas affaiblir le deny-by-default** : aucune route publique ; la route d'écriture est protégée
   par permission **et** portée salon.

## Non-Goals

Ces sujets appartiennent à d'autres issues et **ne doivent pas** être implémentés ici :

- **Application effective de §8.3 au moment de réserver** — la *réservation* est **#21+**. Ce spec
  rend un salon `is_bookable` en enregistrant ses horaires ; il n'ajoute **aucun** contrôle de
  créneau, aucune vérification « le RDV demandé tombe-t-il dans un intervalle ouvert ». Il n'existe
  encore aucune route de réservation à contraindre.
- **Calcul de disponibilité / créneaux réservables** (matérialisation des slots à partir des horaires
  et des prestations) — relève de #21+ (réservation) et de la durée des prestations (#17).
- **Consultation client des horaires** (affichage §7 côté app mobile / catalogue client) — **#18/#19**
  (US-2.4). Ce spec expose les horaires via les routes salon **protégées** existantes ; il n'ajoute
  **aucune** route salon publique.
- **Prestations** (#17), recherche/liste client (#18), modification des informations textuelles du
  salon (#20).
- **Fuseau horaire multi-région / sélecteur de fuseau** : le marché MVP est la Côte d'Ivoire
  (`Africa/Abidjan`, UTC+00). Le fuseau est stocké avec une valeur par défaut fixe, non éditable dans
  l'UI (voir *Risques*).
- **Rappels calés sur les horaires**, **fermetures récurrentes annuelles** (jours fériés
  automatiques) — hors périmètre ; les jours exceptionnels sont **datés** (une date précise), pas des
  règles récurrentes.
- **Journal d'audit applicatif** (§11.4) : la liste §11.4 ne mentionne pas « modification des
  horaires ». Aucun journal d'audit n'est mis en place ici.

## Relevant Repository Context

### Architecture (figée par les ADR — source de vérité)

- **Backend** : Python ≥ 3.12, **FastAPI**, API REST, JWT ([ADR-0003](../docs/adr/0003-backend-fastapi.md)).
- **Architecture hexagonale** ([ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) :
  `domain/` (pur, zéro dépendance framework/I/O) → `application/` (cas d'usage + `ports/`) →
  `adapters/inbound/` (routers FastAPI) et `adapters/outbound/` (SQLAlchemy).
- **Données** : **PostgreSQL 16**, ORM **SQLAlchemy 2.0**, migrations **Alembic**
  ([ADR-0004](../docs/adr/0004-donnees-postgresql-redis.md),
  [ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)).
- **Autorisation** : RBAC **deny-by-default**
  ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) — gardes en **dépendances
  FastAPI**, pas en middleware ASGI.
- **Web gérant** : **Next.js** (App Router, TypeScript), zone protégée `/gerant`, BFF + cookie
  `httpOnly` ([ADR-0002](../docs/adr/0002-web-gerant-admin-nextjs.md), #14).
- **Salon & §8.3** : la tranche salon (#15) est décrite par
  [ADR-0017](../docs/adr/0017-creation-salon-medias-et-reservabilite.md), qui fige notamment que
  `is_bookable` est une **règle de domaine dérivée, jamais persistée**, et que `opening_hours` reste
  `NULL` à la création (« la configuration des horaires elle-même relève de #16 »).

### Ce qui existe déjà et qu'il faut réutiliser (ne rien réinventer)

| Élément | Chemin | Rôle pour #16 |
| --- | --- | --- |
| Colonne `salons.opening_hours` | `backend/coiflink_api/adapters/outbound/persistence/models.py:157` | `JSONB`, **nullable**, **déjà au schéma** (#3). C'est la cible d'écriture — **aucune migration** de structure de table nécessaire (voir *Data Model*). |
| Prédicat `is_bookable` | `backend/coiflink_api/domain/salon.py:107` | `is_bookable(status, opening_hours) = (status==ACTIVE) et bool(opening_hours)`. Écrire un dict **non vide** fait basculer `is_bookable` à `True`. **Ne pas modifier sa signature** — le respecter tel quel (voir *Open Questions* sur la sémantique). |
| Entité de domaine `Salon` | `backend/coiflink_api/domain/salon.py:155` | Porte déjà `opening_hours: dict | None` et la propriété `is_bookable`. À enrichir seulement via le nouveau module d'horaires (pas de champ à ajouter). |
| Permission `SALON_UPDATE` | `backend/coiflink_api/domain/permissions.py:44` | Déjà détenue par le `MANAGER`. **Aucune permission nouvelle.** La configuration d'horaires est une modification du salon. |
| Router salons | `backend/coiflink_api/adapters/inbound/salons.py` | **Le fichier à étendre** : y ajouter la route `PUT /salons/{salon_id}/opening-hours` (patron des routes `PUT /logo` / `POST /photos` : `require_permission(SALON_UPDATE)` + `require_salon_scope`, traduction erreurs de domaine → HTTP). |
| Cas d'usage salons | `backend/coiflink_api/application/salons.py` | **À étendre** : nouveau cas d'usage `SetOpeningHours` (patron `AttachSalonLogo` : DI de port, `find_by_id` → `SalonNotFound`, écriture via le dépôt). |
| Port + dépôt salon | `backend/coiflink_api/application/ports/salon_repository.py`, `.../persistence/salon_repository.py` | **À étendre** : méthode `set_opening_hours(salon_id, opening_hours) -> Salon` (patron `set_logo`, `flush()` sans `commit()`). |
| Lecture salon | `GET /salons`, `GET /salons/{salon_id}` (`salons.py`) | Renvoient **déjà** `opening_hours` et `is_bookable` — **aucune route de lecture nouvelle** n'est requise. |
| Gardes RBAC | `backend/coiflink_api/adapters/inbound/security.py` | `require_permission(...)`, `require_salon_scope` (lit `salon_id` **du chemin**), invariant `unprotected_routes(app)`. **Aucune garde nouvelle** (contrairement à #15 qui avait ajouté `require_any_permission`). |
| Domaine erreurs | `backend/coiflink_api/domain/errors.py` | Ajouter une erreur `InvalidOpeningHours` (message neutre), sur le patron de `InvalidLocation`. |
| Fakes de test | `backend/tests/conftest.py:412` (`FakeSalonRepository`) | À étendre : `set_opening_hours`. Le fake force déjà `opening_hours=None` à la création. |
| Front — domaine salon | `web-dashboard/src/domain/salon/salon.ts` | `Salon.openingHours: Record<string, unknown> | null` + `isBookable(...)` déjà en place. À enrichir d'un type structuré `OpeningHours` et d'un validateur miroir. |
| Front — port/gateway | `web-dashboard/src/application/ports/salon-gateway.ts`, `.../adapters/api/http-salon-gateway.ts` | À étendre : méthode `setOpeningHours(...)` proxifiant le backend **côté serveur** (jeton du cookie httpOnly, jamais exposé). |
| Front — BFF | `web-dashboard/app/api/salons/route.ts` | À compléter : route BFF `PUT /api/salons/[id]/opening-hours`. |
| Front — page Paramètres | `web-dashboard/app/(gerant)/gerant/parametres/page.tsx` | **À étendre** : l'écran affiche déjà un bandeau §8.3 conditionné par `isBookable(salon)` ; y ajouter l'éditeur d'horaires. |

### Commandes (déjà en place, ne pas réinventer)

- Backend : `pytest`, `ruff check`, migrations Alembic (round-trip vérifié en CI contre PostgreSQL 16).
- Web : `npm test` (Vitest), `npm run lint`, `npm run build`.
- Test gate agrégé du pipeline : `scripts/test-gate.sh` (parité CI) — cf. `docs/strategie-de-tests.md`.

### Écart / point d'attention identifié

Le PRD §9.2 nomme la colonne `opening_hours` mais **ne spécifie pas sa structure interne**. Ce spec
**fixe le contrat JSONB** (voir *Data Model / Protocol Changes*) : c'est une décision de conception à
tracer (ADR de suivi recommandé — voir *Documentation Updates*). Aucun autre écart de schéma.

## Proposed Implementation

### Vue d'ensemble

Une **extension** de la tranche salon existante (#15), calquée sur les routes de médias : nouveau
module de domaine pur pour valider/normaliser la structure d'horaires, un cas d'usage `SetOpeningHours`,
une méthode de dépôt, une route `PUT` protégée, et un éditeur dans le dashboard. **Aucune** nouvelle
table, migration de structure, permission, ni route publique.

```
domain/opening_hours.py         (pur : structure, parsing, validation, normalisation)
        ▲
application/salons.py           (nouveau cas d'usage SetOpeningHours)
application/ports/salon_repository.py   (+ set_opening_hours)
        ▲
adapters/inbound/salons.py      (route PUT /salons/{id}/opening-hours + schémas Pydantic)
adapters/outbound/persistence/salon_repository.py  (+ set_opening_hours, SQLAlchemy)
```

### 1. Domaine (`backend/coiflink_api/domain/opening_hours.py`) — nouveau, pur

Module sans aucune dépendance framework/I/O (ADR-0008). Il définit la **structure canonique** des
horaires, la **valide** et la **normalise** (tri des intervalles, minuscule des clés de jour), et lève
`InvalidOpeningHours` sur toute incohérence.

Structure canonique (représentée en `dict`/`dataclass` internes, sérialisée en JSONB) :

```python
DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # ordre semaine
OPENING_HOURS_SCHEMA_VERSION = 1
DEFAULT_TIMEZONE = "Africa/Abidjan"   # Côte d'Ivoire (UTC+00) — MVP mono-fuseau

@dataclass(frozen=True)
class TimeInterval:
    start: str   # "HH:MM" 24h
    end: str     # "HH:MM" 24h, strictement > start

@dataclass(frozen=True)
class DaySchedule:
    day: str                       # une clé de DAY_KEYS
    intervals: tuple[TimeInterval, ...]   # vide ⇒ jour fermé ; >1 ⇒ pause(s)

@dataclass(frozen=True)
class ExceptionalDay:
    date: datetime.date            # date précise (jour exceptionnel)
    closed: bool                   # True ⇒ fermé ce jour-là
    intervals: tuple[TimeInterval, ...]   # horaires exceptionnels si non fermé

@dataclass(frozen=True)
class OpeningHours:
    version: int
    timezone: str
    weekly: tuple[DaySchedule, ...]        # 0..7 jours (jours absents = fermés)
    exceptions: tuple[ExceptionalDay, ...] # 0..N surcharges datées
```

Fonctions pures :

- `parse_opening_hours(payload: dict) -> OpeningHours` : construit la structure canonique à partir du
  `dict` reçu (déjà désérialisé par Pydantic). Rejette toute clé/valeur inattendue.
- `validate_opening_hours(hours: OpeningHours) -> OpeningHours` (ou validation intégrée au parse) —
  règles :
  - **jours** : clés dans `DAY_KEYS`, sans doublon ;
  - **heures** : format `HH:MM`, `00:00`–`23:59` (regex + bornes), `end > start` (pas d'intervalle
    nul ni inversé ; pas de passage minuit — un intervalle ne franchit pas `24:00`) ;
  - **intervalles d'un même jour** : triés par `start`, **non chevauchants** et **non adjacents
    ambigus** (l'écart entre deux intervalles *est* la pause) → chevauchement ⇒ `InvalidOpeningHours` ;
  - **exceptions** : `date` ISO valide ; si `closed=true`, `intervals` doit être vide ; si
    `closed=false`, au moins un intervalle valide ; pas deux exceptions pour la **même date** ;
  - **non-vacuité utile** (voir *Open Questions*) : la semaine doit contenir **au moins un intervalle
    d'ouverture** (un salon « configuré » ouvre au moins une fois) → sinon `InvalidOpeningHours`.
    Cette règle garantit que le JSONB persisté est **non vide et signifiant**, donc que
    `is_bookable` (structurel) ne ment pas.
- `to_jsonb(hours: OpeningHours) -> dict` : sérialise la forme canonique **normalisée** (clés de jour
  minuscules, intervalles triés, `version`, `timezone`) — c'est ce `dict` qui est écrit en base et
  relu par les lectures existantes.

Forme JSONB persistée (contrat, voir *Data Model*) :

```jsonc
{
  "version": 1,
  "timezone": "Africa/Abidjan",
  "weekly": {
    "mon": [{ "start": "08:00", "end": "12:00" }, { "start": "14:00", "end": "18:00" }],
    "tue": [{ "start": "08:00", "end": "18:00" }],
    "wed": []                              // fermé
    // jours absents ⇒ fermés
  },
  "exceptions": [
    { "date": "2026-08-07", "closed": true },                                  // fermé exceptionnel
    { "date": "2026-12-24", "closed": false, "intervals": [{ "start": "08:00", "end": "13:00" }] }
  ]
}
```

Nouvelle erreur dans `domain/errors.py` : `InvalidOpeningHours` (message neutre, sans PII ni détail
SQL), sur le patron de `InvalidLocation`. L'ajouter à `__all__`.

### 2. Port (`backend/coiflink_api/application/ports/salon_repository.py`)

Ajouter au `Protocol SalonRepository` :

```python
def set_opening_hours(self, salon_id: uuid.UUID, opening_hours: dict) -> Salon:
    """Écrit la structure d'horaires (déjà validée) ; retourne le salon relu.

    Lève domain.errors.SalonNotFound si le salon n'existe pas.
    """
    ...
```

### 3. Application (`backend/coiflink_api/application/salons.py`)

Nouveau cas d'usage `SetOpeningHours` (patron `AttachSalonLogo`) :

```python
class SetOpeningHours:
    def __init__(self, repository: SalonRepository) -> None:
        self._repository = repository

    def execute(self, salon_id: uuid.UUID, payload: dict) -> Salon:
        hours = parse_opening_hours(payload)          # valide + normalise (domaine pur)
        if self._repository.find_by_id(salon_id) is None:
            raise SalonNotFound("Salon introuvable.")
        return self._repository.set_opening_hours(salon_id, to_jsonb(hours))
```

- La **validation précède l'écriture** (aucun appel d'écriture si la structure est invalide).
- `find_by_id` avant écriture pour distinguer `404` (salon absent, portée déjà validée) d'un `422`
  (structure invalide) — cohérent avec `AttachSalonLogo`.
- Ajouter `SetOpeningHours` à `__all__`.

### 4. Adapter entrant (`backend/coiflink_api/adapters/inbound/salons.py`)

Nouvelle route, sous le préfixe `/salons/{salon_id}/…` (donc couverte par `require_salon_scope`) :

| Route | Garde(s) | Rôles effectifs (matrice §4.1) |
| --- | --- | --- |
| `PUT /salons/{salon_id}/opening-hours` | `require_permission(SALON_UPDATE)` + `require_salon_scope` | **MANAGER** (son salon) |

Schémas Pydantic (documentation OpenAPI incluse, patron des schémas existants du module) :

```python
class TimeIntervalModel(BaseModel):
    start: str = Field(examples=["08:00"])
    end: str = Field(examples=["12:00"])

class ExceptionalDayModel(BaseModel):
    date: datetime.date = Field(examples=["2026-08-07"])
    closed: bool = Field(default=False)
    intervals: list[TimeIntervalModel] = Field(default_factory=list)

class OpeningHoursRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # weekly : dict jour → intervalles ; jours absents = fermés.
    weekly: dict[str, list[TimeIntervalModel]] = Field(default_factory=dict)
    exceptions: list[ExceptionalDayModel] = Field(default_factory=list)
    # timezone optionnel : défaut serveur DEFAULT_TIMEZONE si absent (non éditable UI MVP).
    timezone: str | None = Field(default=None)
```

- La route mappe `OpeningHoursRequest` → `dict` brut, appelle `SetOpeningHours(...).execute(...)`,
  puis retourne un `SalonResponse` complet (via `GetSalon` pour résoudre logo/photos signés) — de
  sorte que la réponse porte `opening_hours` **normalisé** et `is_bookable=true`.
- Traduction des erreurs : `InvalidOpeningHours` → **422** ; `SalonNotFound` → **404**
  *(seulement après validation de portée — sinon `403` générique)*. Ne jamais faire `str(exc)` sur un
  refus RBAC (patron du module).
- **Ne pas** ajouter le chemin à `PUBLIC_ROUTE_PATHS`.

`responses=` documenté : `401` / `403` / `404` / `422` (pas de `503` : cette route ne touche pas au
stockage objet).

### 5. Adapter sortant (`backend/coiflink_api/adapters/outbound/persistence/salon_repository.py`)

Ajouter `set_opening_hours` (patron `set_logo`) :

```python
def set_opening_hours(self, salon_id: uuid.UUID, opening_hours: dict) -> Salon:
    row = self._session.get(models.Salon, salon_id)
    if row is None:
        raise SalonNotFound("Salon introuvable.")
    row.opening_hours = opening_hours
    self._session.flush()
    self._session.refresh(row)
    return _to_domain(row)
```

`flush()` **sans** `commit()` (le commit est piloté par `get_session`).

### 6. Web dashboard (`web-dashboard/`)

Cible : la section **Paramètres** existante (pas de 8ᵉ entrée de navigation).

- `src/domain/salon/opening-hours.ts` (ou extension de `salon.ts`) — type structuré `OpeningHours`
  (miroir strict du contrat JSONB backend : `weekly`, `exceptions`, `timezone`, `version`) + un
  validateur `validateOpeningHours(...)` **parité stricte** avec les règles du domaine Python
  (intervalles ordonnés, non chevauchants, `end > start`, au moins un intervalle). Tester la parité.
- `src/application/ports/salon-gateway.ts` — ajouter `setOpeningHours(salonId, hours): Promise<...>`
  au port, avec un `SetOpeningHoursResult` aux motifs génériques (`invalid` / `forbidden` /
  `unauthenticated` / `unavailable`).
- `src/adapters/api/http-salon-gateway.ts` — implémente l'appel `PUT` backend **côté serveur**
  (jeton du cookie httpOnly, jamais journalisé, patron existant).
- `app/api/salons/[id]/opening-hours/route.ts` — route BFF `PUT` (lecture du cookie de session,
  mapping `200/401/403/422/503`, ne journalise ni jeton ni PII).
- `src/adapters/ui/opening-hours-form.tsx` — formulaire client : 7 jours, chaque jour avec une
  bascule « fermé / ouvert », un ou plusieurs intervalles (bouton « ajouter une pause »), et une
  section « jours exceptionnels » (ajout d'une date + fermé/horaires). Validation côté client avant
  envoi (retour immédiat), le backend restant l'autorité.
- `app/(gerant)/gerant/parametres/page.tsx` — intégrer l'éditeur sous la fiche du salon ; il consomme
  `salon.openingHours` déjà chargé. Le **bandeau §8.3** existant disparaît automatiquement dès que
  `isBookable(salon)` devient vrai (déjà câblé) — vérifier qu'un rechargement post-enregistrement
  reflète l'état.

## Affected Files / Packages / Modules

### `backend/` (paquet principal)

**À créer**
- `coiflink_api/domain/opening_hours.py`
- Tests : `tests/test_domain_opening_hours.py`, `tests/test_set_opening_hours_usecase.py`,
  `tests/test_salon_opening_hours_api.py` (+ extension éventuelle de `tests/test_salon_e2e.py` si
  présent, sinon un parcours e2e dédié).

**À modifier**
- `coiflink_api/domain/errors.py` — `InvalidOpeningHours` (+ `__all__`)
- `coiflink_api/application/ports/salon_repository.py` — `set_opening_hours`
- `coiflink_api/application/salons.py` — cas d'usage `SetOpeningHours` (+ `__all__`)
- `coiflink_api/adapters/inbound/salons.py` — route `PUT /salons/{id}/opening-hours` + schémas Pydantic
- `coiflink_api/adapters/outbound/persistence/salon_repository.py` — `set_opening_hours`
- `tests/conftest.py` — `FakeSalonRepository.set_opening_hours`
- `backend/README.md` — mention de la route et du contrat d'horaires

**À NE PAS modifier**
- `models.py` (colonne `opening_hours` déjà présente), `domain/permissions.py` (aucune permission
  nouvelle), `domain/salon.py::is_bookable` (signature inchangée — voir *Open Questions*),
  `security.py` (aucune garde nouvelle), `PUBLIC_ROUTE_PATHS`.

### `web-dashboard/`

**À créer** : `src/domain/salon/opening-hours.ts`, `src/adapters/ui/opening-hours-form.tsx`,
`app/api/salons/[id]/opening-hours/route.ts`, tests Vitest associés
(`test/opening-hours-domain.test.ts`, `test/set-opening-hours.test.ts`, extension de
`test/http-salon-gateway.test.ts` et des tests de routes BFF).

**À modifier** : `src/application/ports/salon-gateway.ts`, `src/adapters/api/http-salon-gateway.ts`,
`app/(gerant)/gerant/parametres/page.tsx`, `README.md`.

### Racine / docs

- `docs/adr/` — ADR de suivi recommandé (contrat JSONB des horaires + sémantique `is_bookable`) ;
  `docs/adr/README.md` (index).
- `README.md` (racine) — module 2 « Gestion des salons » et section 6 (« M2 en cours »).

## API / Interface Changes

**Nouvelle route REST** (protégée ; aucun ajout à `PUBLIC_ROUTE_PATHS`) :

### `PUT /salons/{salon_id}/opening-hours` → `200 OK`

Remplace **intégralement** les horaires du salon (sémantique *replace*, idempotente).

```jsonc
// Requête
{
  "weekly": {
    "mon": [{ "start": "08:00", "end": "12:00" }, { "start": "14:00", "end": "18:00" }],
    "tue": [{ "start": "08:00", "end": "18:00" }],
    "sat": [{ "start": "09:00", "end": "13:00" }]
    // jours absents (wed/thu/fri/sun) ⇒ fermés
  },
  "exceptions": [
    { "date": "2026-08-07", "closed": true },
    { "date": "2026-12-24", "closed": false, "intervals": [{ "start": "08:00", "end": "13:00" }] }
  ]
  // "timezone" optionnel ; défaut serveur "Africa/Abidjan"
}
```

```jsonc
// Réponse 200 — SalonResponse complet (patron des autres routes du module)
{
  "id": "…uuid…",
  "opening_hours": { "version": 1, "timezone": "Africa/Abidjan", "weekly": { … }, "exceptions": [ … ] },
  "is_bookable": true,          // ← §8.3 : horaires enregistrés ⇒ réservable (si ACTIVE)
  "status": "ACTIVE",
  // … reste du SalonResponse (name, logo_url signé, photos, …)
}
```

Codes : `200` · `401` (non authentifié) · `403` (rôle insuffisant **ou** salon hors périmètre —
générique) · `404` (salon introuvable, portée déjà validée) · `422` (structure d'horaires invalide).

**Lecture** : inchangée — `GET /salons` et `GET /salons/{salon_id}` renvoient déjà `opening_hours` et
`is_bookable`. **Aucune** route de lecture nouvelle.

**Nouvelles interfaces internes documentées** : méthode de port `SalonRepository.set_opening_hours`
(docstring) ; cas d'usage `SetOpeningHours` ; module `domain/opening_hours.py` (docstring de module
décrivant le contrat JSONB, comme les modules de domaine existants).

**Variables d'environnement** : aucune nouvelle. **CLI** : aucun changement.

## Data Model / Protocol Changes

**Structure de table** : **aucune modification**. La colonne `salons.opening_hours` (`JSONB`,
nullable) existe déjà (#3). **Aucune migration Alembic de structure** n'est requise.

**Nouveau contrat de sérialisation JSONB** (le point réellement nouveau de cette issue) : ce spec
**fixe la forme interne** de `opening_hours`, jusqu'ici non spécifiée par le PRD §9.2. Champs :

| Clé | Type | Contrainte |
| --- | --- | --- |
| `version` | entier | `1` (permet une évolution future du schéma JSONB sans ambiguïté) |
| `timezone` | chaîne IANA | défaut `"Africa/Abidjan"` |
| `weekly` | objet `{ jour: [intervalle] }` | clés ⊂ `{mon,tue,wed,thu,fri,sat,sun}` ; jour absent ⇒ fermé |
| `weekly[jour][]` | `{ start, end }` | `HH:MM` 24h ; `end > start` ; intervalles triés, non chevauchants |
| `exceptions` | liste d'objets | dates distinctes |
| `exceptions[]` | `{ date, closed, intervals? }` | `date` ISO ; `closed=true` ⇒ `intervals` vide ; sinon ≥ 1 intervalle |

**Invariant de réservabilité** : seul un JSONB **non vide et valide** (au moins un intervalle
d'ouverture hebdomadaire) peut être persisté. La règle §8.3 reste portée par `is_bookable` (structurel,
`bool(opening_hours)`), **inchangée** ; ce spec garantit simplement qu'aucun `{}` « faussement
configuré » n'est écrit.

**Compatibilité** : la colonne étant aujourd'hui toujours `NULL` (aucune écriture d'horaires n'existe
avant #16), il n'y a **aucune donnée existante** à migrer ni à rétro-valider. Un éventuel besoin de
« repasser un salon à non réservable » (remettre `opening_hours` à `NULL`) est **hors périmètre** —
voir *Open Questions*.

**Validation** : effectuée dans le **domaine** (`domain/opening_hours.py`), pas par une contrainte
`CHECK` SQL (un JSONB structuré ne se valide pas raisonnablement en `CHECK`). Cohérent avec la
frontière hexagonale (le domaine est l'autorité des règles métier).

## Security & Privacy Considerations

Contraintes **documentées** par le dépôt et touchées par ce changement :

1. **RBAC deny-by-default** ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) —
   *invariant à ne jamais affaiblir*. La route est `PUT /salons/{salon_id}/opening-hours`, protégée par
   `require_permission(SALON_UPDATE)` **et** `require_salon_scope`. Aucun chemin ajouté à
   `PUBLIC_ROUTE_PATHS` ; l'invariant `unprotected_routes(app)` doit rester **vide** (couvert
   automatiquement par `test_security_guards.py`).

2. **Isolation par salon** (PRD §11.2) — la route porte `salon_id` dans le chemin ; un gérant qui vise
   le salon d'un autre reçoit le **`403` générique** (message constant, **aucun oracle d'existence** —
   ne jamais dégrader ce `403` en `404` « informatif »). Le `404` `SalonNotFound` n'est renvoyé
   qu'**après** validation de portée.

3. **Pas de nouveau vecteur PII** : une structure d'horaires (jours/heures) n'est pas une donnée
   personnelle. Les messages d'erreur `InvalidOpeningHours` restent **neutres** (ni valeur soumise
   in extenso qui pourrait être injectée, ni détail SQL). Journalisation : ne journaliser ni le jeton,
   ni la PII du salon (`phone`, `address`, coordonnées) — le `salon_id` UUID suffit à tracer
   (invariant du dépôt, PRD §11.3). `test_secrets_policy.py` doit rester vert (aucun secret nouveau).

4. **Validation d'entrée stricte** : la structure est validée dans le domaine avant écriture (heures
   bien formées, bornes, non-chevauchement, dates valides). Refuser les clés/valeurs inattendues évite
   qu'un `weekly` géant ou des milliers d'`exceptions` ne gonflent la ligne JSONB — envisager une
   **borne raisonnable** sur le nombre d'exceptions (ex. ≤ 366) et d'intervalles par jour (ex. ≤ 6) au
   titre de la robustesse (budget latence/stockage, PRD §12). À traiter dans le validateur de domaine.

5. **Front (#14)** : le jeton d'accès reste dans un cookie `httpOnly`, lu **côté serveur** par le BFF ;
   il n'atteint jamais le navigateur. La passerelle ne journalise ni jeton ni PII (invariant
   `http-auth-gateway.ts`).

Le dépôt ne documente **aucune contrainte de résidence ou de chiffrement spécifique** aux horaires
(donnée non sensible) au-delà des invariants ci-dessus.

## Testing Plan

### Backend — unitaires (`pytest`, sans base ni réseau)

- `tests/test_domain_opening_hours.py` (cœur de l'issue) :
  - **horaires par jour** : un jour avec un intervalle valide → accepté ; clé de jour inconnue
    (`"lundi"`, `"mo"`) → `InvalidOpeningHours` ;
  - **jours fermés** : jour à `[]` ou absent → accepté et interprété « fermé » ;
  - **pauses** : deux intervalles disjoints (`08:00–12:00`, `14:00–18:00`) → acceptés et **triés** ;
  - **intervalles invalides** : `end <= start`, chevauchement (`08:00–12:00`, `11:00–15:00`), heure
    malformée (`8h`, `25:00`, `12:60`) → `InvalidOpeningHours` ;
  - **jours exceptionnels** : `closed=true` + `intervals` non vide → erreur ; `closed=false` +
    `intervals` vide → erreur ; deux exceptions même date → erreur ; date malformée → erreur ;
  - **non-vacuité** : `weekly` entièrement fermé **et** aucune exception ouverte → `InvalidOpeningHours` ;
  - **normalisation** : `to_jsonb` produit `version=1`, `timezone` par défaut si absent, clés
    minuscules, intervalles triés — forme **stable** (idempotence : `parse(to_jsonb(x)) == x`) ;
  - **bornes de robustesse** : trop d'exceptions / trop d'intervalles par jour → `InvalidOpeningHours`.
- `tests/test_set_opening_hours_usecase.py` (fakes de `conftest.py`) : validation **avant** écriture
  (aucun `set_opening_hours` appelé si la structure est invalide) ; `SalonNotFound` si le salon
  n'existe pas ; JSONB **normalisé** transmis au dépôt ; le salon relu porte `is_bookable=true`.

### Backend — API / intégration (`TestClient`, `dependency_overrides`)

- `tests/test_salon_opening_hours_api.py` :
  - **matrice RBAC** : `MANAGER` (son salon) → `200` ; `CLIENT`/`HAIRDRESSER` → `403` ; `ADMIN` →
    `403` (l'admin supervise, il ne configure pas les horaires — `SALON_UPDATE` est au `MANAGER`) ;
    sans jeton → `401` ;
  - **isolation** : `MANAGER` visant le salon d'un **autre** gérant → `403` **générique** (pas `404`) ;
  - **succès** : réponse `200` avec `opening_hours` normalisé et **`is_bookable: true`** ;
  - **validation** : corps avec chevauchement / heure malformée → `422` ;
  - **salon inexistant** (dans la portée d'un admin de test, si applicable) → `404` après portée ;
  - **replace** : un second `PUT` remplace intégralement (pas de fusion résiduelle).
- `tests/test_security_guards.py` (existant) : `unprotected_routes(app)` reste **vide** après ajout de
  la route.
- `tests/test_domain_permissions.py` (existant) : inchangé et vert (aucune permission nouvelle).

### Backend — end-to-end

Parcours : inscription gérant (#9) → login (#10) → `POST /salons` (`is_bookable=false`) →
`PUT /salons/{id}/opening-hours` → `GET /salons/{id}` avec **`is_bookable=true`** et `opening_hours`
normalisé. À placer dans le fichier e2e salon existant (ou nouveau `tests/test_opening_hours_e2e.py`).

### Web dashboard (Vitest)

- `test/opening-hours-domain.test.ts` — validateur TS : **mêmes cas** que le domaine Python (parité
  de la structure et des règles), dont la non-chevauchement et la non-vacuité ;
- `test/set-opening-hours.test.ts` — cas d'usage / mapping d'erreurs de la passerelle ;
- extension de `test/http-salon-gateway.test.ts` — mapping `200/401/403/422/503` ; **le jeton n'est
  jamais journalisé ni renvoyé au client** ;
- extension des tests de routes BFF — `PUT /api/salons/[id]/opening-hours` exige le cookie de session ;
- test d'affichage : le bandeau §8.3 **disparaît** quand `isBookable(salon)` devient vrai.

### Migration

Aucune migration de structure. Le round-trip Alembic existant (job `backend`) reste vert sans
modification.

## Documentation Updates

- **ADR de suivi recommandé** (ex. `docs/adr/0018-configuration-horaires-salon.md`) : le dépôt trace
  chaque décision structurante (0015, 0016, 0017). À couvrir : (a) le **contrat JSONB** des horaires
  (structure `weekly`/`exceptions`, `version`, `timezone`) ; (b) la sémantique retenue de `is_bookable`
  (structurel, inchangé — non-vacuité garantie par la validation) ; (c) sémantique *replace* de la
  route ; (d) fuseau mono-région MVP. Indexer dans `docs/adr/README.md`. *(Alternative : documenter le
  contrat dans la docstring de `domain/opening_hours.py` + le README backend si l'on juge l'ADR
  disproportionné — voir Open Questions.)*
- **`README.md` (racine)** : module 2 « Gestion des salons » — mentionner
  `PUT /salons/{id}/opening-hours` et le fait qu'enregistrer des horaires rend le salon réservable
  (§8.3). Mettre à jour la section 6 (M2 : #16 livré après #15).
- **`backend/README.md`** : la nouvelle route et un exemple du contrat JSONB d'horaires.
- **`web-dashboard/README.md`** : la section Paramètres → éditeur d'horaires (jours, pauses, jours
  exceptionnels) et la disparition du bandeau §8.3.
- **OpenAPI** : `summary`/`responses`/docstrings de la route (patron du module) — documentation
  publique de l'API.

## Risks and Open Questions

### Décisions à confirmer

1. **Sémantique de `is_bookable` — structurel vs. « au moins un créneau ouvert »** *(recommandé :
   garder structurel)*. Aujourd'hui `is_bookable = ACTIVE et bool(opening_hours)`. Ce spec **ne
   modifie pas** cette signature (elle est figée par ADR-0017 et partagée avec le front) et garantit,
   par la **règle de non-vacuité** de la validation, qu'aucun horaire « vide » n'est persisté — donc
   `bool(opening_hours)` reste fiable. **Alternative** : rendre `is_bookable` sémantique (vérifier
   qu'il existe un intervalle ouvert), mais cela déborde vers la logique de réservation (#21+) et
   impose de synchroniser la règle avec le front. **À confirmer** ; recommandation : rester structurel.

2. **Faut-il pouvoir « déconfigurer » les horaires (repasser à non réservable) ?** Le PRD §8.3 parle
   d'un salon « sans horaire ». Une route `DELETE /salons/{id}/opening-hours` (remise à `NULL`) rendrait
   le salon de nouveau non réservable. **Recommandation : hors périmètre au MVP** — la désactivation
   d'un salon passe par `status` (`SALON_SET_STATUS`, admin, M5/M6), pas par la suppression d'horaires.
   À confirmer.

3. **Fuseau horaire dans l'UI.** MVP mono-région (Côte d'Ivoire, `Africa/Abidjan`). **Recommandation :
   stocker `timezone` avec la valeur par défaut, non éditable dans l'UI**, pour que #21 dispose déjà du
   champ. Rendre le champ éditable relève d'une évolution multi-région (hors MVP).

4. **Sémantique *replace* vs *patch*.** `PUT` remplace l'intégralité des horaires (idempotent, simple à
   raisonner). **Recommandation : replace**. Un `PATCH` par jour serait plus granulaire mais ambigu
   (fusion des exceptions ?) — non retenu au MVP.

5. **ADR dédié ou docstring ?** Le contrat JSONB est une décision structurante (consommée par #21+,
   #18/#19). **Recommandation : ADR-0018** (cohérent avec 0017), mais la doc peut se limiter à la
   docstring de `domain/opening_hours.py` + README si l'équipe juge l'ADR disproportionné.

### Risques

- **Divergence de parité front/back du validateur d'horaires.** Deux implémentations (Python + TS) des
  mêmes règles risquent de diverger. Mitigation : tests de parité explicites (mêmes cas des deux côtés),
  et le **backend reste l'autorité** (le front valide pour l'UX, le back pour la correction).
- **Chevauchement d'intervalles subtils** (ex. `08:00–12:00` et `12:00–14:00` — adjacents mais non
  chevauchants) : décider si l'adjacence stricte est autorisée. **Recommandation : autoriser
  l'adjacence** (`end == start` du suivant), interdire seulement le vrai chevauchement (`start <
  end_précédent`). À figer par test.
- **Passage minuit** (`22:00–02:00`) : non supporté au MVP (un intervalle ne franchit pas `24:00`).
  Un salon ouvrant après minuit devra le modéliser en deux jours — **limitation assumée**, à
  documenter. À confirmer si un cas d'usage réel l'exige.
- **Volumétrie JSONB** : sans borne, un client pourrait soumettre des milliers d'exceptions.
  Mitigation : bornes de robustesse dans le validateur (voir *Security* §4).
- **Le dashboard suppose 0 ou 1 salon** dans l'écran Paramètres (héritage #15). Si un gérant a N
  salons (ADR-0017 : N salons sans limite au MVP), l'éditeur d'horaires devra suivre le même sélecteur
  que la fiche — à cadrer avec l'évolution multi-salon de l'UI (déjà notée dans #15).

## Implementation Checklist

> Ordre conçu pour vérifier chaque étape isolément (domaine → application → adapters → UI).

### Backend — domaine & application

1. Créer `domain/opening_hours.py` : `DAY_KEYS`, `OPENING_HOURS_SCHEMA_VERSION`, `DEFAULT_TIMEZONE`,
   dataclasses (`TimeInterval`, `DaySchedule`, `ExceptionalDay`, `OpeningHours`), et les fonctions
   pures `parse_opening_hours`, `validate_opening_hours`, `to_jsonb`. Zéro import framework/I/O.
2. Ajouter `InvalidOpeningHours` à `domain/errors.py` (message neutre) + `__all__`.
3. Écrire `tests/test_domain_opening_hours.py` (jours/pauses/fermés/exceptions/normalisation/bornes/
   non-vacuité). ✅ vert avant de continuer.
4. Ajouter `set_opening_hours` au port `application/ports/salon_repository.py` (docstring).
5. Ajouter le cas d'usage `SetOpeningHours` à `application/salons.py` (validation avant écriture,
   `SalonNotFound` si absent) + `__all__`. Écrire `tests/test_set_opening_hours_usecase.py`
   (étendre `FakeSalonRepository` avec `set_opening_hours`).

### Backend — persistance

6. Implémenter `set_opening_hours` dans
   `adapters/outbound/persistence/salon_repository.py` (patron `set_logo` : `flush()` sans `commit()`,
   `SalonNotFound` si absent).

### Backend — adapter entrant

7. Ajouter à `adapters/inbound/salons.py` les schémas Pydantic (`TimeIntervalModel`,
   `ExceptionalDayModel`, `OpeningHoursRequest`) et la route
   `PUT /salons/{salon_id}/opening-hours` (`require_permission(SALON_UPDATE)` + `require_salon_scope`),
   renvoyant un `SalonResponse` complet (via `GetSalon`) avec `is_bookable=true`.
8. Traduire les erreurs : `InvalidOpeningHours` → `422`, `SalonNotFound` → `404` (après portée) ;
   jamais `str(exc)` sur un refus RBAC. **Ne pas** toucher à `PUBLIC_ROUTE_PATHS`.
9. Écrire `tests/test_salon_opening_hours_api.py` (matrice RBAC, isolation `403` générique, succès
   `is_bookable=true`, validation `422`, replace) + parcours e2e.
10. Vérifier : `unprotected_routes(app)` vide, `test_domain_permissions.py` et `test_secrets_policy.py`
    verts et inchangés, `ruff check` propre.

### Web dashboard

11. `src/domain/salon/opening-hours.ts` : type `OpeningHours` + `validateOpeningHours` (**parité
    stricte** avec le backend).
12. Étendre `src/application/ports/salon-gateway.ts` (`setOpeningHours` + `SetOpeningHoursResult`) et
    `src/adapters/api/http-salon-gateway.ts` (appel `PUT` côté serveur, jeton du cookie, aucune
    journalisation de jeton/PII).
13. Route BFF `app/api/salons/[id]/opening-hours/route.ts` (`PUT`, cookie de session, mapping
    `200/401/403/422/503`).
14. `src/adapters/ui/opening-hours-form.tsx` : éditeur 7 jours (fermé/ouvert, intervalles + pauses,
    jours exceptionnels), validation client avant envoi.
15. Intégrer l'éditeur dans `app/(gerant)/gerant/parametres/page.tsx` ; vérifier que le bandeau §8.3
    disparaît après enregistrement (`isBookable(salon)` vrai).
16. Tests Vitest : `opening-hours-domain`, `set-opening-hours`, extension `http-salon-gateway` et
    routes BFF ; `npm run lint`, `npm test`, `npm run build`.

### Documentation

17. Rédiger l'ADR de suivi (contrat JSONB + sémantique `is_bookable` + replace + fuseau) et l'indexer
    dans `docs/adr/README.md` *(ou documenter dans la docstring + README si l'ADR est jugé
    disproportionné — décision 5)*.
18. Mettre à jour `README.md` (racine, module 2 + section 6), `backend/README.md`,
    `web-dashboard/README.md`.
19. Relire : rien dans la doc ne doit laisser entendre que la **réservation** (#21+) ou le **calcul de
    disponibilité** existent — ce spec livre l'**enregistrement** des horaires et l'activation de
    `is_bookable`, pas l'application des horaires à la réservation.

### Vérification finale

20. `scripts/test-gate.sh` vert (parité CI : `pytest` + `npm test` + `flutter test`).
