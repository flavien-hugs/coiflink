# ADR-0014 : Réinitialisation du mot de passe par OTP (SMS ou e-mail)

- **Statut** : Accepté
- **Date** : 2026-07-10
- **Décideurs** : équipe CoifLink
- **Issue** : #11 (US-1.3 — Réinitialisation du mot de passe)
- **Référence PRD** : §11.1 (authentification, réinitialisation par OTP), §11.3 (non-journalisation)
- **S'appuie sur** : [ADR-0012](./0012-hachage-argon2-strategie-otp.md) (argon2 + domaine OTP),
  [ADR-0013](./0013-connexion-jwt-refresh-anti-bruteforce.md) (JWT/refresh, anti-bruteforce),
  [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal)
- **Dépend de** : #8 (inscription client)

## Contexte et problème

Un utilisateur qui **oublie son mot de passe** n'avait jusqu'ici **aucun moyen** de le
réinitialiser : le socle d'auth couvrait l'inscription (#8/#9) et la connexion/refresh (#10), pas la
récupération de compte. Le PRD §11.1 exige une « **réinitialisation par OTP** » et le critère
d'acceptation de #11 précise : *« parcours de reset complet ; OTP à usage unique et expirant ; ancien
mot de passe invalidé »*.

Le cœur OTP (génération/vérification pures, usage unique, expiration, limite d'essais) existe déjà
dans le domaine (`domain/otp.py`, ADR-0012) mais n'était câblé à **aucun parcours métier**. La
réinitialisation est le **premier parcours qui consomme réellement l'OTP** et le **premier où l'OTP
est bloquant** (le reset ne peut aboutir sans un code valide). Plusieurs points devaient être tranchés
avant de coder les contrats de ports.

## Options envisagées

- **Forme du port `OtpSender`** : (A) généraliser en `send(recipient, code, channel)` multi-canal ;
  (B) introduire un second port/adapter e-mail distinct.
- **Stockage de l'OTP de reset** : (A) dépôt **en mémoire dédié** (comme #8) ; (B) store Redis à TTL
  ou table dédiée dès #11.
- **Invalidation des sessions** : (A) invalider **uniquement** le mot de passe (condensat remplacé) ;
  (B) révoquer aussi les jetons déjà émis (`password_changed_at`/`token_version` + migration + RBAC).
- **Anti-énumération à la demande** : (A) réponse 202 uniforme + défi « jeté » pour égaliser le temps
  de réponse ; (B) 202 uniforme sans atténuation d'oracle temporel.

## Décision

Parcours **en deux étapes** exposé sous le router `/auth`, adossé aux ports existants (plus deux
extensions minimes), cas d'usage **pur** (RNG + horloge injectables) :

1. **`POST /auth/password/reset/request`** — à partir d'un identifiant (téléphone **ou** e-mail),
   émet un OTP à usage unique et expirant. **Toujours `202`** générique (compte existant ou non).
2. **`POST /auth/password/reset/confirm`** — vérifie le code + fixe un nouveau mot de passe qui
   **remplace** le condensat. **`200`** générique ; **`400`** générique pour tout échec d'OTP et
   identifiant sans défi ; **`422`** si le nouveau mot de passe viole la politique.

Décisions structurantes retenues :

1. **Réutilisation du domaine OTP** (ADR-0012) sans modification : `generate_otp_challenge` /
   `verify_otp_challenge` (usage unique + expiration + limite d'essais + comparaison temps constant).
2. **Port `OtpSender` généralisé** (Option A) : `send(recipient, code, channel)` avec
   `channel ∈ NotificationChannel` (`SMS`/`EMAIL`, défaut `SMS`). L'appelant d'inscription passe
   `channel=SMS` ; le reset route `EMAIL`/`SMS` selon l'identifiant.
3. **Dépôt OTP de reset dédié** (Option A) : instance `InMemoryOtpRepository` séparée
   (`app.state.password_reset_otp_repository`) — un OTP d'inscription ne peut **jamais** servir à un
   reset, ni l'inverse. Renommage nominal du paramètre `OtpRepository.phone → key` (keyage e-mail
   comme téléphone).
4. **OTP de reset bloquant et toujours actif** : **indépendant** d'`OTP_ENABLED` (qui ne gouverne que
   l'OTP optionnel d'inscription).
5. **Anti-énumération** (Option A) : réponse **202 uniforme** à la demande ; **un seul 400** à la
   confirmation ; **atténuation d'oracle temporel** — un défi est **toujours** généré (même sans
   compte), analogue au condensat *dummy* de #10.
