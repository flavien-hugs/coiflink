# Middleware d'autorisation & RBAC (rôles, permissions, isolation par salon)

> **Issue :** #12 — *Middleware d'autorisation & RBAC* · `Must` · `M` · `security`
> **Dépend de :** #10 (connexion JWT + refresh — livrée)
> **Bloque :** #13 (comptes employés), #14 (dashboard gérant), #28 (fiches clients), #52 (audit sécurité)
> **Références :** PRD §4 / §4.1 (permissions par rôle), §11.2 (autorisation & isolation),
> §11.4 (journalisation), §18 (Sprint 1 — « Middleware permissions ») ·
> [ADR-0008](../docs/adr/0008-architecture-hexagonale.md) (hexagonal),
> [ADR-0013](../docs/adr/0013-connexion-jwt-refresh-anti-bruteforce.md) (JWT/claims)

---

## Problem Statement

Le backend sait aujourd'hui **authentifier** (inscrire #8/#9, connecter #10, réinitialiser #11) mais
**n'autorise rien** : aucun endpoint ne lit l'en-tête `Authorization`, aucun code ne consomme les
claims d'un jeton d'accès, et aucune route n'est protégée. Concrètement, dans
`backend/coiflink_api/` :

- `JwtTokenService.decode()` existe mais **n'est appelé nulle part** en dehors de `verify_refresh`
  (rafraîchissement) ; il n'y a **aucun** `verify_access`, donc rien n'empêche aujourd'hui un
  *refresh token* d'être présenté comme jeton d'accès ;
- toutes les routes montées (`/health`, `/auth/*`) sont **publiques par construction** : une nouvelle
  route ajoutée par une issue ultérieure serait **publique par défaut** — l'inverse de l'invariant
  attendu ;
- le modèle de rôles du PRD §4.1 (`CLIENT`, `HAIRDRESSER`, `MANAGER`, `ADMIN`) n'existe que comme
  **énumération** (`domain/enums.py`) et comme **claim `role`** dans le JWT : aucune table de
  permissions, aucune règle de portée ;
- l'isolation multi-tenant du PRD §11.2 est **garantie en base** (FK composites `(salon_id, id)` dans
  `models.py`) mais **pas au niveau applicatif** : rien n'empêcherait un gérant d'adresser le
  `salon_id` d'un concurrent dans une future requête.

Sans cette brique, chaque issue métier (#13, #15, #21, #28…) devrait réinventer ses contrôles
d'accès — avec un risque élevé d'oubli et de fuite inter-salons. L'issue #12 pose donc **la couche
d'autorisation commune**, avant que la moindre ressource métier ne soit exposée.

---

## Goals

1. **Identité de requête** : un `Principal` (id, rôle, statut) résolu depuis un `Authorization:
   Bearer <access_token>` valide, avec **relecture du rôle et du statut en base** à chaque requête
   (un compte suspendu ou rétrogradé ne peut plus agir, même avec un jeton encore valide).
2. **Rejet du mauvais type de jeton** : un *refresh token* présenté comme jeton d'accès est refusé
   (`type == "access"` exigé) — `TokenService.verify_access` ajouté au port et à l'adapter.
3. **Deny-by-default** : toute route est protégée **sauf** si son chemin figure dans une **liste
   d'exemption publique explicite** (`/health`, `/auth/register*`, `/auth/login`, `/auth/refresh`,
   `/auth/password/reset/*`, documentation OpenAPI). Une route ajoutée demain sans rien déclarer est
   **fermée**, pas ouverte.
4. **Matrice de permissions du PRD §4.1** modélisée dans le **domaine** (pure, sans framework) :
   `Permission` (verbe métier) × `Role` → l'unique source de vérité des droits.
5. **Gardes réutilisables** : dépendances FastAPI `require_roles(...)`, `require_permission(...)` et
   une garde de **portée salon** (`salon_id`) que les issues M2–M5 branchent sans ré-implémenter de
   logique.
6. **Isolation par salon (§11.2)** : un gérant n'accède qu'aux salons dont il est propriétaire ; un
   coiffeur qu'à son périmètre ; un client qu'à ses propres données ; l'`ADMIN` supervise la
   plateforme. Accès inter-salons **bloqué**.
7. **Tests d'autorisation négatifs par rôle** : matrice paramétrée (rôle × route → statut attendu),
   plus un **test d'invariant** qui énumère `app.routes` et échoue si une route n'est ni publique
   (liste explicite) ni protégée — la garantie deny-by-default devient **exécutable**.
8. **Une route protégée réelle** (`GET /auth/me`) qui prouve la chaîne de bout en bout et sert de
   garde d'authentification au dashboard (#14).

---

## Non-Goals

- **Créer des endpoints métier** (salons, prestations, RDV, caisse) : ils appartiennent à #15+.
  #12 livre les **gardes** et une seule route (`/auth/me`) ; le reste est câblé par les issues qui
  exposent les ressources.
