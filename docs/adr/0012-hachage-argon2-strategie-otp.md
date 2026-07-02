# ADR-0012 : Hachage de mot de passe (argon2id) & stratégie OTP

- **Statut** : Accepté
- **Date** : 2026-07-02
- **Décideurs** : équipe CoifLink
- **Issue** : #8 (US-1.1 — Inscription client)
- **Référence PRD** : §11.1 (authentification, mot de passe chiffré, OTP), §12.1 (API < 3 s)
- **Complète** : [ADR-0003](./0003-backend-fastapi.md) (« Suivi : bibliothèques JWT / hachage → M1 »)

## Contexte et problème

L'inscription client (#8) est la **première feature d'authentification** : elle doit stocker un mot
de passe **jamais en clair** (§11.1) et fournir une capacité **OTP testable** (OTP « recommandé »).
L'ADR-0003 avait explicitement **différé à M1** le choix de la bibliothèque de hachage. Deux
décisions structurantes — réutilisées par la connexion (#10) et la réinitialisation par OTP (#11) —
doivent donc être actées ici :

1. **Quel algorithme / quelle bibliothèque** de hachage de mot de passe ?
2. **Quelle stratégie OTP** en #8, alors que l'infra SMS (ADR-0006) n'arrive qu'en **M5** ?

## Options envisagées

**Hachage :**
- **Option A — argon2id** (`argon2-cffi`). Fonction mémoire-dure, **lauréate du Password Hashing
  Competition**, recommandée par l'OWASP ; **pas de troncature** de l'entrée.
- **Option B — bcrypt** (`passlib[bcrypt]`). Très répandu et éprouvé, mais **tronque silencieusement
  à 72 octets** et `passlib` est peu maintenu.
- **Option C — scrypt / PBKDF2** (`hashlib`, stdlib). Sans dépendance, mais paramétrage plus manuel
  et ergonomie de vérification/rehash moindre.

**Stratégie OTP :**
- **Option A — capacité testable, envoi différé, gating non bloquant, stockage hors schéma.** Compte
  créé `ACTIVE` ; OTP optionnel (drapeau), logique pure testable, dépôt en mémoire, envoi *stub*.
  **Aucune migration.**
- **Option B — gating bloquant** (compte non vérifié avant activation) : nécessiterait une **migration**
  (`phone_verified` ou statut `PENDING_VERIFICATION`) **et** une dépendance à l'infra SMS (M5).

## Décision

1. **Hachage = argon2id** via **`argon2-cffi`** (`argon2.PasswordHasher`, paramètres de coût sûrs par
   défaut), derrière le port `PasswordHasher` (`hash` / `verify`).
2. **OTP = Option A** : logique de domaine **pure et injectable** (RNG + horloge injectés, longueur,
   expiration, **usage unique**, **limite d'essais**), **désactivée par défaut** (`OTP_ENABLED=false`),
   dépôt **en mémoire** (port `OtpRepository`) et **envoi stub** (port `OtpSender`). **Aucune migration.**

## Justification (compromis)

- **argon2id** évite la **troncature 72 octets** de bcrypt (un mot de passe long resterait
  distinguable) et suit la recommandation OWASP ; le coût par défaut reste bien **sous le budget API
  < 3 s** (§12.1). Le port isole l'algorithme : un futur *rehash* (montée de paramètres) est possible
  sans toucher l'application. Compromis accepté : une dépendance native (`cffi`) — déjà présente dans
  l'écosystème et empaquetée en *wheels*.
- **OTP Option A** satisfait le critère d'acceptation « **l'OTP est testable** » **sans** dépendre de
  l'infra SMS (M5) ni imposer une migration prématurée. Le gating bloquant (Option B) est **différé**
  jusqu'à l'arrivée de l'envoi SMS réel, où il pourra être réévalué.

## Conséquences

- **Positives** : mot de passe robuste dès la première feature ; patterns d'auth (ports hacheur /
  dépôt / expéditeur) posés pour #9/#10/#11 ; OTP testable sans SMS ; pas d'évolution de schéma.
- **Négatives / risques** : le dépôt OTP en mémoire n'est **ni partagé ni persistant** (acceptable
  tant que l'OTP est non bloquant) ; l'envoi SMS reste **différé** (M5, ADR-0006). Un adapter Redis à
  TTL / une table dédiée et le gating bloquant seront tranchés à ce moment-là.
- **Sécurité** : mot de passe / condensat / code OTP / téléphone **jamais journalisés** ; l'OTP est
  stocké au repos sous forme non exploitable et le code n'est jamais renvoyé (PRD §11.1/§11.3).
- **Suivi (non bloquant)** : bibliothèque **JWT** (émission de jetons) → **issue #10** ; adapter OTP
  **Redis/SMS** et éventuel **gating bloquant** → M5 (ADR-0006).
