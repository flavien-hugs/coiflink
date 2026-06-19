# Backlog — Plateforme de Santé Numérique Décentralisée (Côte d'Ivoire)

> **Source :** dérivé de [`PRD_HealthTech.md`](./PRD_HealthTech.md)
> **État du dépôt au moment de la rédaction :** projet *greenfield* — aucun code, uniquement le PRD.
> **Architecture cible :** Local-First / Zero-Knowledge Cloud, chiffrement AES-256-GCM côté patient, hébergement obligatoire en Côte d'Ivoire (ARTCI / loi n°2013-450).

## Légende

- **Effort :** `S` (≤ 2 j), `M` (3–5 j), `L` (1–2+ semaines)
- **Priorité :** `Must` / `Should` / `Could` (MoSCoW, alignée sur le PRD)
- **Étiquettes :** `feature`, `bug`, `tech-debt`, `docs`, `security`, `infra`, `compliance`, `ux`, `crypto`

---

## Vue d'ensemble des jalons (milestones)

| Jalon | Objectif (1 ligne) | Épics couverts |
| ----- | ------------------ | -------------- |
| **M0 — Fondations & Conformité** | Mettre en place le socle technique, cryptographique, légal et l'hébergement souverain avant d'écrire la moindre fonctionnalité. | E0, E6, E7 |
| **M1 — Cœur cryptographique & onboarding patient** | Le patient crée un compte chiffré localement, ses données sont sauvegardées en zero-knowledge, et il peut les restaurer. | E1, E5, E7 |
| **M2 — Boucle de consultation** | Le cycle complet QR → scan → consultation → effacement fonctionne de bout en bout. C'est le cœur de valeur du produit. | E1, E2 |
| **M3 — Résilience hors-ligne & médias** | La consultation survit aux coupures réseau/courant et gère les images médicales lourdes hors du téléphone. | E2, E5 |
| **M4 — Durcissement & lancement** | Audit de sécurité, homologation ARTCI, validation des performances et pilote terrain à Abidjan. | E3, E4, E6 |