- **Créer des comptes employés / coiffeurs** (#13) — donc **ne pas** introduire la table
  d'appartenance salarié↔salon ici (cf. *Risks and Open Questions*).
- **Garde de route côté web-dashboard** (redirection d'un non-authentifié) : c'est le périmètre de
  **#14** ; #12 fournit le contrat HTTP (`401`/`403`, `GET /auth/me`) qu'il consommera.
- **Invalidation immédiate des jetons déjà émis** après reset de mot de passe
  (`password_changed_at` / `token_version`) : suivi ouvert d'[ADR-0014](../docs/adr/0014-reinitialisation-mot-de-passe-otp.md),
  volontairement laissé hors de #12 (voir *Risks*).
- **Journalisation d'audit des accès sensibles** (PRD §11.4) : périmètre de **#52**. #12 pose
  au plus un log de refus **sans PII ni jeton** (voir *Security & Privacy*).
- **Révocation/blacklist de jetons, OAuth/OIDC, permissions par salon configurables** : hors MVP.
- **Rate-limiting des routes protégées** : l'anti-bruteforce (#10) reste cantonné à la connexion.

---

## Relevant Repository Context

### Stack (figée — aucune décision de stack ouverte)

Backend **Python ≥ 3.12 / FastAPI** ([ADR-0003](../docs/adr/0003-backend-fastapi.md)), **architecture
hexagonale** ([ADR-0008](../docs/adr/0008-architecture-hexagonale.md)), **SQLAlchemy 2.0 + Alembic +
psycopg 3 / PostgreSQL 16** ([ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)),
**PyJWT HS256** ([ADR-0013](../docs/adr/0013-connexion-jwt-refresh-anti-bruteforce.md)).
Tests : `pytest` (+ `httpx`/`TestClient`), lint `ruff` (`line-length = 100`). **Aucune nouvelle
dépendance n'est nécessaire** : les utilitaires de sécurité de FastAPI (`fastapi.security.HTTPBearer`)
et PyJWT suffisent.

### Découpage hexagonal existant (à respecter)

```
backend/coiflink_api/
├── domain/          # pur : enums, user, credentials, tokens, otp, errors  (zéro import framework)
├── application/     # cas d'usage (registration, authentication, password_reset) + ports/ (Protocol)
├── adapters/
│   ├── inbound/     # health.py, auth.py (routers FastAPI)
│   └── outbound/    # persistence/ (SQLAlchemy), security/ (argon2, JWT, rate limiter), notifications/
├── config.py        # AuthConfig lue de l'environnement (aucun secret en dur)
└── main.py          # composition root : app.state + include_router
```

Conventions établies par #8/#10/#11, à reproduire :

- **Le domaine ne connaît ni FastAPI ni SQLAlchemy** ; l'application ne dépend que de **ports**
  (`typing.Protocol`) ; seuls les adapters connaissent PyJWT/psycopg.
- Les **erreurs de domaine** (`domain/errors.py`) sont neutres ; **l'adapter entrant** les traduit en
  codes HTTP.
- Le **composition root** (`main.py`) dépose les singletons sur `app.state` ; les dépendances FastAPI
  les relisent (`getattr(request.app.state, ...)`) avec un **repli sûr**.
- Les **dépendances FastAPI sont surchargeables en test** (`app.dependency_overrides`) — c'est le
  mécanisme utilisé par `tests/test_login_api.py`, `test_password_reset_api.py`.
- **Aucun secret ni PII** dans les messages, les logs ou les réponses (PRD §11.1/§11.3).
- Docstrings de module explicites, en français, référençant l'issue et l'ADR.

### Ce qui existe déjà et sera réutilisé

| Élément | Fichier | Rôle dans #12 |
| --- | --- | --- |
| `Role` (CLIENT/HAIRDRESSER/MANAGER/ADMIN), `UserStatus` | `domain/enums.py` | source de vérité des rôles |
| `TokenClaims` (`sub`, `role`, `type`, `jti`, `iat`, `exp`), `ACCESS`/`REFRESH` | `domain/tokens.py` | claims consommés (**aucune PII** — invariant à préserver) |
| Port `TokenService` (`decode`, `verify_refresh`) | `application/ports/token_service.py` | **étendu** avec `verify_access` |
| `JwtTokenService` (HS256, `algorithms=[...]`, `require: exp/iat/sub`) | `adapters/outbound/security/jwt_token_service.py` | **étendu** avec `verify_access` |
| Port `UserRepository` (`find_by_id` → `UserCredentials`) | `application/ports/user_repository.py` | relecture rôle/statut ; **étendu** pour `/auth/me` |
| `SqlUserRepository` | `adapters/outbound/persistence/user_repository.py` | implémentation |
| `Salon.owner_id` (FK `users.id`) | `adapters/outbound/persistence/models.py` | **seule** source de vérité actuelle du rattachement gérant→salon |
| `get_session` (session par requête, commit/rollback) | `adapters/outbound/persistence/session.py` | dépendance des gardes qui lisent la base |
| `app.state.token_service` (`None` si `JWT_SECRET` absent → `503`) | `main.py` | réutilisé tel quel |
| Fakes de test (`FakeAuthUserRepository`, `FakeTokenService`…) | `tests/conftest.py` | **étendus** (voir *Testing Plan*) |

### Statut du reste du dépôt

- `web-dashboard/` (Next.js) et `app-mobile/` (Flutter) sont des **squelettes** : aucun appel d'API
  authentifié n'y existe. **#12 ne les modifie pas.**
- Le schéma (`models.py` + `migrations/versions/0001_schema_initial.py`) contient `users`, `salons`,
  `services`, `appointments`, `appointment_services`, `customer_profiles`, `payments`,
  `cash_journal`, `notifications`. **Il n'existe aucune table d'appartenance employé↔salon** — point
  structurant traité en *Risks and Open Questions*.

---

## Proposed Implementation

Trois couches, dans l'ordre de dépendance hexagonale (domaine → application → adapters), puis le
câblage.

### 1. Domaine — `coiflink_api/domain/` (pur, sans framework)

**`domain/permissions.py` (nouveau)** — la matrice du PRD §4.1, source de vérité unique.

- `class Permission(_StrEnum)` : un membre par **verbe métier** du §4.1, nommé
  `<RESSOURCE>_<ACTION>`. Jeu minimal proposé (à figer à l'implémentation, dérivé mot à mot du PRD) :

  | Domaine | Permissions |
  | --- | --- |
  | Salon | `SALON_CREATE`, `SALON_UPDATE`, `SALON_READ_OWN`, `SALON_READ_ANY`, `SALON_SET_STATUS` |
  | Prestations | `SERVICE_MANAGE`, `SERVICE_READ` |
  | RDV | `APPOINTMENT_BOOK`, `APPOINTMENT_READ_OWN`, `APPOINTMENT_READ_ASSIGNED`, `APPOINTMENT_READ_SALON`, `APPOINTMENT_MANAGE`, `APPOINTMENT_UPDATE_STATUS` |
  | Employés | `EMPLOYEE_MANAGE` |
  | Clients | `CUSTOMER_MANAGE` |
  | Caisse | `PAYMENT_RECORD`, `CASH_JOURNAL_READ` |
  | Statistiques | `STATS_READ_SALON`, `STATS_READ_PLATFORM` |
  | Comptes | `USER_MANAGE` |

- `ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]]` — le tableau du §4.1, **exhaustif et
  fermé** : tout rôle absent de la table n'a **aucune** permission (deny-by-default jusque dans le
  domaine). `ADMIN` n'est **pas** un joker implicite : ses permissions sont listées (supervision
  plateforme), ce qui rend le privilège auditable.
- `def permissions_for(role: str) -> frozenset[Permission]` : tolérant à un rôle inconnu
  (jeton forgé/rôle retiré) → `frozenset()`.

**`domain/principal.py` (nouveau)**

```python
@dataclass(frozen=True)
class Principal:
    """Utilisateur authentifié d'une requête. Ne porte AUCUNE PII (ni nom, ni téléphone, ni e-mail)."""
    id: uuid.UUID
    role: str
    status: str

    @property
    def is_active(self) -> bool: ...          # status == UserStatus.ACTIVE
    def has_permission(self, permission: Permission) -> bool: ...
    def has_role(self, *roles: Role) -> bool: ...
```

**`domain/access.py` (nouveau)** — règles de portée du §11.2, **fonctions pures** (aucune I/O) :

```python
def can_access_salon(principal: Principal, salon_id: uuid.UUID, scope: SalonScope) -> bool:
    """ADMIN : toujours vrai. MANAGER/HAIRDRESSER : salon_id ∈ scope.salon_ids. CLIENT : faux."""

def can_access_appointment(principal: Principal, appointment: AppointmentRef, scope: SalonScope) -> bool:
    """CLIENT : appointment.client_id == principal.id.
       HAIRDRESSER : appointment.hairdresser_id == principal.id (« son planning », §11.2).
       MANAGER : appointment.salon_id ∈ scope.salon_ids.  ADMIN : vrai."""
```

où `SalonScope` est un `frozenset[uuid.UUID]` encapsulé (dataclass frozen) et `AppointmentRef` un
petit *value object* (`salon_id`, `client_id`, `hairdresser_id | None`) que les issues RDV
alimenteront. Ces fonctions sont **testables sans base ni HTTP** — c'est là que vit la règle métier.

**`domain/errors.py` (modifier)** — deux erreurs neutres :

- `class NotAuthenticated(DomainError)` — aucune identité exploitable (jeton absent/invalide/expiré,
  compte introuvable).
- `class PermissionDenied(DomainError)` — identité valide, droit ou portée insuffisants (rôle,
  permission, **accès inter-salons**). Message **générique**, jamais l'`id` visé.

### 2. Application — `coiflink_api/application/`

**`application/ports/token_service.py` (modifier)** — ajouter au `Protocol` :

```python
def verify_access(self, token: str) -> TokenClaims:
    """Décode et exige `type == "access"` ; lève InvalidToken sinon (un refresh
    token ne peut jamais servir de jeton d'accès)."""
```

**`application/ports/user_repository.py` (modifier)** — ajouter :

```python
def find_user_by_id(self, user_id: uuid.UUID | str) -> User | None:
    """Entité **publique** (sans condensat) pour `GET /auth/me`. `None` si l'id est
    inconnu ou illisible (jeton altéré) — jamais d'exception remontée."""
```

> `find_by_id` (existant, → `UserCredentials`) reste l'appel de la **résolution du principal** :
> il porte déjà `role` + `status`, tout ce qu'il faut pour autoriser, et rien de plus.

**`application/ports/salon_scope_repository.py` (nouveau)** — le port d'isolation :

```python
class SalonScopeRepository(Protocol):
    def salon_ids_for(self, principal_id: uuid.UUID, role: str) -> frozenset[uuid.UUID]:
        """Salons sur lesquels ce compte a une portée. MANAGER : salons dont il est
        propriétaire (`salons.owner_id`). HAIRDRESSER : salons où il est rattaché.
        CLIENT : ensemble vide (un client n'a **pas** de portée salon ; il accède à
        *ses* RDV, pas aux données d'un salon). ADMIN : non appelé (supervision globale)."""
```

**`application/authorization.py` (nouveau)** — le service de politique, sans HTTP :

```python
class AccessPolicy:
    """Applique les règles §4.1 (permissions) et §11.2 (portée). Lève PermissionDenied."""
    def __init__(self, scope_repository: SalonScopeRepository) -> None: ...
    def require_roles(self, principal: Principal, *roles: Role) -> None: ...
    def require_permission(self, principal: Principal, permission: Permission) -> None: ...
    def require_salon(self, principal: Principal, salon_id: uuid.UUID) -> SalonScope: ...
    def scope_of(self, principal: Principal) -> SalonScope: ...
```

`require_salon` est **le point unique** qui bloque l'accès inter-salons : il charge la portée via le
port, délègue la décision à `domain.access.can_access_salon`, et lève `PermissionDenied` sinon. Un
`ADMIN` court-circuite le port (portée plateforme).

### 3. Adapters

**`adapters/outbound/security/jwt_token_service.py` (modifier)** — implémenter `verify_access` :
`decode()` puis exiger `claims.type == ACCESS`, sinon `InvalidToken` (miroir exact de
`verify_refresh`, aucun changement de signature ni d'algorithme).

**`adapters/outbound/persistence/salon_scope_repository.py` (nouveau)** — `SqlSalonScopeRepository` :

- `MANAGER` → `SELECT id FROM salons WHERE owner_id = :principal_id` (rattachement **réel**, déjà
  dans le schéma) ;
- `HAIRDRESSER` → **aucune source de vérité en base aujourd'hui** (pas de table employé↔salon).
  Implémentation retenue pour #12, littérale vis-à-vis du §11.2 (« son planning ou les rendez-vous
  qui lui sont assignés ») : `SELECT DISTINCT salon_id FROM appointments WHERE hairdresser_id =
  :principal_id`. **À remplacer par la table d'appartenance quand #13 la créera** — le port ne change
  pas, seule cette requête change. Limite à documenter dans l'ADR : un coiffeur **sans aucun RDV
  assigné** a une portée vide (deny-by-default → il ne voit rien, ce qui est sûr, mais pas
  suffisant à terme).
- `CLIENT` / rôle inconnu → `frozenset()`.

**`adapters/inbound/security.py` (nouveau)** — le cœur du « middleware » côté HTTP. Il ne contient
**aucune règle métier** : il traduit HTTP → domaine et erreurs → statuts.

1. `bearer_scheme = HTTPBearer(auto_error=False)` — schéma déclaré (alimente l'« Authorize » de
   `/docs`, ADR-0003) ; `auto_error=False` pour maîtriser le message et l'en-tête
   `WWW-Authenticate: Bearer`.

2. **`PUBLIC_ROUTE_PATHS: frozenset[str]`** — la **liste d'exemption**, unique et explicite :

   ```python
   PUBLIC_ROUTE_PATHS = frozenset({
       "/health",
       "/auth/register", "/auth/register/manager",
       "/auth/login", "/auth/refresh",
       "/auth/password/reset/request", "/auth/password/reset/confirm",
   })
   ```

   (les routes de documentation `/docs`, `/redoc`, `/openapi.json` sont montées par FastAPI hors du
   système de dépendances et ne sont donc pas concernées ; leur exposition reste inchangée.)

3. **`require_authenticated(request, credentials)` — dépendance globale (deny-by-default).**
   Enregistrée sur l'application (`FastAPI(dependencies=[Depends(require_authenticated)])`), donc
   appliquée à **toutes** les routes de tous les routers :

   - si `request.scope["route"].path ∈ PUBLIC_ROUTE_PATHS` → retour immédiat (pas de session DB
     ouverte : `/health` reste sans I/O) ;
   - sinon : en-tête absent/mal formé → `401` ; `token_service` absent (`JWT_SECRET` non
     configuré) → `503` (cohérent avec `/auth/login`) ; `verify_access` échoue (signature, `alg`,
     `exp`, `type != access`) → `401` avec `WWW-Authenticate: Bearer` et **message générique**
     unique ; sinon dépose `TokenClaims` sur `request.state.token_claims` (évite un second décodage).

   > **Contrôle *stateless* uniquement** (signature + `exp` + `type`) : pas de lecture de base, pour
   > ne pas coûter une session à chaque requête. La fraîcheur rôle/statut est vérifiée juste après
   > par `get_current_principal`, que **toute** route protégée doit déclarer — invariant garanti par
   > le test d'énumération des routes (§ *Testing Plan*).

4. **`get_current_principal(...) -> Principal`** — dépendance des routes protégées : relit les claims
   (`request.state.token_claims`, ou re-décode en repli), charge `UserRepository.find_by_id(sub)` sur
   la session de la requête, puis :
   - compte introuvable (jeton d'un compte supprimé) → `401` générique ;
   - `status != ACTIVE` → **`403`** « Compte désactivé. » (le porteur d'un jeton signé **est** le
     titulaire : l'informer n'est pas une fuite d'énumération) ;
   - sinon retourne `Principal(id, role=<rôle **en base**>, status=...)`.
   **Le `role` du JWT n'est jamais celui qui autorise** : seul le rôle relu en base fait foi (une
   rétrogradation prend effet immédiatement, sans attendre l'expiration du jeton).

5. **Fabriques de gardes** (composables, réutilisées par toutes les issues suivantes) :

   ```python
   def require_roles(*roles: Role) -> Callable[..., Principal]      # 403 si rôle non listé
   def require_permission(permission: Permission) -> Callable[..., Principal]   # 403 (§4.1)
   def require_salon_scope(...) -> Callable[..., SalonScope]        # 403 si salon_id hors portée (§11.2)
   ```

   `require_salon_scope` lit le paramètre de chemin `salon_id` (convention : les ressources à portée
   salon sont montées sous `/salons/{salon_id}/...`), assemble `AccessPolicy` avec
   `SqlSalonScopeRepository` et appelle `policy.require_salon(...)`.

6. **Traduction des erreurs** : `NotAuthenticated` → `401` (+ `WWW-Authenticate: Bearer`),
   `PermissionDenied` → `403`. **Messages constants et génériques** (jamais `str(exc)`, jamais l'id
   visé) : `_UNAUTHENTICATED_DETAIL = "Authentification requise."`,
   `_FORBIDDEN_DETAIL = "Accès refusé."`.

**`adapters/inbound/auth.py` (modifier)** — ajouter **une** route protégée réelle :

```
GET /auth/me → 200 UserResponse   (le compte du porteur du jeton ; 401 sans jeton valide, 403 si inactif)
```

Elle réutilise le `UserResponse` existant (déjà sans secret) et sert de **garde d'authentification**
au dashboard (#14) et à l'app mobile.

### 4. Composition root — `main.py` (modifier)

```python
app = FastAPI(title=APP_NAME, dependencies=[Depends(require_authenticated)])
```

Aucun autre changement : `token_service` (déjà sur `app.state`) est relu par les gardes ; aucune
nouvelle variable d'environnement, **aucun nouveau secret**.

### 5. Ordre d'exécution résultant (route protégée)

```
Requête ──▶ [dépendance globale] require_authenticated   → 401 / 503   (deny-by-default, stateless)
        ──▶ [dépendance de route] get_current_principal  → 401 / 403   (relecture rôle+statut en base)
        ──▶ [garde] require_roles / require_permission   → 403         (matrice PRD §4.1)
        ──▶ [garde] require_salon_scope                  → 403         (isolation PRD §11.2)
        ──▶ handler
```

---

## Affected Files / Packages / Modules

### À créer

| Fichier | Contenu |
| --- | --- |
| `backend/coiflink_api/domain/permissions.py` | `Permission`, `ROLE_PERMISSIONS` (PRD §4.1), `permissions_for` |
| `backend/coiflink_api/domain/principal.py` | `Principal` (sans PII) |
| `backend/coiflink_api/domain/access.py` | `SalonScope`, `AppointmentRef`, `can_access_salon`, `can_access_appointment` (§11.2) |
| `backend/coiflink_api/application/ports/salon_scope_repository.py` | port `SalonScopeRepository` |
| `backend/coiflink_api/application/authorization.py` | `AccessPolicy` |
| `backend/coiflink_api/adapters/outbound/persistence/salon_scope_repository.py` | `SqlSalonScopeRepository` |
| `backend/coiflink_api/adapters/inbound/security.py` | `PUBLIC_ROUTE_PATHS`, `require_authenticated`, `get_current_principal`, `require_roles`, `require_permission`, `require_salon_scope` |
| `backend/tests/test_permissions_matrix.py` | matrice §4.1 (unitaire, domaine) |
| `backend/tests/test_access_rules.py` | règles de portée §11.2 (unitaire, domaine) |
| `backend/tests/test_authorization_policy.py` | `AccessPolicy` (unitaire, avec fake scope repo) |
| `backend/tests/test_security_dependencies.py` | gardes HTTP : 401/403/503, matrice négative par rôle |
| `backend/tests/test_deny_by_default.py` | invariant : toute route est publique-listée **ou** protégée |
| `backend/tests/test_rbac_e2e.py` | e2e PostgreSQL : isolation inter-salons réelle |
| `docs/adr/0015-autorisation-rbac-deny-by-default.md` | ADR de la décision |

### À modifier

| Fichier | Modification |
| --- | --- |
| `backend/coiflink_api/domain/errors.py` | `NotAuthenticated`, `PermissionDenied` (+ `__all__`) |
| `backend/coiflink_api/domain/tokens.py` | docstring : les claims sont désormais **consommés** par le RBAC |
| `backend/coiflink_api/application/ports/token_service.py` | `verify_access` |
| `backend/coiflink_api/application/ports/user_repository.py` | `find_user_by_id` |
| `backend/coiflink_api/adapters/outbound/security/jwt_token_service.py` | `verify_access` |
| `backend/coiflink_api/adapters/outbound/persistence/user_repository.py` | `find_user_by_id` |
| `backend/coiflink_api/adapters/inbound/auth.py` | route `GET /auth/me` |
| `backend/coiflink_api/main.py` | dépendance globale `require_authenticated` |
| `backend/tests/conftest.py` | fakes : `verify_access`, `find_user_by_id`, `FakeSalonScopeRepository`, fabrique de jeton de test |
| `backend/README.md` | section « Autorisation & RBAC » (rôles, gardes, deny-by-default, ajout d'une route) |
| `README.md` | §3/§4 : mention du RBAC livré (#12) |
| `docs/adr/README.md` | index + fermeture du suivi correspondant |

**Non touchés :** `web-dashboard/`, `app-mobile/`, `deploy/`, `migrations/` (aucune migration —
voir *Data Model*).

---

## API / Interface Changes

### Nouvelle route

| Méthode | Chemin | Auth | Réponses |
| --- | --- | --- | --- |
| `GET` | `/auth/me` | `Authorization: Bearer <access_token>` | `200 UserResponse` · `401` (jeton absent/invalide/expiré/refresh) · `403` (compte non `ACTIVE`) · `503` (`JWT_SECRET` non configuré) |

`UserResponse` (schéma existant) : `id`, `full_name`, `phone`, `email`, `role`, `status`,
`created_at`. **Aucun secret** (ni `password_hash`, ni jeton).

### Contrat d'autorisation transverse (nouveau, s'applique à toute route future)

| Situation | Statut | Corps / en-têtes |
| --- | --- | --- |
| Route non publique, en-tête `Authorization` absent ou mal formé | `401` | `{"detail": "Authentification requise."}` + `WWW-Authenticate: Bearer` |
| Jeton invalide, expiré, altéré, `alg` inattendu, ou **refresh présenté comme accès** | `401` | idem (message **identique** — aucune distinction du motif) |
| Compte du jeton introuvable | `401` | idem |
| Compte non `ACTIVE` (INACTIVE/SUSPENDED) | `403` | `{"detail": "Compte désactivé."}` |
| Rôle ou permission insuffisants (§4.1) | `403` | `{"detail": "Accès refusé."}` |
| **Accès inter-salons** (salon hors portée, §11.2) | `403` | `{"detail": "Accès refusé."}` — message **identique** au cas précédent |
| `JWT_SECRET` non configuré | `503` | cohérent avec `/auth/login` (#10) |

### Contrat interne (pour les issues suivantes)

Nouvelles interfaces publiques du paquet, **à documenter** dans `backend/README.md` :

```python
from coiflink_api.adapters.inbound.security import (
    get_current_principal, require_roles, require_permission, require_salon_scope,
)

@router.get("/salons/{salon_id}/appointments")
def list_appointments(
    salon_id: uuid.UUID,
    scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[Principal, Depends(require_permission(Permission.APPOINTMENT_READ_SALON))],
): ...
```

**Aucun changement** sur `/health`, `/auth/register`, `/auth/register/manager`, `/auth/login`,
`/auth/refresh`, `/auth/password/reset/*` (ces routes restent publiques et leurs contrats
inchangés — vérifié par les suites existantes, qui doivent rester vertes sans modification).

---

## Data Model / Protocol Changes

**Aucune migration Alembic.** #12 **lit** le schéma existant, il ne le modifie pas :

- rattachement gérant→salon : `salons.owner_id` (existant, FK `users.id`) ;
- périmètre coiffeur : `appointments.hairdresser_id` (existant) ;
- rôle/statut : `users.role`, `users.status` (existants, contraints par `CHECK` dérivés du domaine).

**Format des jetons inchangé** (ADR-0013) : `sub`, `role`, `type`, `iat`, `exp`, `jti` — **aucun
nouveau claim**, **aucune PII ajoutée**. #12 ajoute seulement une **vérification** (`type == access`)
côté consommation.

Deux évolutions de schéma sont **volontairement différées** (voir *Risks*) : la table d'appartenance
employé↔salon (#13) et `users.password_changed_at` / `token_version` (suivi ADR-0014).

---

## Security & Privacy Considerations

Contraintes documentées touchées : **PRD §11.1** (authentification), **§11.2** (autorisation —
l'objet même de l'issue), **§11.3** (données personnelles), **§11.4** (journalisation),
**ADR-0011** (secrets hors dépôt), **ADR-0013** (JWT sans PII).

1. **Deny-by-default, vérifiable.** L'exemption publique est une **liste blanche unique** en dur dans
   `adapters/inbound/security.py`, et un test échoue si une route la contourne. Une route ajoutée
   sans réflexion est **fermée**, jamais ouverte.
2. **Le JWT n'est pas une source d'autorité sur le rôle.** Le rôle et le statut sont **relus en base**
   à chaque requête protégée : rétrogradation, suspension ou désactivation d'un compte prennent effet
   **immédiatement**, sans attendre l'expiration du jeton d'accès (15 min par défaut).
3. **Séparation stricte accès / refresh.** `verify_access` exige `type == "access"` : un refresh token
   (TTL 30 j) **ne peut pas** ouvrir une ressource protégée. `decode()` impose déjà
   `algorithms=[HS256]` et `require: exp/iat/sub` (rejet de `alg=none` et de la confusion
   d'algorithme).
4. **Isolation inter-salons appliquée côté serveur**, jamais dérivée d'un paramètre client : la portée
   vient **de la base** (`salons.owner_id`), le `salon_id` de la requête n'est qu'une **cible à
   valider**. Défense en profondeur : les FK composites `(salon_id, id)` du schéma restent le dernier
   rempart en base.
5. **Aucune fuite par message d'erreur.** `401` et `403` portent des **messages constants**
   (jamais `str(exc)`, jamais l'`id` d'un salon ou d'un compte). Un `403` « Accès refusé. » est
   **identique** pour un rôle insuffisant et pour un accès inter-salons : le refus ne renseigne pas
   sur ce qui existe chez autrui.
6. **Aucun secret, aucune PII journalisés.** Si un log de refus est ajouté (utile pour #52), il ne
   contient **que** : `user_id` (UUID pseudonyme), `role`, méthode + chemin de la route, décision.
   **Jamais** : jeton (même tronqué), en-tête `Authorization`, mot de passe, téléphone, e-mail, nom.
   La journalisation d'audit complète (§11.4) reste **le périmètre de #52**.
7. **Pas de nouveau secret ni de nouvelle variable d'environnement** : `JWT_SECRET` (ADR-0011) reste
   l'unique secret de la chaîne, lu de l'environnement, jamais journalisé ni renvoyé.
8. **`Principal` ne transporte aucune PII** (id, rôle, statut) — invariant à préserver pour ne pas
   contaminer les logs ni les traces.
9. **Budget latence (§12.1, API < 3 s)** : une requête protégée ajoute une vérification HMAC
   (µs) + **une** lecture indexée `users` par PK ; `require_salon_scope` ajoute **une** requête
   indexée (`salons.owner_id` — index à confirmer, cf. *Risks*). Impact négligeable.

---

## Testing Plan

Toutes les suites vivent dans `backend/tests/` (`pytest`, conventions de #6 /
[docs/strategie-de-tests.md](../docs/strategie-de-tests.md)) : **unitaires sans I/O**, tests API avec
`TestClient` + `app.dependency_overrides`, e2e conditionnés à `DATABASE_URL` (skip sinon).

### Unitaires — domaine (aucune I/O)

- `test_permissions_matrix.py` : pour **chacun** des 4 rôles, la liste de permissions correspond au
  PRD §4.1 (test par rôle, listes exhaustives) ; un rôle inconnu (`"ROOT"`) → `frozenset()` ; `CLIENT`
  n'a **aucune** permission de gestion salon/caisse/employés ; `HAIRDRESSER` n'a ni `PAYMENT_RECORD`
  ni `EMPLOYEE_MANAGE` ; `STATS_READ_PLATFORM` / `USER_MANAGE` sont **réservées** à `ADMIN`.
- `test_access_rules.py` : `can_access_salon` — gérant sur **son** salon ✅ / sur **un autre** ❌ ;
  coiffeur hors de sa portée ❌ ; client ❌ (toujours) ; admin ✅. `can_access_appointment` — client
  sur **son** RDV ✅ / sur celui d'un autre ❌ ; coiffeur sur un RDV **assigné** ✅ / non assigné ❌ ;
  gérant sur un RDV de **son** salon ✅ / d'un autre salon ❌.

### Unitaires — application

- `test_authorization_policy.py` (avec `FakeSalonScopeRepository`) : `require_permission` lève
  `PermissionDenied` pour un rôle non habilité ; `require_salon` lève `PermissionDenied` sur un
  `salon_id` hors portée et **ne lève pas** sur un salon de la portée ; `ADMIN` traverse sans appeler
  le port (assertion : le fake n'a **pas** été sollicité).
- `test_jwt_token_service.py` (existant, **étendre**) : `verify_access` accepte un jeton d'accès ;
  **rejette un refresh token** (`InvalidToken`) ; rejette un jeton expiré (`ExpiredToken`), de
  signature invalide, et `alg=none`.

### API — gardes HTTP (`TestClient`, sans base)

`test_security_dependencies.py`, avec une **route de test** montée dans la fixture (et **non** dans
l'application de production) pour exercer les gardes de portée avant l'existence des routes salon :

- **401** : aucun en-tête ; `Authorization: Basic xxx` ; `Bearer` vide ; jeton illisible ; jeton
  expiré ; **refresh token en guise d'accès** ; compte du `sub` introuvable. → dans **tous** les cas :
  même message, présence de `WWW-Authenticate: Bearer`, et **aucune** divulgation du motif.
- **403** : compte `SUSPENDED` / `INACTIVE` porteur d'un jeton valide ; rôle insuffisant ; permission
  absente ; **accès inter-salons**.
- **200** : rôle et portée corrects.
- **503** : `app.state.token_service = None` (JWT non configuré) sur une route protégée.
- **Matrice négative par rôle** (`pytest.mark.parametrize` sur `role × route → statut attendu`) —
  couvre littéralement le critère d'acceptation « tests d'autorisation négatifs par rôle » : chaque
  rôle est testé contre les gardes des **trois autres** rôles.
- **Non-régression** : les routes publiques (`/health`, `/auth/register`, `/auth/register/manager`,
  `/auth/login`, `/auth/refresh`, `/auth/password/reset/*`) répondent **sans** en-tête
  `Authorization` — les suites existantes (`test_auth_api.py`, `test_login_api.py`,
  `test_password_reset_api.py`, `test_health.py`, `test_manager_auth_api.py`) doivent rester vertes
  **sans modification**.

### Invariant — deny-by-default (`test_deny_by_default.py`)

Test **statique** dans l'esprit de `test_secrets_policy.py` : énumérer `main.app.routes` et, pour
chaque `APIRoute`, asserter que **soit** son `path` ∈ `PUBLIC_ROUTE_PATHS`, **soit** la route est
couverte par `require_authenticated` **et** déclare une dépendance de principal. Un second test
vérifie que `PUBLIC_ROUTE_PATHS` ne contient **que** les chemins attendus (toute extension future de
la liste blanche devient un choix **conscient et revu**, pas un effet de bord).

### End-to-end (PostgreSQL requis, `skipif` sans `DATABASE_URL`)

`test_rbac_e2e.py` — dans l'esprit de `test_login_e2e.py` (JWT réel, argon2 réel, dépôt SQL réel,
nettoyage des données avant/après, plage de téléphones réservée) :

1. inscription gérant A → login → `GET /auth/me` → `200`, `role = MANAGER`, **aucun** secret dans le
   corps ;
2. **isolation inter-salons** : insérer un salon pour A et un salon pour un gérant B ; le jeton de A
   sur une ressource à portée `salon_id(B)` → **`403`**, corps **sans** aucune donnée de B ;
3. jeton **altéré** (un caractère de signature modifié) → `401` ;
4. **refresh token** issu du login présenté en `Bearer` → `401` ;
5. compte passé à `SUSPENDED` en base **après** émission du jeton → la requête suivante → `403`
   (preuve que la relecture en base fait autorité, pas le claim).

### Lint / gate

`ruff check` (`line-length = 100`) + `pytest` verts ; le test gate agrégé
(`scripts/test-gate.sh`) doit rester vert sans base de données (les e2e se *skippent*).

---

## Documentation Updates

1. **`docs/adr/0015-autorisation-rbac-deny-by-default.md` (nouveau)** — décisions actées :
   (a) autorisation appliquée par **dépendances FastAPI** (globale + gardes de route) plutôt que par
   un middleware ASGI — testable, injectable, visible dans OpenAPI ; (b) **deny-by-default** par liste
   blanche explicite + test d'invariant ; (c) **rôle relu en base**, le claim `role` n'autorise pas ;
   (d) codes HTTP : `401` (non authentifié) / `403` (rôle, permission, **inter-salons**) / `503` (JWT
   non configuré), messages génériques ; (e) portée coiffeur dérivée des **RDV assignés** en attendant
   la table d'appartenance de #13 — limite et plan de sortie documentés ; (f) conséquences et suivis
   (table d'appartenance, `password_changed_at`, audit §11.4 → #52).
   Suivre le gabarit `docs/adr/0000-processus-et-gabarit-adr.md` (Statut / Date / Décideurs / Issue /
   Référence PRD / Contexte / Options / Décision / Conséquences).
2. **`docs/adr/README.md`** — ajouter l'entrée 0015 à l'index ; mettre à jour la section « décisions
   ouvertes » : le RBAC (#12) est **tranché**, la table d'appartenance employé↔salon devient un suivi
   explicite de **#13**, et le point « invalidation immédiate des jetons » d'ADR-0014 est **reformulé**
   (la relecture du statut en base couvre la **suspension** ; l'invalidation après **reset de mot de
   passe** reste ouverte).
3. **`backend/README.md`** — nouvelle section « Autorisation & RBAC » : les 4 rôles et leurs
   permissions (renvoi PRD §4.1), le contrat `401`/`403`/`503`, `GET /auth/me`, et un **mode d'emploi
   pour l'issue suivante** : « comment protéger une nouvelle route » (déclarer `get_current_principal`,
   `require_permission(...)`, `require_salon_scope` ; **ne jamais** ajouter un chemin à
   `PUBLIC_ROUTE_PATHS` sans revue).
4. **`README.md` (racine)** — §3 (module Authentification) et §4 : signaler le RBAC livré et pointer
   l'ADR-0015.
5. **OpenAPI** — la déclaration `HTTPBearer` fait apparaître le bouton « Authorize » dans `/docs` ;
   chaque route protégée documente `401`/`403` dans ses `responses` (pas de doc manuscrite à
   maintenir).

---

## Risks and Open Questions

1. **Portée du coiffeur : aucune source de vérité en base (à confirmer).** Le schéma n'a **pas** de
   table employé↔salon ; `salons.owner_id` ne couvre que le gérant. Trois options :
   (a) **[recommandé]** dériver la portée coiffeur des **RDV assignés** (`appointments.hairdresser_id`)
   — littéral vis-à-vis du §11.2, **zéro migration**, portée vide (donc refus) pour un coiffeur sans
   RDV ; la table d'appartenance arrive avec **#13** et ne change **que** l'implémentation du port ;
   (b) créer `salon_employees` **dans #12** — plus complet, mais empiète sur #13 et fait sortir une
   issue « security » de son périmètre ;
   (c) ne pas gérer la portée coiffeur maintenant (tout refuser pour `HAIRDRESSER`) — sûr mais rend
   `HAIRDRESSER` inutilisable et repousse les tests d'isolation.
   **Décision à confirmer** avant l'implémentation.
2. **`403` vs `404` sur l'accès inter-salons.** Le plan retient **`403`** (simple, testable,
   directement lisible comme « accès inter-salons bloqué »). Un `404` masquerait l'**existence** du
   salon d'autrui (anti-oracle) ; le risque résiduel du `403` est faible car les `salon_id` sont des
   **UUID** (non énumérables, cf. `models.py`). **À confirmer** — le choix doit être tranché dans
   l'ADR-0015 et **appliqué uniformément** par toutes les issues suivantes.
3. **Aucun chemin de création d'un compte `ADMIN`.** Le rôle existe (`enums.Role`) mais **aucune
   route ne le crée** (l'inscription fixe `CLIENT` ou `MANAGER` côté serveur). Les gardes `ADMIN`
   seront donc **testables** (jeton forgé en test) mais **inatteignables en production** tant qu'un
   *seed*/une procédure d'amorçage n'existe pas. À arbitrer : le documenter comme suivi (probablement
   #52 / une issue d'exploitation) plutôt que d'ajouter une route de création d'admin dans #12.
4. **Jetons déjà émis après un reset de mot de passe.** La relecture du statut en base couvre la
   **suspension** d'un compte, **pas** l'invalidation des jetons après changement de mot de passe
   (suivi ADR-0014 : `password_changed_at` / `token_version` + migration). **Hors périmètre #12** —
   mais `get_current_principal` est **le point d'accroche** naturel (comparer `claims.iat` à
   `password_changed_at`) quand la décision sera prise.
5. **Index sur `salons.owner_id`.** `models.py` déclare la FK mais **pas** d'index explicite (PostgreSQL
   n'indexe pas automatiquement le côté référençant). Avec `require_salon_scope` sur chaque requête à
   portée salon, cette colonne devient un chemin chaud. Ajouter `ix_salons_owner_id` — mais cela
   **implique une migration**, contredisant le « aucune migration » de #12. **À confirmer** :
   l'ajouter ici (migration triviale, `0002`) ou dans #15 (création de salon). Volumétrie MVP faible :
   l'impact réel est marginal à court terme.
6. **Jeu exact de `Permission`.** La liste proposée dérive du PRD §4.1 mais reste une **interprétation**
   (granularité). Un jeu trop fin vieillit mal, trop grossier n'exprime pas §4.1. Point de revue à
   l'implémentation ; les *tests* de matrice figeront le contrat.
7. **Gardes livrées sans consommateur de production.** Hors `/auth/me`, `require_salon_scope` /
   `require_permission` ne seront exercées que par des **routes de test** jusqu'à #15. Risque d'API
   spéculative assumé (c'est la raison d'être d'une issue « middleware » qui précède les ressources) ;
   mitigé par des tests unitaires + API complets. **Ne pas** documenter comme existantes des routes
   métier qui n'existent pas.
8. **Contournement possible de la garde globale.** Une route montée hors du système de dépendances
   (`app.add_route`, montage d'une sous-application ASGI) échapperait à `require_authenticated`. Le
   test d'invariant énumère `app.routes` et doit **aussi** échouer sur une route non-`APIRoute`
   inattendue.
9. **Cohérence avec les autres paquets.** `web-dashboard` (#14) et `app-mobile` devront envoyer
   `Authorization: Bearer` et gérer `401` (re-login/refresh) / `403` (accès refusé). #12 ne fournit que
   le contrat serveur ; l'alignement client est à porter par les issues concernées.

---

## Implementation Checklist

> Ordre imposé par l'hexagonal : domaine → application → adapters → câblage → tests → docs.
> Vérifier après chaque étape : `cd backend && ruff check . && pytest`.

**Préalables (décisions à confirmer avant de coder)**
- [ ] Trancher la **portée coiffeur** (risque 1) — recommandation : dérivée des RDV assignés, table d'appartenance reportée à #13.
- [ ] Trancher **`403` vs `404`** sur l'accès inter-salons (risque 2) — recommandation : `403`.
- [ ] Trancher l'ajout (ou non) de `ix_salons_owner_id` (risque 5) — par défaut : **pas de migration dans #12**.

**Domaine (pur — aucun import FastAPI/SQLAlchemy)**
- [ ] `domain/permissions.py` : `Permission`, `ROLE_PERMISSIONS` (PRD §4.1, exhaustif), `permissions_for` (rôle inconnu → vide).
- [ ] `domain/principal.py` : `Principal` (id, role, status ; `is_active`, `has_role`, `has_permission`) — **aucune PII**.
- [ ] `domain/access.py` : `SalonScope`, `AppointmentRef`, `can_access_salon`, `can_access_appointment` (§11.2).
- [ ] `domain/errors.py` : `NotAuthenticated`, `PermissionDenied` (+ `__all__`).
- [ ] Tests : `test_permissions_matrix.py`, `test_access_rules.py` (verts avant de continuer).

**Application (ports + politique)**
- [ ] `ports/token_service.py` : `verify_access` (docstring : refuse un refresh).
- [ ] `ports/user_repository.py` : `find_user_by_id` (entité publique, sans condensat).
- [ ] `ports/salon_scope_repository.py` : `SalonScopeRepository`.
- [ ] `application/authorization.py` : `AccessPolicy` (`require_roles`, `require_permission`, `require_salon`, `scope_of` ; `ADMIN` court-circuite le port).
- [ ] Test : `test_authorization_policy.py`.

**Adapters sortants**
- [ ] `security/jwt_token_service.py` : `verify_access` (miroir de `verify_refresh`).
- [ ] `persistence/user_repository.py` : `find_user_by_id`.
- [ ] `persistence/salon_scope_repository.py` : `SqlSalonScopeRepository` (MANAGER → `salons.owner_id` ; HAIRDRESSER → `DISTINCT appointments.salon_id` ; sinon vide).
- [ ] Test : étendre `test_jwt_token_service.py` (refresh-en-accès, expiré, `alg=none`).

**Adapter entrant (les gardes)**
- [ ] `adapters/inbound/security.py` : `bearer_scheme`, `PUBLIC_ROUTE_PATHS`, `require_authenticated` (stateless, exemption publique, `401`/`503`), `get_current_principal` (relecture rôle/statut en base ; `401` / `403` inactif), `require_roles`, `require_permission`, `require_salon_scope` ; messages **constants et génériques**, `WWW-Authenticate: Bearer` sur les `401`.
- [ ] `adapters/inbound/auth.py` : `GET /auth/me` (200 `UserResponse`, `401`/`403` documentés).

**Câblage**
- [ ] `main.py` : `FastAPI(title=APP_NAME, dependencies=[Depends(require_authenticated)])` — aucune nouvelle variable d'environnement, aucun nouveau secret.
- [ ] Vérifier que `/health` **n'ouvre aucune session** de base (probes CI/Railway).

**Tests**
- [ ] `tests/conftest.py` : `FakeTokenService.verify_access`, `FakeAuthUserRepository.find_user_by_id`, `FakeSalonScopeRepository`, fabrique de jetons de test (secret **factice**, jamais un secret réel).
- [ ] `test_security_dependencies.py` : 401 (7 variantes) · 403 (inactif, rôle, permission, **inter-salons**) · 200 · 503 · **matrice paramétrée rôle × route**.
- [ ] `test_deny_by_default.py` : invariant sur `app.routes` + liste blanche figée.
- [ ] `test_rbac_e2e.py` : `skipif` sans `DATABASE_URL` ; isolation inter-salons réelle, jeton altéré, refresh-en-accès, compte suspendu **après** émission.
- [ ] Confirmer que **toutes** les suites existantes passent **sans modification** (routes publiques intactes).

**Documentation**
- [ ] `docs/adr/0015-autorisation-rbac-deny-by-default.md` (gabarit ADR-0000).
- [ ] `docs/adr/README.md` : index + suivis mis à jour (#13 : table d'appartenance ; ADR-0014 : invalidation de jetons ; #52 : audit §11.4).
- [ ] `backend/README.md` : section « Autorisation & RBAC » + « comment protéger une nouvelle route ».
- [ ] `README.md` : §3/§4 — RBAC livré (#12).

**Vérification finale**
- [ ] `cd backend && ruff check . && pytest` verts (e2e *skippés* sans base).
- [ ] Avec `DATABASE_URL` : `alembic upgrade head && pytest` verts (e2e inclus).
- [ ] Relecture sécurité : aucun jeton, mot de passe, téléphone, e-mail ou nom dans un log, un message d'erreur ou une réponse ; aucun secret ajouté au dépôt.