6. **Anti-abus** : la demande est **rate-limitée** (port `LoginRateLimiter`, instance **dédiée**,
   clé identifiant + IP) contre le « SMS/e-mail bombing » ; la confirmation est bornée par
   `attempts_left`.
7. **Ancien mot de passe invalidé** : nouvelle méthode `UserRepository.update_password(user_id,
   new_password_hash)` (reçoit **uniquement un condensat**). Le défi est **supprimé** après succès
   (usage unique **doublement** garanti : `consumed` + suppression).
8. **Invalidation des sessions = mot de passe uniquement** (Option A) : les jetons déjà émis restent
   valides jusqu'à `exp` (refresh stateless non révocable, ADR-0013). Le critère #11 porte sur le
   **mot de passe** ; l'invalidation complète des sessions est **différée** (voir Conséquences).
9. **Aucune migration** : le reset réécrit `users.password_hash` (colonne existante) ; l'OTP reste
   hors schéma (dépôt en mémoire). Le **canal e-mail** réel est un **stub** (pas d'ADR e-mail à ce
   jour ; ADR-0006 couvre FCM + SMS, pas l'e-mail transactionnel).

## Justification (compromis)

- **Réutiliser le domaine OTP et les ports d'auth** minimise le code neuf et garantit que les
  invariants (temps constant, usage unique, non-journalisation) sont déjà éprouvés.
- **Signature multi-canal** : une seule abstraction pour SMS et e-mail, refactor minime de l'appelant
  d'inscription (un `channel=SMS` explicite), plutôt que deux ports à maintenir en parallèle.
- **Dépôt dédié** : séparation physique claire des usages, sans logique de préfixe de clé fragile.
- **Réponse générique + défi jeté** : ferme l'oracle d'énumération (existence de compte) et atténue
  l'oracle temporel à faible coût, dans la continuité du `401` générique de #10.
- **Store en mémoire** : cohérent avec #8/#10 ; suffisant en dev/mono-instance. **Compromis assumé** :
  un OTP bloquant en mémoire n'est ni partagé entre instances ni persistant (voir Conséquences).
- **Non-révocation des jetons** : accepter la limite (documentée) évite une migration
  (`password_changed_at`/`token_version`) et une coordination prématurée avec le RBAC (#12) hors
  scope ; le risque est réduit par un TTL d'accès court (15 min) et l'impossibilité de **toute
  nouvelle** connexion avec l'ancien secret.

## Conséquences

- **Positives** : parcours de récupération de compte complet (SMS **ou** e-mail) ; premier usage
  bloquant de l'OTP ; anti-énumération et anti-abus préservés ; **aucune migration** ; ports d'auth
  enrichis proprement (`update_password`, `OtpSender` multi-canal) pour les features suivantes.
- **Négatives / risques** :
  - **Store OTP en mémoire pour un OTP bloquant** : un code émis sur une instance peut être
    invérifiable sur une autre (ou perdu au redéploiement). Acceptable en mono-instance ; **risque
    réel en multi-instances** → **Redis à TTL** (ADR-0004) à câbler si le staging est multi-instances.
  - **Non-révocation des jetons existants** : après reset, les jetons d'accès/refresh déjà émis
    **restent valides** jusqu'à `exp`. **Ne pas** laisser croire à une déconnexion serveur immédiate.
  - **Casse de l'e-mail conservée** (ADR-0013) : un e-mail saisi avec une casse différente de
    l'inscription ne trouvera pas le compte (⇒ 202/400 générique). Limite connue, non traitée ici.
- **Sécurité** : mot de passe en clair / condensat / **code OTP** / téléphone / e-mail **jamais
  journalisés ni renvoyés** (senders stub sans log) ; comptes non `ACTIVE` traités comme inexistants
  (pas de divulgation) ; endpoints **indépendants** de `JWT_SECRET` (pas de `503`).
- **Suivi (non bloquant)** : **store OTP Redis/persistant** (fiabilité multi-instances) et
  **invalidation immédiate des jetons** (`password_changed_at`/`token_version` + RBAC #12) → M5 /
  itération ultérieure ; **canal e-mail réel** (fournisseur, surface de secrets) → M5 (ADR-0006 à
  compléter).