**Chemin critique :** M0 → M1 → M2 → M3 → M4 (chaque jalon dépend du précédent ; M2 ne peut commencer tant que le module crypto de M1 n'est pas figé).

---

## M0 — Fondations & Conformité

> **Objectif :** Aucune fonctionnalité avant un socle sûr. On fige ici l'architecture, le modèle de menace et le cadre légal.

### E0 — Socle projet & DevOps `infra`

- **#1 — Choix de la stack technique & ADR** · `Must` · `M` · `docs` `infra`
  Trancher : framework app patient (Kotlin natif vs Flutter — cible Android entrée de gamme), interface médecin (PWA React vs mobile partagé), backend (Go/Rust/Node), stockage objet pour les blobs. Documenter via des ADR (Architecture Decision Records).
  *Acceptation :* un ADR par décision majeure committé dans `/docs/adr/` ; justification du compromis taille/perf sur smartphones d'entrée de gamme.

- **#2 — Initialisation du monorepo & structure** · `Must` · `S` · `infra`
  Créer l'arborescence (`/app-patient`, `/app-medecin`, `/backend`, `/crypto-core`, `/infra`, `/docs`), licences, `README`, `.gitignore`, conventions de commits.
  *Acceptation :* `git init`, structure en place, README décrivant le projet et la commande de build de chaque paquet.

- **#3 — Pipeline CI/CD** · `Must` · `M` · `infra`
  Lint, tests unitaires, build des apps et du backend, scan de dépendances (SCA), à chaque PR.
  *Acceptation :* CI verte obligatoire avant merge ; build APK et image backend produits en artefacts.

- **#4 — Environnements & secrets** · `Should` · `M` · `infra` `security`
  Gestion des secrets (pas de clé en clair dans le repo), environnements dev/staging/prod, IaC pour l'hébergement local.
  *Acceptation :* secrets injectés via coffre-fort ; `staging` reproductible depuis l'IaC.

### E6 — Conformité, légal & gouvernance `compliance`

- **#5 — Analyse de conformité loi n°2013-450 & exigences ARTCI** · `Must` · `L` · `compliance` `docs`
  Cartographier chaque exigence légale (résidence des données, consentement, droits du patient) vers une exigence technique.
  *Acceptation :* matrice de conformité exigence → contrôle technique → preuve, validée par le conseil juridique.

- **#6 — Modèle de menace & politique de sécurité** · `Must` · `L` · `security` `docs`
  Threat model (STRIDE) couvrant : vol de téléphone, serveur compromis, MITM réseau, QR code intercepté, attaque sur la phrase de passe de récupération.
  *Acceptation :* document de threat model revu ; chaque menace `Must` a une contre-mesure tracée vers une issue.

- **#7 — Politique de consentement & parcours juridique patient** · `Should` · `M` · `compliance` `ux`
  Écrans de consentement, CGU, politique de confidentialité conformes à la loi ivoirienne.
  *Acceptation :* textes validés juridiquement, intégrés au parcours d'onboarding (#13).

### E7 — Hébergement souverain & backend zero-knowledge `infra`

- **#8 — Provisionnement de l'hébergement en Côte d'Ivoire** · `Must` · `L` · `infra` `compliance`
  Sélectionner et provisionner l'hébergement local (datacenter national) garantissant la résidence des données.
  *Acceptation :* infrastructure opérationnelle sur le territoire national, attestation de localisation.

- **#9 — Service de stockage de blobs zero-knowledge** · `Must` · `L` · `feature` `backend` `security`
  API minimale : stocker / récupérer un blob chiffré indexé par UUID anonyme. Le serveur ne voit jamais de donnée nominative ni de clé.
  *Acceptation :* endpoints `PUT/GET /blob/{uuid}` ; aucune donnée en clair persistée ; tests prouvant que le serveur ne peut pas déchiffrer.

---

## M1 — Cœur cryptographique & onboarding patient

> **Objectif :** Le patient possède réellement ses données : clé générée localement, sauvegarde illisible par le serveur, restauration possible.

### E5 — Cœur cryptographique (bibliothèque partagée) `crypto`

- **#10 — Module AES-256-GCM (chiffrement/déchiffrement de blob)** · `Must` · `M` · `crypto` `security`
  Bibliothèque partagée patient/médecin : chiffrement authentifié AES-256-GCM, gestion des nonces, vecteurs de test.
  *Acceptation :* vecteurs de test officiels passants ; revue de sécurité du module ; API stable réutilisée par les apps.
  *Dépend de :* #6.

- **#11 — Génération & gestion de la clé maîtresse locale** · `Must` · `M` · `crypto` `security`
  Génération de la clé maîtresse sur l'appareil, stockage dans le keystore matériel (Android Keystore), jamais exportée en clair.
  *Acceptation :* clé générée et scellée dans le keystore ; aucune fuite en mémoire persistante.
  *Implémente :* US-1.1.

- **#12 — Dérivation & récupération de clé (PBKDF2 + questions culturelles)** · `Must` · `M` · `crypto` `security` `ux`
  Dérivation PBKDF2 depuis une phrase de passe ou des questions de sécurité adaptées au contexte ivoirien ; paramètres de coût calibrés pour les téléphones d'entrée de gamme.
  *Acceptation :* restauration réussie sur un nouvel appareil à partir de la phrase/des réponses ; paramètres résistants au brute-force documentés.
  *Implémente :* US-1.4 · *Dépend de :* #6, #11.

### E1 — Application Patient (onboarding) `feature`

- **#13 — Création de compte chiffré (n° CMU / téléphone)** · `Must` · `M` · `feature` `ux`
  Parcours d'onboarding : saisie n° CMU/téléphone, génération locale de la clé (#11), aucune donnée nominative envoyée en clair.
  *Acceptation :* compte créé hors-ligne ; capture réseau prouvant l'absence de PII en clair.
  *Implémente :* US-1.1 · *Dépend de :* #11, #7.

- **#14 — Sauvegarde cloud zero-knowledge du dossier** · `Must` · `M` · `feature` `security`
  Chiffrement local du dossier complet (blob) puis téléversement automatique vers le serveur ivoirien (#9).
  *Acceptation :* le blob téléversé est indéchiffrable côté serveur ; téléversement automatique après modification.
  *Implémente :* US-1.3 · *Dépend de :* #9, #10.

- **#15 — Structure & schéma du dossier médical (≤ 500 Ko)** · `Must` · `M` · `feature` `tech-debt`
  Définir le schéma du dossier texte, valider la contrainte de 500 Ko de texte brut, stratégie de compression/troncature.
  *Acceptation :* schéma versionné ; garde-fou bloquant/avertissant au-delà de 500 Ko.
  *Dépend de :* contrainte PRD §4.

---

## M2 — Boucle de consultation

> **Objectif :** Le parcours QR → scan → édition → effacement fonctionne de bout en bout. C'est le cœur de valeur démontrable.

### E1 — Application Patient (partage) `feature`

- **#16 — Génération du QR code d'accès temporaire** · `Must` · `M` · `feature` `crypto`
  QR dynamique contenant l'URL serveur + la clé symétrique de déchiffrement ; expiration à 120 s ; affichage UX clair du compte à rebours.
  *Acceptation :* QR expiré refusé côté médecin après 120 s ; clé jamais persistée hors du QR.
  *Implémente :* US-1.2 · *Dépend de :* #10, #14.

### E2 — Interface Professionnel de Santé `feature`

- **#17 — Scan du QR & déchiffrement en RAM uniquement** · `Must` · `L` · `feature` `security`
  Scan → téléchargement du blob (#9) → déchiffrement avec la clé du QR **uniquement en mémoire vive**, jamais sur disque.
  *Acceptation :* analyse mémoire/disque prouvant l'absence d'écriture en clair ; dossier affiché après scan.
  *Implémente :* US-2.1 · *Dépend de :* #16, #9, #10.

- **#18 — Ajout de note / ordonnance & fusion en mémoire** · `Must` · `M` · `feature` `ux`
  Formulaire d'édition rapide ; fusion des ajouts avec le dossier existant en RAM ; modèle d'ordonnance.
  *Acceptation :* note/ordonnance fusionnée sans écraser l'historique ; rechiffrement du dossier mis à jour.
  *Implémente :* US-2.2 · *Dépend de :* #17.

- **#19 — Fin de session : rechiffrement, renvoi cloud & wipe RAM** · `Must` · `M` · `feature` `security`
  Au clic « Terminer » ou après 15 min d'inactivité : chiffrer le nouveau dossier, l'envoyer au cloud, vider la RAM du médecin.
  *Acceptation :* après fin de session, aucune donnée patient résiduelle en mémoire ; blob mis à jour côté serveur.
  *Implémente :* US-2.3 · *Dépend de :* #17, #18, #14.

- **#20 — Démo end-to-end de la boucle de consultation** · `Should` · `S` · `docs` `feature`
  Scénario de bout en bout (patient génère QR → médecin scanne, édite, termine → patient voit la mise à jour) automatisé en test d'intégration.
  *Acceptation :* test e2e vert couvrant le cycle complet.
  *Dépend de :* #16–#19.

---

## M3 — Résilience hors-ligne & médias

> **Objectif :** Garantir 100 % des consultations sans perte de données même hors réseau, et sortir les images lourdes du téléphone.

### E2 — Résilience médecin `feature`

- **#21 — File d'attente hors-ligne sécurisée (SQLCipher)** · `Must` · `L` · `feature` `security`
  En cas de coupure réseau, l'ordonnance chiffrée est placée dans une file locale chiffrée (SQLCipher).
  *Acceptation :* consultation validée hors-ligne ; donnée stockée chiffrée localement ; rien en clair.
  *Implémente :* US-2.4 · *Dépend de :* #10, #19.

- **#22 — Synchronisation au retour du réseau** · `Must` · `M` · `feature` `tech-debt`
  Dès le retour réseau, la file se synchronise vers le cloud ; gestion des conflits et des renvois.
  *Acceptation :* aucune perte ni doublon après reconnexion ; stratégie de résolution de conflits documentée.
  *Implémente :* US-2.4 · *Dépend de :* #21.

### E5 — Gestion des médias lourds `feature`

- **#23 — Déport des images médicales sur serveur chiffré + URL éphémère** · `Must` · `L` · `feature` `security` `infra`
  Interdire le stockage des radiographies/scans sur le téléphone ; les stocker sur serveur distant chiffré ; n'intégrer qu'un lien d'accès éphémère au dossier texte.
  *Acceptation :* aucune image lourde sur le téléphone patient ; URL éphémère révoquée après expiration.
  *Implémente :* PRD §4 (contrainte stockage).

- **#24 — Optimisation réseau dégradé (Edge/3G)** · `Should` · `M` · `tech-debt` `infra`
  Téléchargement/déchiffrement instantanés sous Edge/3G : compression, reprise de téléchargement, budget de taille.
  *Acceptation :* dossier de 500 Ko téléchargé+déchiffré dans la cible perf sur lien simulé 3G instable.
  *Dépend de :* #15, #14.

---

## M4 — Durcissement & lancement

> **Objectif :** Prouver la sécurité, obtenir l'homologation, valider les performances et piloter à Abidjan.

### E3 — Sécurité & audit `security`

- **#25 — Audit de sécurité & test d'intrusion externe** · `Must` · `L` · `security`
  Pentest par un tiers ciblant crypto, zero-knowledge, QR, récupération de clé, wipe RAM.
  *Acceptation :* rapport d'audit ; toutes les vulnérabilités `Critical`/`High` corrigées et re-testées.
  *Dépend de :* M1–M3 complets.

- **#26 — Revue cryptographique indépendante** · `Should` · `M` · `security` `crypto`
  Revue par un expert crypto des choix AES-GCM, PBKDF2, gestion des nonces/clés.
  *Acceptation :* avis d'expert favorable ou correctifs appliqués.

### E4 — Performance & UX `ux`

- **#27 — Validation des performances (déchiffrement < 3 s en 3G)** · `Must` · `M` · `tech-debt` `ux`
  Banc de mesure : scan → affichage du dossier ≤ 3 s sous 3G stable.
  *Acceptation :* mesures reproductibles confirmant la cible ; régression bloquée en CI.
  *Implémente :* NFR Performance.

- **#28 — Affûtage UX médecin (prise en main < 5 min)** · `Must` · `M` · `ux`
  Interface ultra-épurée, sans menus complexes ; tests d'utilisabilité avec des médecins.
  *Acceptation :* un médecin non formé réalise une consultation complète en < 5 min lors d'un test utilisateur.
  *Implémente :* NFR UX.

- **#29 — Accessibilité & robustesse sur smartphones d'entrée de gamme** · `Should` · `M` · `ux` `tech-debt`
  Tester sur appareils type Infinix 32 Go quasi saturés ; gérer micro-coupures de courant.
  *Acceptation :* parcours patient et médecin validés sur appareil de référence bas de gamme.

### E6 — Homologation & lancement `compliance`

- **#30 — Dossier d'homologation ARTCI** · `Must` · `L` · `compliance` `docs`
  Constituer et soumettre le dossier d'homologation ; preuves de conformité (#5, #25).
  *Acceptation :* homologation ARTCI obtenue à 100 % avant lancement commercial (Objectif KPI).
  *Dépend de :* #5, #25.

- **#31 — Pilote terrain à Abidjan (beta)** · `Should` · `L` · `feature` `ux`
  Déploiement pilote (Cocody/Yopougon) avec un panel de patients et médecins ; collecte de retours.
  *Acceptation :* pilote mené ; métriques d'adoption et de fiabilité collectées vers les KPIs (50 000 patients / 500 médecins).
  *Dépend de :* #30.

---

## Récapitulatif des dépendances clés

- **#10 (AES-256-GCM)** est la pierre angulaire : bloque #14, #16, #17, #21.
- **#9 (serveur zero-knowledge)** bloque toute sauvegarde/lecture cloud (#14, #17, #19).
- **#25 (pentest)** et **#5 (conformité)** conditionnent **#30 (homologation ARTCI)**, elle-même prérequis du lancement.
- La boucle de consultation (M2) n'a de valeur démontrable qu'une fois #16→#19 enchaînés ; viser un premier *end-to-end* (#20) le plus tôt possible.

## Risques à surveiller

1. **Récupération de clé** (#12) : compromis sécurité ↔ ergonomie ; un mauvais choix bloque les patients hors de leurs données.
2. **Contrainte 500 Ko** (#15, #24) : impose une discipline de schéma dès M1, difficile à rétro-fitter.
3. **Hébergement souverain** (#8) : délai d'approvisionnement potentiellement long, à lancer dès M0.
4. **Homologation ARTCI** (#30) : dépendance externe sur le chemin critique du lancement.

---

## Ordre d'implémentation recommandé

> Séquence dérivée des dépendances de chaque issue. Reflétée dans le champ **`Ordre`** du [GitHub Project « HealthTech — Roadmap »](https://github.com/users/kortiene/projects/2) (tri ascendant pour la dérouler à l'écran).

### Chemin critique (enchaînement bloquant le plus long)

> **#1 → #2 → #6 → #10 → #9 → #14 → #16 → #17 → #19 → #21 → #25 → #30 → #31**

Tout retard sur cette chaîne décale le lancement. Deux dépendances **externes** y pèsent lourd : **#8** (hébergement, à lancer immédiatement) et **#5 + #30** (conformité / homologation ARTCI) — d'où leur démarrage anticipé malgré l'absence de code.

### Vagues (ce qui peut avancer en parallèle)

- **Vague 0 — fondations & longs délais (J0, en parallèle) :** #1, #6, #5, #8
- **Vague 1 — socle technique :** #2, #3, #4, #7, #15
- **Vague 2 — cœur crypto & backend :** #10, #9, #11
- **Vague 3 — onboarding patient (M1) :** #12, #14, #13
- **Vague 4 — boucle de consultation (M2, quasi séquentielle) :** #16 → #17 → #18 → #19 → #20
- **Vague 5 — résilience hors-ligne & médias (M3) :** #21, #23, #24, #22
- **Vague 6 — durcissement & lancement (M4) :** #26, #28, #27, #29, #25, #30, #31

### Séquence stricte (1 seul flux, ordre topologique)

| Ordre | Issue | | Ordre | Issue |
| ----: | ----- | --- | ----: | ----- |
| 1  | #1 — Stack & ADR              | | 17 | #17 — Scan QR + déchiffrement RAM |
| 2  | #6 — Modèle de menace         | | 18 | #18 — Note / ordonnance |
| 3  | #5 — Conformité ARTCI         | | 19 | #19 — Fin de session + wipe |
| 4  | #8 — Hébergement souverain    | | 20 | #20 — Démo end-to-end |
| 5  | #2 — Monorepo                 | | 21 | #23 — Déport images + URL éphémère |
| 6  | #3 — CI/CD                    | | 22 | #24 — Optimisation réseau dégradé |
| 7  | #4 — Environnements & secrets | | 23 | #21 — File offline (SQLCipher) |
| 8  | #15 — Schéma dossier ≤ 500 Ko | | 24 | #22 — Synchronisation réseau |
| 9  | #10 — Module AES-256-GCM      | | 25 | #26 — Revue crypto indépendante |
| 10 | #9 — Service blob zero-knowledge | | 26 | #28 — Affûtage UX médecin |
| 11 | #11 — Clé maîtresse locale    | | 27 | #27 — Validation perf < 3 s |
| 12 | #12 — Dérivation/récupération PBKDF2 | | 28 | #29 — Accessibilité bas de gamme |
| 13 | #7 — Consentement & juridique | | 29 | #25 — Audit sécurité / pentest |
| 14 | #13 — Création de compte chiffré | | 30 | #30 — Homologation ARTCI |
| 15 | #14 — Sauvegarde cloud ZK     | | 31 | #31 — Pilote terrain Abidjan |
| 16 | #16 — Génération QR temporaire | | | |
