# ADR-0044 : Signature stable de l'APK Android — mises à jour de la borne en place

- **Statut** : Accepté
- **Date** : 2026-08-23
- **Décideurs** : équipe CoifLink
- **Issue** : ad hoc (aucune issue GitHub créée en amont, comme #150–#153/ADR-0043)
- **Référence PRD** : §10.2 (déploiement), US-8.5 « Authentification & activation de la borne » (#159)
- **S'appuie sur** : [ADR-0001](./0001-app-mobile-flutter.md) (Flutter), [ADR-0041](./0041-authentification-borne-kiosque.md)
  (activation/credential device) — **étendu** ici, pas remplacé

## Contexte et problème

La borne (mode kiosque, US-8.5/#159) s'active **une seule fois** : code à 6 chiffres →
`TerminalActivationScreen` → credential device (`device_id`, `secret`) persisté via
`SecureTerminalCredentialStore` (`flutter_secure_storage`, adossé au **Keystore Android**). Au
démarrage suivant, `TerminalBootstrap` lit ce credential et authentifie **silencieusement** — aucune
ré-activation tant qu'il est présent et valide (`app-mobile/lib/adapters/ui/terminal/
terminal_bootstrap.dart`). Cette logique est correcte et déjà en place.

**Symptôme rapporté** : après une mise à jour de l'app, la borne redemande le code d'activation au lieu
d'aller directement à l'accueil (prise de ticket).

**Cause racine identifiée** : `android/app/build.gradle.kts` n'a jamais eu de configuration de
signature de release (`TODO` du template Flutter par défaut jamais rempli) ; `ci.yml` construit l'APK
avec `flutter build apk --debug`, signé par la clé de **debug auto-générée par Gradle** — régénérée à
chaque run sur un runner GitHub Actions éphémère (aucun `~/.android/debug.keystore` persisté d'un run à
l'autre). Chaque APK produit par la CI a donc une **signature différente** du précédent. Android refuse
catégoriquement d'installer une mise à jour dont la signature diffère de la version déjà installée
(protection anti-usurpation du système) : la mise à jour des bornes se fait donc en pratique par
**désinstallation puis réinstallation** — confirmé auprès de l'équipe. Désinstaller une app Android
efface **tout** son stockage privé, Keystore compris : le credential borne et l'imprimante sélectionnée
(`SecureTicketPrinterDeviceStore`, même mécanisme) disparaissent avec l'app, quel que soit le code Dart.
**Aucune logique métier n'est donc en cause** — la ré-activation observée est un effet de bord d'une
signature d'APK instable, pas un choix ni un bug du bootstrap.

## Options envisagées

- **Option A — Ne rien changer côté build, contourner en Dart.** Impossible par construction : une
  désinstallation Android efface la totalité du stockage privé de l'app avant que le nouveau code ne
  s'exécute une seule fois ; aucune logique applicative ne peut lire un état qui n'existe plus.
- **Option B (retenue) — Clé de signature stable, réutilisée à chaque build.** `android/key.properties`
  (gitignoré) fournit une identité de signature persistante ; `build.gradle.kts` la lit **si présente**
  et l'applique à la config `debug` (celle utilisée par la CI aujourd'hui). Une mise à jour redevient
  une vraie mise à jour **en place** : le stockage privé (donc le credential et l'imprimante) survit,
  et le bootstrap déjà correct fait le reste.
- **Option C — Passer à des builds `--release` signés + distribution formelle (Play Store interne /
  MDM).** Solution plus complète et « propre » à terme, mais périmètre bien plus large (minification
  R8, tests de non-régression sur device réel impossibles dans l'environnement de développement actuel,
  choix d'un canal de distribution) — **hors périmètre** de cette demande, qui porte spécifiquement sur
  la ré-activation après mise à jour. Noté comme évolution possible, non traitée ici.

## Décision

- **`android/app/build.gradle.kts`** lit `android/key.properties` **s'il existe** (`Properties()` +
  `FileInputStream`, patron standard Flutter) et, dans ce cas seulement, redéfinit la config de
  signature `debug` (`storeFile`/`storePassword`/`keyAlias`/`keyPassword`) — **absent** (poste de tout
  contributeur ordinaire, fichier gitignoré) → **aucun changement** de comportement, Gradle garde sa
  clé de debug implicite. Le fichier `.jks` et `key.properties` sont ajoutés à `.gitignore`
  (`app-mobile/`) : **jamais** committés.
- **`ci.yml` (job `mobile`)** : nouvelle étape avant `flutter build apk`, qui décode un secret
  GitHub Actions base64 (`ANDROID_UPLOAD_KEYSTORE_BASE64`) vers `android/app/upload-keystore.jks` et
  écrit `android/key.properties` à partir de trois autres secrets
  (`ANDROID_UPLOAD_KEYSTORE_PASSWORD`/`ANDROID_UPLOAD_KEY_ALIAS`/`ANDROID_UPLOAD_KEY_PASSWORD`) —
  **uniquement si le premier secret est renseigné** (branchement dans le script, pas via `if:`, qui
  n'expose pas le contexte `secrets`). Secrets absents (non encore provisionnés) → comportement actuel
  préservé sans erreur, comme le patron déjà établi pour `API_BASE_URL_PROD`/`API_BASE_URL_STAGING`
  (ADR-0043).
- **Génération et custody du keystore laissées à l'équipe**, jamais à un agent ni committées : un
  keystore de signature est un secret **permanent et critique** (voir Conséquences) — sa génération et
  son premier provisionnement suivent un court runbook (`keytool -genkeypair`, `gh secret set`),
  documenté dans `docs/environnements-et-secrets.md`.
- **Build type inchangé** (`--debug`, pas `--release`) : seule la **signature** est stabilisée, aucune
  minification/obfuscation n'est introduite — limite le risque de régression à la seule question posée.

## Justification (compromis)

- **Résout la cause racine, pas le symptôme** : aucune modification du bootstrap Dart (déjà correct)
  n'aurait résolu quoi que ce soit tant que l'update reste une désinstallation forcée.
- **Sans danger pour les contributeurs ordinaires** : `key.properties` absent (cas par défaut, jamais
  committé) laisse `build.gradle.kts` et `ci.yml` strictement inchangés dans leur comportement observé.
- **Cohérent avec le patron déjà établi cette session** (`MY_GITHUB_TOKEN`, `API_BASE_URL_PROD/
  _STAGING`) : infrastructure câblée pour lire un secret par son nom, provisionnement réel laissé à
  l'équipe — jamais une valeur inventée ou générée par un agent pour un secret de cette nature.
- **Compromis accepté** : la custody du keystore devient une responsabilité **permanente** et sans
  filet (voir Conséquences) — inhérent à tout système de signature Android, pas spécifique à ce choix
  d'implémentation.

## Conséquences

- **Positives** : une mise à jour CI redevient une vraie mise à jour en place dès que le keystore est
  provisionné — la borne conserve son activation et son imprimante configurée, résolvant directement le
  symptôme rapporté.
- **Négatives / risques** :
  - **Perte du keystore** : plus aucune mise à jour en place possible pour le parc déjà activé avec
    l'ancienne signature — chaque borne physique nécessite une **réactivation manuelle unique** (pas
    pire que la situation actuelle, mais un retour en arrière à éviter). **Aucune récupération
    possible** : un secret GitHub Actions n'est jamais relisible une fois posé, seule une sauvegarde
    humaine du fichier `.jks` original permet de le restaurer.
  - **Fuite du keystore** : risque limité en pratique (APK jamais publié sur un store public, distribué
    par sideload/CI vers un parc de bornes contrôlé) mais à traiter comme tout secret critique
    (§3 `docs/environnements-et-secrets.md`).
  - `--release`/distribution formelle restent hors périmètre : cette ADR ne prétend pas livrer un
    pipeline de release Android complet, seulement stabiliser la signature du build déjà utilisé par
    la CI pour les bornes.
- **Suivi** :
  - l'équipe génère le keystore et provisionne les 4 secrets (runbook
    `docs/environnements-et-secrets.md`) — **non bloquant**, la CI continue de fonctionner sans eux ;
  - vérification réelle sur device physique, hors de portée de l'environnement de développement actuel
    (pas de SDK Android/device pour compiler et installer ici) ;
  - passage éventuel à `--release` + distribution formelle : évolution possible, à décider séparément.
