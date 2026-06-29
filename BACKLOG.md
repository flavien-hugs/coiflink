# Backlog — CoifLink (plateforme de gestion pour salons de coiffure)

> **Source :** dérivé de [`prd-coiflink.md`](./prd-coiflink.md) — §6 (Épics & User Stories), §18 (Roadmap Sprint 0→6), §22 (MoSCoW), §8 (Règles métier), §11 (Sécurité).
> **État du dépôt :** projet *greenfield* — aucun code applicatif, uniquement le PRD et l'outillage ADW.
> **Usage :** ce backlog est la source des **issues GitHub** consommées par le pipeline ADW
> (`scripts/run-issue.sh <N>` → `.claude/commands/issue.md`). Chaque item ci-dessous devient
> une issue numérotée `#N` ; ses *Critères d'acceptation* sont la **definition of done** et la
> ligne *Dépend de* est lue par l'orchestrateur pour bloquer un ordre invalide.

## Légende

- **Effort :** `S` (≤ 2 j) · `M` (3–5 j) · `L` (1–2+ semaines)
- **Priorité :** `Must` / `Should` / `Could` (MoSCoW, §22)
- **Étiquettes :** `feature`, `bug`, `tech-debt`, `docs`, `security`, `infra`, `ux`, `payments`, `notifications`

---

## Vue d'ensemble des jalons (milestones)

| Jalon | Sprint PRD | Objectif (1 ligne) | Épics couverts |
| ----- | ---------- | ------------------ | -------------- |
| **M0 — Socle & Préparation** | Sprint 0 | Figer stack, dépôt, schéma de données, CI et environnements avant toute fonctionnalité. | (transverse) |
| **M1 — Authentification & utilisateurs** | Sprint 1 | Comptes client/gérant/employé, connexion JWT, RBAC, squelette dashboard. | Épic 1 |
| **M2 — Salons & prestations** | Sprint 2 | Un gérant configure son salon ; un client le consulte et voit les prestations réservables. | Épic 2 |
| **M3 — Rendez-vous** | Sprint 3 | Boucle réservation → confirmation → planning, sans double-réservation. | Épic 3 |
| **M4 — Clients, encaissement & caisse** | Sprint 4 | Fiches clients, paiements liés aux prestations, journal de caisse horodaté. | Épics 4, 5 |
| **M5 — Dashboard & notifications** | Sprint 5 | KPI gérant/admin + notifications confirmation/rappel/annulation. | Épics 6, 7 |
| **M6 — Tests, corrections & production** | Sprint 6 | Durcissement, e2e, perf, déploiement et pilote 10 salons. | (transverse) |

