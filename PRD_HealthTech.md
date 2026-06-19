# Document d'Exigences Produit (PRD)

## Projet : Plateforme de Santé Numérique Décentralisée (Côte d'Ivoire)

**Statut :** En cours de révision | **Date :** Juin 2026 | **Auteur :** Product Team

**Cible :** Marché Ivoirien (Patients & Professionnels de Santé)

**Architecture :** Local-First / Zero-Knowledge Cloud

---

## 1. Vision du Produit & Objectifs Stratégiques

### Vision

Offrir à chaque citoyen ivoirien la propriété absolue et sécurisée de ses données de santé. Grâce à une architecture décentralisée, le patient transporte son dossier médical dans son smartphone et en octroie un accès éphémère et contrôlé aux professionnels de santé via un QR code dynamique, sans dépendre d'une connexion internet permanente.

### Objectifs Clés (KPIs)

- **Adoption :** Atteindre 50 000 patients actifs et 500 médecins partenaires à Abidjan dans les 6 premiers mois post-lancement.
- **Fiabilité technique :** 100 % des consultations doivent pouvoir se dérouler sans perte de données, même en cas de coupure réseau totale.
- **Conformité :** Validation et homologation à 100 % par l'ARTCI avant le lancement commercial.

---

## 2. Profils Utilisateurs (Personas)

- **Awa, 28 ans (Le Patient) :** Habite à Yopougon, possède un smartphone Infinix (32 Go, souvent saturé). Elle souhaite que ses antécédents médicaux soient accessibles rapidement lorsqu'elle consulte, mais refuse que l'État ou des tiers piratent ses données.
- **Dr. Koné, 42 ans (Le Médecin) :** Généraliste dans une clinique à Cocody. Il reçoit 30 patients par jour. Il a besoin d'un outil ultra-rapide qui s'intègre dans sa routine sans lui faire perdre de temps, et qui fonctionne même lors des micro-coupures de courant.

---

## 3. Exigences Fonctionnelles (Épics & User Stories)

### Épic 1 : L’Application Patient (Mobile-First - Focus Android)

| ID         | User Story                                                                                            | Priorité (MoSCoW) | Spécifications Fonctionnelles                                                                                  |
| ---------- | ----------------------------------------------------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------- |
| **US-1.1** | En tant que patient, je veux créer un compte chiffré localement avec mon numéro CMU ou de téléphone.  | **Must**          | Génération locale de la clé maîtresse cryptographique. Aucune donnée nominative envoyée en clair.              |
| **US-1.2** | En tant que patient, je veux générer un QR code d'accès temporaire pour mon médecin.                  | **Must**          | Le QR code contient l'URL du serveur + la clé symétrique de déchiffrement. Expire au bout de 120 secondes.     |
| **US-1.3** | En tant que patient, je veux sauvegarder mon dossier sur le cloud sans que le serveur puisse le lire. | **Must**          | Chiffrement local du dossier complet (Blob) avant téléversement automatique sur le serveur ivoirien.           |
| **US-1.4** | En tant que patient, je veux récupérer mes données sur un nouveau téléphone si je perds le mien.      | **Must**          | Mécanisme de dérivation de clé (PBKDF2) basé sur une phrase de passe ou des questions de sécurité culturelles. |

### Épic 2 : L’Interface Professionnel de Santé (Web & Mobile)

| ID         | User Story                                                                                              | Priorité (MoSCoW) | Spécifications Fonctionnelles                                                                                                                         |
| ---------- | ------------------------------------------------------------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **US-2.1** | En tant que médecin, je veux scanner le QR code d'un patient pour ouvrir son dossier instantanément.    | **Must**          | Le scan télécharge le Blob chiffré du serveur, utilise la clé du QR code pour le déchiffrer uniquement dans la mémoire RAM du terminal.               |
| **US-2.2** | En tant que médecin, je veux ajouter une note ou une ordonnance au dossier du patient.                  | **Must**          | Formulaire d'édition rapide. Les ajouts sont fusionnés avec le dossier existant en mémoire vive.                                                      |
| **US-2.3** | En tant que médecin, je veux que la session se ferme et s'efface automatiquement après la consultation. | **Must**          | Au clic sur "Terminer" ou après 15 min d'inactivité, le nouveau dossier est chiffré, envoyé au cloud, et la RAM du médecin est vidée (_Wipe_).        |
| **US-2.4** | En tant que médecin, je veux pouvoir valider une consultation même si ma connexion internet coupe.      | **Must**          | Si le réseau échoue, l'ordonnance chiffrée est placée dans une file d'attente locale sécurisée (_SQLCipher_) et synchronisée dès le retour du réseau. |

---

## 4. Contraintes Techniques & Spécifications de Sécurité

### Architecture Cryptographique

- **Chiffrement des Données :** Standard **AES-256-GCM** appliqué sur le smartphone du patient avant tout transit.
- **Zéro-Connaissance (Zero-Knowledge) :** Le serveur de base de données (hébergé localement en Côte d'Ivoire pour respecter l'ARTCI) ne stocke que des identifiants anonymes (UUID) liés à des chaînes de texte chiffrées (Blobs).

### Contraintes d'Infrastructure Locale

> **Règle de performance en réseau dégradé :** La taille du texte brut du dossier médical principal ne doit pas dépasser 500 Ko pour garantir un téléchargement et un déchiffrement instantanés, même sur une connexion Edge/3G instable.

- **Gestion du stockage des smartphones d'entrée de gamme :** Interdiction de stocker les images médicales lourdes (radiographies, scans) directement sur le téléphone du patient. Elles sont stockées sur un serveur distant chiffré et seul un lien d'accès (URL éphémère) est intégré au dossier texte du patient.

---

## 5. Exigences Non-Fonctionnelles (NFR)

- **Sécurité et Conformité :** Alignement strict sur la loi ivoirienne n°2013-450 relative à la protection des données à caractère personnel. Données stockées obligatoirement sur le territoire national.
- **Performance :** Le déchiffrement et l'affichage du dossier sur l'écran du médecin après le scan du QR code ne doivent pas prendre plus de **3 secondes** sous couverture 3G stable.
- **Expérience Utilisateur (UX) :** L'application du médecin doit pouvoir être prise en main avec moins de 5 minutes de formation (interface ultra-épurée, pas de menus complexes).
