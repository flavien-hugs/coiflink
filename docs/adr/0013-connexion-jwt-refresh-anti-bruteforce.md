# ADR-0013 : Connexion — bibliothèque JWT, stratégie de refresh & anti-bruteforce

- **Statut** : Accepté
- **Date** : 2026-07-08
- **Décideurs** : équipe CoifLink
- **Issue** : #10 (US-1.2 — Connexion téléphone/email + mot de passe, JWT)
- **Référence PRD** : §11.1 (authentification, JWT + refresh, anti-bruteforce), §12.1 (API < 3 s)
- **Complète / ferme** : [ADR-0003](./0003-backend-fastapi.md) (« Suivi : bibliothèque JWT → M1 »),
  côté **émission de jetons**. Réutilise les ports d'auth posés par
  [ADR-0012](./0012-hachage-argon2-strategie-otp.md) (#8).

## Contexte et problème

L'inscription (#8/#9) crée des comptes mais **n'émet aucun jeton** : un utilisateur inscrit ne peut
pas encore ouvrir de session. La connexion (#10) est la **première feature à émettre des jetons** ;
elle doit (§11.1) : authentifier par **téléphone ou e-mail + mot de passe**, **émettre un JWT
d'accès + un refresh token**, **refuser** des identifiants invalides sans divulguer lequel est faux,
et **limiter les tentatives répétées**. L'ADR-0003 avait explicitement **différé à M1** le choix de la
**bibliothèque JWT**. Quatre décisions structurantes — réutilisées par le RBAC (#12, vérification des
jetons) et la réinitialisation (#11) — doivent donc être actées ici :

1. **Quelle bibliothèque / quel algorithme** de signature JWT ?
2. **Quelle stratégie de refresh** (rotation ? révocation ?) ?
3. **Quels TTL** pour l'accès et le refresh ?
4. **Quelle stratégie d'anti-bruteforce** (clé, seuils, stockage) ?

## Options envisagées

**Bibliothèque JWT :**
- **Option A — PyJWT.** Simple, ciblée sur JWT, très répandue et bien maintenue ; déjà présente
  dans l'écosystème.
- **Option B — python-jose.** Couvre l'ensemble JOSE (JWE/JWK…), plus large que le besoin ;
  historique de maintenance plus irrégulier.
- **Option C — authlib.** Très complète (OAuth/OIDC) mais surdimensionnée pour un simple JWT
  symétrique de monolithe.

**Algorithme :**
- **HS256** (secret symétrique) — simple pour un monolithe : la même clé signe et vérifie.
- **RS256** (asymétrique) — utile si la vérification est distribuée à d'autres services ; non
  nécessaire au MVP.

**Stratégie de refresh :**
- **Option A — refresh stateless signé + rotation**, sans persistance : aucune migration ; pas de
  déconnexion serveur immédiate.
- **Option B — révocation serveur** (logout, détection de réutilisation) via un store de `jti`
  révoqués (mémoire/Redis, ou table `refresh_tokens`) : permet la révocation immédiate, au prix
  d'un store partagé/persistant.

**Anti-bruteforce :**
- **Option A — compteur en mémoire** (fenêtre glissante + verrou temporisé), horloge injectable :
  aucune migration, cohérent avec l'OTP de #8 ; non partagé entre workers.
- **Option B — Redis** (déjà provisionné, ADR-0004) : partagé/persistant, mais câblage à faire.

## Décision

1. **Bibliothèque = PyJWT** (`pyjwt>=2.8`), **algorithme = HS256** avec `JWT_SECRET` (secret
   symétrique lu de l'environnement, ADR-0011), derrière le **port `TokenService`**
   (`issue_pair` / `decode` / `verify_refresh`). Le décodage **impose** l'algorithme attendu
   (`algorithms=["HS256"]`) et exige `exp`/`iat`/`sub`, ce qui **rejette `alg=none`** et la confusion
   d'algorithme. Claims minimaux, **sans PII** : `sub` (id utilisateur), `role`, `type`
   (`access`/`refresh`), `iat`, `exp`, `jti`.
2. **Refresh = Option A** : refresh **stateless** signé (`type=refresh`, `jti`, `exp`) **+ rotation**
   (chaque `/auth/refresh` émet une **nouvelle** paire) et **re-lecture** du `role`/`status` courant
   (un compte devenu non `ACTIVE` est refusé). **Pas de store de révocation** ni de `/auth/logout` en
   #10. **Aucune migration.**
3. **TTL** : accès **court** (défaut **15 min**), refresh **long** (défaut **30 j**), configurables
   par l'environnement (`JWT_ACCESS_TTL_SECONDS` / `JWT_REFRESH_TTL_SECONDS`).
4. **Anti-bruteforce = Option A** : **port `LoginRateLimiter`** implémenté **en mémoire** (fenêtre
   glissante + verrou temporisé, horloge injectable). Clé = **identifiant normalisé + IP** du pair.
   Seuils par défaut : **5 échecs / 300 s → verrou 900 s** (`429 Too Many Requests` + `Retry-After`) ;
   un **succès réinitialise** le compteur.

## Justification (compromis)

- **PyJWT + HS256** : le strict nécessaire pour un monolithe. Un secret symétrique suffit tant que la
  vérification n'est pas distribuée ; **RS256 est différé** (réévaluable si des services tiers doivent
  vérifier les jetons). Le coût signature/vérification est négligeable devant le budget API < 3 s
  (§12.1). Le port `TokenService` isole la lib : migrer vers RS256/authlib ne toucherait pas
  l'application. La **capacité `decode`** est fournie dès #10 pour que **#12** (middleware RBAC)
  consomme les mêmes claims — **contrat inter-issue figé ici**.
- **Refresh stateless + rotation** : satisfait « refresh token sécurisé » **sans migration** ni
  dépendance à un store. Compromis assumé : **pas de déconnexion serveur immédiate** — la fenêtre
  d'exposition est bornée par la **brièveté de l'accès** et la **rotation** du refresh. La révocation
  explicite (logout, liste de déni de `jti`) est **différée** avec un éventuel store Redis/table.
- **Anti-bruteforce en mémoire** : satisfait le critère « rate-limit sur les échecs » **sans
  migration**, cohérent avec l'OTP en mémoire de #8. Clé **IP + identifiant** pour éviter qu'un
  attaquant verrouille trivialement le compte d'un tiers sur le seul identifiant. Limite connue :
  **non partagé** entre workers/instances (efficacité réduite en multi-instances) — **adapter Redis
  différé**. Fiabilité de l'IP derrière le proxy Railway (`X-Forwarded-For` de confiance) **différée**
  également : on utilise l'IP du **pair direct** pour ne pas dépendre d'un en-tête spoofable.
- **Anti-énumération** : `401` **générique et uniforme** (compte inconnu / mot de passe faux / compte
  non `ACTIVE` → même statut, même message). **Atténuation d'oracle temporel** : une vérification
  argon2 **factice** (condensat *dummy* pré-calculé) est exécutée quand aucun compte ne correspond,
  pour égaliser grossièrement le temps de réponse (rigueur *constant-time* non garantie — limite
  documentée).
- **Normalisation de l'identifiant** : e-mail → `strip` (casse **conservée** pour rester cohérent avec
  le stockage de #8, qui ne met pas l'e-mail en minuscules) ; téléphone → **E.164** via la même
  fonction qu'à l'inscription (`0700…` et `+2250700…` visent le même compte). Une normalisation e-mail
  **insensible à la casse** (impactant #8 et l'unicité) est **différée**.
- **Fail-fast du secret** : `JWT_SECRET` est validé **à l'assemblage du `TokenService`** (au démarrage
  s'il est présent ; sinon les routes `/auth/login` et `/auth/refresh` répondent **`503`**), **sans
  casser `GET /health`** ni l'inscription en environnement mal configuré.

## Conséquences

- **Positives** : connexion de bout en bout dès M1 ; patterns de jetons (`TokenService.decode`)
  **réutilisables par #12** ; anti-bruteforce livré sans migration ; secret confiné à un adapter.
- **Négatives / risques** : refresh **non révocable** immédiatement (rotation seulement) ; limiteur
  et store de refresh **non partagés** entre instances ; IP du pair direct peu fiable derrière un
  proxy. Ces points sont **différés** (Redis/`X-Forwarded-For` de confiance / éventuel `/auth/logout`).
- **Sécurité** : mot de passe / condensat / `JWT_SECRET` / jeton **jamais journalisés** ; claims
  **sans PII** ; `401` générique anti-énumération ; algorithme **fixé côté serveur** (rejet
  `alg=none`) ; transport **Bearer** supposant HTTPS (terminaison TLS Railway, ADR-0011).
- **Suivi (non bloquant)** : **révocation / `/auth/logout`** et **adapter Redis** (anti-bruteforce +
  store de refresh partagés) → à réévaluer (M5/M6) ; **normalisation e-mail insensible à la casse** →
  décision commune avec #8/#9 ; **middleware RBAC** consommant `TokenService.decode` → **#12**.