**Chemin critique :** M0 → M1 → M2 → M3 → M4/M5 → M6.
M3 ne peut démarrer tant que le modèle de données (#3) et l'auth/RBAC (M1) ne sont pas figés ;
l'encaissement (M4) et les KPI (M5) dépendent de la boucle de rendez-vous (M3).

---

## M0 — Socle & Préparation (Sprint 0)

> **Objectif :** aucune fonctionnalité avant un socle décidé et reproductible. On fige ici la stack,
> le schéma de données (§9) et la chaîne d'intégration.

- **#1 — Choix de la stack technique & ADR** · `Must` · `M` · `docs` `infra`
  Trancher chaque brique recommandée au §10 : app mobile (**Flutter** vs React Native, Android prioritaire), interface web gérant/admin (**Next.js / React**), backend (**FastAPI** vs Django REST, API REST + JWT), données (**PostgreSQL + Redis**), stockage fichiers (S3-compatible), notifications (FCM + SMS). Documenter via des ADR.
  *Acceptation :* un ADR par décision majeure committé dans `docs/adr/` ; justification du compromis (coût, écosystème, cible Android entrée de gamme) ; aucune décision de stack ne reste ouverte pour M1.

- **#2 — Initialisation du dépôt & structure du projet** · `Must` · `S` · `infra`
  Créer l'arborescence (`app-mobile/`, `web-dashboard/`, `backend/`, `docs/`, `docs/adr/`, `specs/`), licence, `README` décrivant le projet et la commande de build/test de chaque paquet, `.gitignore`, conventions de commits.
  *Acceptation :* structure en place ; `README` documente comment builder et tester chaque paquet ; les chemins attendus par le pipeline ADW existent.
  *Dépend de :* #1.

- **#3 — Modèle de données & schéma initial PostgreSQL** · `Must` · `M` · `infra` `tech-debt`
  Implémenter le schéma des entités du §9 : `User`, `Salon`, `Service/Prestation`, `Appointment`, `CustomerProfile`, `Payment/Transaction`, `CashJournal`, `Notification`, avec migrations versionnées.
  *Acceptation :* migrations exécutables (up/down) ; contraintes clés (un RDV lié à un salon + ≥ 1 prestation §8.1, un paiement lié à une prestation/RDV §8.2) présentes ; schéma documenté.
  *Dépend de :* #1, #2.

- **#4 — Pipeline CI/CD (GitHub Actions)** · `Must` · `M` · `infra`
  Lint, tests unitaires, build des apps et du backend, scan de dépendances, à chaque PR ; build d'images Docker.
  *Acceptation :* CI verte obligatoire avant merge ; artefacts de build produits ; jobs séparés mobile/web/backend.
  *Dépend de :* #2.

- **#5 — Environnements & gestion des secrets** · `Should` · `M` · `infra` `security`
  Environnements dev/staging/prod, aucune clé en clair dans le dépôt, configuration par variables d'environnement, sauvegardes activées.
  *Acceptation :* secrets injectés hors dépôt ; `staging` reproductible ; politique de secrets documentée.
  *Dépend de :* #4.

- **#6 — Plan de tests & configuration du test gate ADW** · `Should` · `S` · `infra` `docs`
  Définir la stratégie de tests (unitaire/intégration/e2e) et câbler le test gate du pipeline (`MX_AGENT_TEST_CMD`, ex. `flutter test` côté mobile, `pytest` côté backend) dans `scripts/adw.env`.
  *Acceptation :* `MX_AGENT_TEST_CMD` documenté et fonctionnel ; un test trivial passe via le gate.
  *Dépend de :* #1, #4.

- **#7 — Maquettes UX/UI des écrans MVP** · `Should` · `M` · `ux` `docs`
  Maquettes des écrans du §7 (mobile client, web gérant, admin) couvrant les parcours du §5.
  *Acceptation :* maquettes des écrans Must validées ; référencées par les issues d'implémentation correspondantes.

---

## M1 — Authentification & utilisateurs (Sprint 1) — Épic 1

> **Critères de sortie (PRD) :** un utilisateur peut créer un compte ; un gérant peut se connecter ;
> les rôles sont séparés ; les accès non autorisés sont bloqués.

- **#8 — US-1.1 · Inscription client (nom, téléphone, mot de passe)** · `Must` · `M` · `feature` `security`
  Création de compte client par téléphone + mot de passe ; vérification OTP recommandée ; mot de passe chiffré (§11.1).
  *Acceptation :* un client crée un compte ; doublon de téléphone refusé ; mot de passe jamais stocké en clair ; OTP testable.
  *Dépend de :* #3.

- **#9 — Inscription gérant & création du compte propriétaire** · `Must` · `M` · `feature` `security`
  Onboarding gérant (compte propriétaire du salon), prérequis de US-2.1. Dérivé de §18 (Sprint 1) et §4.
  *Acceptation :* un gérant crée son compte ; rôle `Gérant` attribué ; prêt à créer un salon.
  *Dépend de :* #3.

- **#10 — US-1.2 · Connexion (téléphone/email + mot de passe, JWT)** · `Must` · `S` · `feature` `security`
  Connexion avec émission d'un JWT + refresh token sécurisé ; protection contre les tentatives répétées (§11.1).
  *Acceptation :* connexion valide émet un JWT ; identifiants invalides refusés ; rate-limit sur les échecs.
  *Dépend de :* #8.

- **#11 — US-1.3 · Réinitialisation du mot de passe (OTP)** · `Must` · `S` · `feature` `security`
  Réinitialisation par OTP SMS ou email.
  *Acceptation :* parcours de reset complet ; OTP à usage unique et expirant ; ancien mot de passe invalidé.
  *Dépend de :* #8.

- **#12 — Middleware d'autorisation & RBAC** · `Must` · `M` · `security`
  Modèle de rôles/permissions du §4 + règles d'isolation du §11.2 (un gérant ne voit que son salon, un coiffeur que son planning, un client que ses RDV). Dérivé de §18 (« Middleware permissions »).
  *Acceptation :* accès inter-salons bloqué ; tests d'autorisation négatifs par rôle ; routes protégées par défaut (deny-by-default).
  *Dépend de :* #10.

- **#13 — US-1.4 · Création/invitation de comptes employés** · `Should` · `M` · `feature`
  Le gérant crée ou invite des employés (coiffeurs) avec rôles.
  *Acceptation :* un gérant crée un compte coiffeur ; le coiffeur se connecte avec un périmètre restreint.
  *Dépend de :* #12.

- **#14 — Squelette du dashboard web gérant** · `Must` · `S` · `feature` `ux`
  Shell du dashboard (navigation, layout, garde d'authentification). Dérivé de §18 (« Base du dashboard ») et §7.2.
  *Acceptation :* le gérant authentifié atteint un dashboard vide protégé ; un non-authentifié est redirigé.
  *Dépend de :* #10, #12.

---

## M2 — Salons & prestations (Sprint 2) — Épic 2

> **Critères de sortie (PRD) :** un gérant configure son salon ; un client le consulte ;
> les prestations sont visibles et réservables.

- **#15 — US-2.1 · Création d'un salon** · `Must` · `M` · `feature`
  Nom, logo, description, téléphone, localisation, photos.
  *Acceptation :* un gérant crée un salon rattaché à son compte ; un salon sans horaire n'est pas encore réservable (§8.3).
  *Dépend de :* #9, #14.

- **#16 — US-2.2 · Configuration des horaires d'ouverture** · `Must` · `M` · `feature`
  Horaires par jour, jours fermés, pauses, jours exceptionnels.
  *Acceptation :* horaires enregistrés par salon ; un salon sans horaire ne peut pas recevoir de réservation (§8.3).
  *Dépend de :* #15.

- **#17 — US-2.3 · Ajout & gestion des prestations** · `Must` · `M` · `feature`
  Nom, durée, prix, description, catégorie ; ajout/modification/suppression.
  *Acceptation :* prestations CRUD par salon ; durée et prix obligatoires ; modification journalisée (§11.4).
  *Dépend de :* #15.

- **#18 — Recherche & liste des salons (côté client)** · `Must` · `M` · `feature` `ux`
  Écran de recherche/liste des salons (§7.1, parcours §5.1). Seuls les salons actifs sont visibles (§8.3).
  *Acceptation :* un client liste/recherche les salons actifs ; un salon désactivé n'apparaît pas.
  *Dépend de :* #15.

- **#19 — US-2.4 · Consultation d'un salon (côté client)** · `Must` · `M` · `feature` `ux`
  Affichage horaires, prestations, prix, localisation et disponibilité.
  *Acceptation :* le détail d'un salon montre prestations + horaires + dispo ; point d'entrée de la réservation.
  *Dépend de :* #16, #17, #18.

- **#20 — US-2.5 · Modification des informations du salon** · `Should` · `S` · `feature`
  Mise à jour des informations depuis le dashboard.
  *Acceptation :* le gérant met à jour son salon ; changements reflétés côté client.
  *Dépend de :* #15.

---

## M3 — Rendez-vous (Sprint 3) — Épic 3

> **Critères de sortie (PRD) :** un client réserve ; le salon confirme ; le planning se met à jour ;
> les notifications de base sont prêtes.

- **#21 — US-3.7 · Moteur de disponibilité & anti double-réservation** · `Must` · `M` · `feature`
  Vérification automatique des créneaux ; un créneau ne peut être réservé deux fois pour le même coiffeur (§8.1).
  *Acceptation :* deux réservations concurrentes sur le même créneau/coiffeur → une seule acceptée ; tests de concurrence.
  *Dépend de :* #16, #17.

- **#22 — US-3.1 · Réservation d'un rendez-vous (client)** · `Must` · `M` · `feature`
  Choix salon, prestation, date, heure, commentaire optionnel ; un RDV est lié à un salon + ≥ 1 prestation (§8.1).
  *Acceptation :* un client réserve un créneau disponible ; statut initial `en attente` ; RDV lié salon+prestation.
  *Dépend de :* #19, #21.

- **#23 — US-3.2 · Modification d'un rendez-vous (client)** · `Must` · `S` · `feature`
  Modification selon les règles du salon ; un RDV terminé n'est plus modifiable sauf par le gérant (§8.1).
  *Acceptation :* modification d'un RDV non terminé ; RDV terminé verrouillé côté client.
  *Dépend de :* #22.

- **#24 — US-3.3 · Annulation d'un rendez-vous (client)** · `Must` · `S` · `feature`
  Annulation avec motif optionnel ; un RDV annulé n'est pas comptabilisé dans le CA (§8.1).
  *Acceptation :* annulation selon la règle du salon ; RDV annulé exclu du chiffre d'affaires.
  *Dépend de :* #22.

- **#25 — US-3.4 · Confirmer/refuser un RDV & cycle de statuts (gérant)** · `Must` · `M` · `feature`
  Statuts : en attente, confirmé, annulé, terminé, absent ; assignation optionnelle d'un coiffeur (§8.1).
  *Acceptation :* transitions de statut valides ; transitions interdites bloquées ; changement journalisé (§11.4).
  *Dépend de :* #22.

- **#26 — US-3.5 · Planning du salon (vue calendrier)** · `Must` · `M` · `feature` `ux`
  Vue jour/semaine/mois des RDV confirmés/en attente/annulés/terminés (§5.2).
  *Acceptation :* le planning affiche les RDV du jour par statut ; se met à jour après changement de statut.
  *Dépend de :* #25.

- **#27 — US-3.6 · Planning personnel du coiffeur** · `Should` · `M` · `feature`
  Le coiffeur consulte les RDV qui lui sont assignés (§11.2 : il ne voit que les siens).
  *Acceptation :* un coiffeur voit uniquement son planning ; aucun accès aux RDV non assignés.
  *Dépend de :* #13, #26.

---

## M4 — Clients, encaissement & caisse (Sprint 4) — Épics 4 & 5

> **Critères de sortie (PRD) :** les paiements sont enregistrés ; le journal de caisse est consultable ;
> les prestations réalisées sont liées au chiffre d'affaires.

- **#28 — US-4.1 · Création d'une fiche client (gérant)** · `Must` · `M` · `feature`
  Nom, téléphone, genre optionnel, notes internes.
  *Acceptation :* le gérant crée une fiche client rattachée à son salon ; isolation par salon (§11.2).
  *Dépend de :* #12.

- **#29 — US-4.2 · Historique des visites d'un client (gérant)** · `Must` · `M` · `feature`
  Liste des RDV passés, prestations, montants.
  *Acceptation :* l'historique liste les RDV terminés du client avec prestations et montants.
  *Dépend de :* #25, #28.

- **#30 — US-4.4 · Historique de prestations (côté client mobile)** · `Should` · `S` · `feature`
  Historique depuis l'application mobile ; un client ne voit que ses propres RDV (§11.2).
  *Acceptation :* le client voit son historique de RDV terminés et rien d'autre.
  *Dépend de :* #25.

- **#31 — US-4.3 · Prestations préférées d'un client (stats)** · `Should` · `S` · `feature`
  Statistiques par client.
  *Acceptation :* affichage des prestations les plus fréquentes du client.
  *Dépend de :* #29.

- **#32 — US-4.5 · Note client privée** · `Could` · `S` · `feature`
  Notes privées : préférences, allergies, habitudes.
  *Acceptation :* le gérant ajoute/édite une note privée non visible du client.
  *Dépend de :* #28.

- **#33 — US-5.1 · Enregistrement d'un paiement** · `Must` · `M` · `feature` `payments`
  Montant, mode de paiement, prestation liée, client lié ; un paiement est lié à une prestation/RDV avec un utilisateur responsable (§8.2) ; le montant correspond à la prestation (§5.3).
  *Acceptation :* paiement enregistré et lié au RDV/prestation ; montant cohérent ; opération journalisée (§11.4).
  *Dépend de :* #25.

- **#34 — US-5.3 · Journal de caisse horodaté** · `Must` · `M` · `feature` `payments` `security`
  Journal horodaté avec l'utilisateur ayant enregistré l'opération ; un paiement validé n'est jamais supprimé, toute correction crée une opération d'ajustement (§8.2).
  *Acceptation :* chaque paiement apparaît horodaté + auteur ; suppression interdite ; correction = ligne d'ajustement.
  *Dépend de :* #33.

- **#35 — US-5.2 · Historique des transactions (filtrable)** · `Must` · `S` · `feature` `payments`
  Liste filtrable par date, client, montant, mode de paiement.
  *Acceptation :* filtres fonctionnels ; cohérence avec le journal de caisse.
  *Dépend de :* #33.

- **#36 — US-5.4 · Détection des écarts de caisse** · `Should` · `M` · `feature` `payments`
  Comparaison entre prestations réalisées et paiements enregistrés (§8.2).
  *Acceptation :* un RDV terminé sans paiement est signalé comme écart.
  *Dépend de :* #34.

- **#37 — US-5.6 · Supervision agrégée des transactions (admin)** · `Should` · `M` · `feature` `payments`
  Statistiques agrégées par salon, sans détails sensibles inutiles (§11.2/§11.3).
  *Acceptation :* l'admin voit des agrégats par salon sans PII de paiement superflue.
  *Dépend de :* #34.

- **#38 — US-5.5 · Reçu numérique de paiement (client)** · `Could` · `S` · `feature` `payments`
  Reçu numérique ou notification.
  *Acceptation :* un reçu est généré/envoyé après paiement.
  *Dépend de :* #33.

---

## M5 — Dashboard & notifications (Sprint 5) — Épics 6 & 7

> **Critères de sortie (PRD) :** le gérant suit son activité ; le client reçoit ses notifications ;
> les KPI MVP sont visibles.

- **#39 — US-6.1 · RDV du jour (dashboard)** · `Must` · `S` · `feature`
  Total, confirmés, annulés, terminés, absents.
  *Acceptation :* le dashboard affiche le décompte du jour par statut.
  *Dépend de :* #14, #25.

- **#40 — US-6.2 · Chiffre d'affaires (jour/semaine/mois)** · `Must` · `M` · `feature`
  CA journalier, hebdomadaire, mensuel ; les RDV annulés ne comptent pas (§8.1).
  *Acceptation :* CA calculé à partir des paiements ; annulés exclus ; périodes correctes.
  *Dépend de :* #33.

- **#41 — US-6.3 · Prestations les plus demandées** · `Must` · `M` · `feature`
  Classement par volume et revenu généré.
  *Acceptation :* top prestations par volume et par revenu.
  *Dépend de :* #33.

- **#42 — US-6.4 · Clients actifs** · `Must` · `M` · `feature`
  Nouveaux, récurrents, inactifs.
  *Acceptation :* segmentation des clients sur une période donnée.
  *Dépend de :* #29.

- **#43 — US-6.5 · Performance des coiffeurs** · `Should` · `M` · `feature`
  Nombre de prestations réalisées, CA généré, taux d'annulation.
  *Acceptation :* indicateurs par coiffeur cohérents avec le planning et la caisse.
  *Dépend de :* #27, #33.

- **#44 — US-6.6 · KPI globaux plateforme (admin)** · `Must` · `M` · `feature`
  Salons inscrits, abonnements, rendez-vous, revenus plateforme.
  *Acceptation :* dashboard admin avec KPI globaux agrégés.
  *Dépend de :* #37.

- **#45 — US-7.1 · Notification de confirmation de RDV** · `Must` · `M` · `feature` `notifications`
  Push, SMS ou WhatsApp selon disponibilité ; envoyée après chaque réservation (§8.4).
  *Acceptation :* une confirmation part à la création du RDV ; notification critique tracée (§8.4/§11.4).
  *Dépend de :* #22.

- **#46 — US-7.2 · Rappel automatique avant RDV** · `Must` · `M` · `feature` `notifications`
  Rappel configurable 24h / 2h / 30 min via jobs asynchrones.
  *Acceptation :* rappel planifié et envoyé à l'échéance ; annulation du RDV annule le rappel.
  *Dépend de :* #22.

- **#47 — US-7.3 · Notification au salon à la réservation** · `Must` · `S` · `feature` `notifications`
  Notification dashboard + option email/SMS.
  *Acceptation :* le salon est notifié à chaque nouvelle réservation.
  *Dépend de :* #22.

- **#48 — US-7.4 · Notification d'annulation/modification** · `Must` · `S` · `feature` `notifications`
  Notification automatique après changement de statut ; annulation notifie client + salon (§8.4).
  *Acceptation :* un changement de statut déclenche la notification aux parties concernées.
  *Dépend de :* #23, #24, #25.

- **#49 — US-7.5 · Campagnes/messages aux clients** · `Could` · `M` · `feature` `notifications`
  Campagnes simples : rappel, promotion, fermeture exceptionnelle.
  *Acceptation :* le gérant envoie un message à un segment de clients.
  *Dépend de :* #28.

---

## M6 — Tests, corrections & mise en production (Sprint 6)

> **Critères de sortie (PRD) :** MVP stable ; 10 salons pilotes prêts ; données de test validées ;
> monitoring activé ; support opérationnel.

- **#50 — Tests e2e des parcours critiques** · `Must` · `L` · `tests`
  Parcours réservation (§5.1), gestion RDV gérant (§5.2) et encaissement (§5.3) de bout en bout.
  *Acceptation :* suite e2e verte sur les parcours Must ; intégrée à la CI (#4).
  *Dépend de :* M3, M4, M5.

- **#51 — Tests de sécurité (authz, JWT, données perso)** · `Must` · `M` · `security` `tests`
  Vérifier RBAC/isolation par salon (§11.2), JWT/refresh, protection brute-force, journalisation des accès sensibles (§11.3/§11.4).
  *Acceptation :* tests négatifs d'autorisation par rôle ; aucune fuite inter-salons ; accès sensibles journalisés.
  *Dépend de :* #12.

- **#52 — Tests de performance** · `Should` · `M` · `tests`
  Charge sur les endpoints critiques selon les cibles du §12.1.
  *Acceptation :* temps de réponse dans les budgets du §12 sous charge nominale.
  *Dépend de :* M3, M4.

- **#53 — Documentation utilisateur** · `Should` · `M` · `docs`
  Guides gérant et client.
  *Acceptation :* documentation des parcours Must publiée.

- **#54 — Déploiement production** · `Must` · `L` · `infra`
  Docker, hébergement cloud sécurisé, sauvegardes automatiques, monitoring.
  *Acceptation :* prod déployée et monitorée ; sauvegardes vérifiées ; rollback documenté.
  *Dépend de :* #5.

- **#55 — Préparation du pilote (10 salons) & formation** · `Should` · `M` · `docs`
  Données de test, onboarding et formation des salons pilotes, suivi post-lancement.
  *Acceptation :* 10 salons pilotes prêts ; support opérationnel en place.
  *Dépend de :* #54.

---

## Hors périmètre MVP (§21 / §22 « Won't Have »)

Reportés en V2+ (suivis ailleurs, **pas** dans ce backlog MVP) : paiement Mobile Money automatisé,
borne intelligente d'accueil (§17), IA de recommandation, gestion de stock, multi-salons avancé,
marketplace produits, programme de fidélité, QR code de présence.
