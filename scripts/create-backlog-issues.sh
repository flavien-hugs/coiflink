#!/usr/bin/env bash
# Pousse BACKLOG.md dans GitHub : crée les labels, les milestones (M0–M6) et les
# 55 issues, dans l'ordre, avec leurs critères d'acceptation et dépendances.
#
# Prérequis : gh (GitHub CLI) authentifié pour le dépôt cible (gh auth login).
#
# IMPORTANT — numérotation : BACKLOG.md référence ses issues par #1..#55 et les
# lignes « Dépend de #N ». GitHub attribue les numéros séquentiellement et les
# partage entre issues ET pull requests. Ce script REFUSE de tourner si le dépôt
# contient déjà une issue ou une PR, sinon #1..#55 ne correspondraient plus.
#
# Usage :
#   scripts/create-backlog-issues.sh --dry-run   # aperçu, aucun appel d'écriture
#   scripts/create-backlog-issues.sh             # crée réellement (demande confirmation)
set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

command -v gh >/dev/null 2>&1 || { echo "error: gh CLI introuvable — https://cli.github.com" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "error: gh non authentifié — lance: gh auth login" >&2; exit 1; }

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo ">> dépôt : $REPO   (dry-run=$DRY_RUN)"

# --- garde-fou de numérotation ---------------------------------------------
if [ "$DRY_RUN" = 0 ]; then
  highest=$(gh api "repos/$REPO/issues?state=all&per_page=1&sort=created&direction=desc" -q '.[0].number // 0')
  if [ "$highest" != "0" ]; then
    echo "error: le dépôt contient déjà des issues/PR (plus haut numéro : #$highest)." >&2
    echo "       BACKLOG.md suppose un dépôt vierge (#1..#55). Repars d'un dépôt sans issue/PR" >&2
    echo "       ou ajuste manuellement les numéros 'Dépend de #N' après création." >&2
    exit 1
  fi
fi

# --- labels (idempotent : --force met à jour s'il existe) ------------------
mklabel() { # name color desc
  if [ "$DRY_RUN" = 1 ]; then echo "label  : $1"; return; fi
  gh label create "$1" --color "$2" --description "$3" --force >/dev/null
}
mklabel feature       1d76db "Nouvelle fonctionnalité"
mklabel bug           d73a4a "Anomalie"
mklabel tech-debt     fbca04 "Dette technique / fondations"
mklabel docs          0075ca "Documentation / ADR"
mklabel security      b60205 "Sécurité / autorisation"
mklabel infra         5319e7 "Infrastructure / CI / déploiement"
mklabel ux            e99695 "Expérience / interface"
mklabel payments      0e8a16 "Encaissement / caisse"
mklabel notifications c5def5 "Notifications"
mklabel tests         bfdadc "Tests / qualité"

# --- milestones (idempotent : créés seulement si absents) ------------------
mkmilestone() { # title description
  if [ "$DRY_RUN" = 1 ]; then echo "jalon  : $1"; return; fi
  local exists
  exists=$(gh api "repos/$REPO/milestones?state=all&per_page=100" -q ".[] | select(.title==\"$1\") | .number" 2>/dev/null | head -1)
  if [ -n "$exists" ]; then echo ">> jalon déjà présent : $1"; return; fi
  gh api "repos/$REPO/milestones" -f title="$1" -f description="$2" >/dev/null
  echo ">> jalon créé : $1"
}
M0="M0 — Socle & Préparation"
M1="M1 — Authentification & utilisateurs"
M2="M2 — Salons & prestations"
M3="M3 — Rendez-vous"
M4="M4 — Clients, encaissement & caisse"
M5="M5 — Dashboard & notifications"
M6="M6 — Tests, corrections & production"
mkmilestone "$M0" "Sprint 0 — Cadrage : stack, dépôt, schéma de données, CI, environnements."
mkmilestone "$M1" "Sprint 1 — Comptes, connexion JWT, RBAC, squelette dashboard."
mkmilestone "$M2" "Sprint 2 — Configuration salon, prestations, consultation client."
mkmilestone "$M3" "Sprint 3 — Réservation, statuts, planning, anti double-réservation."
mkmilestone "$M4" "Sprint 4 — Fiches clients, paiements, journal de caisse."
mkmilestone "$M5" "Sprint 5 — KPI gérant/admin, notifications."
mkmilestone "$M6" "Sprint 6 — Durcissement, e2e, perf, déploiement, pilote."

if [ "$DRY_RUN" = 0 ]; then
  printf '\n>> prêt à créer 55 issues sur %s. Continuer ? [y/N] ' "$REPO"
  read -r ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "annulé."; exit 0; }
fi

# --- issues (ordre strict = numérotation #1..#55) --------------------------
N=0
issue() { # title  milestone  labels   (corps sur stdin)
  N=$((N + 1))
  local title="$1" ms="$2" labels="$3" body
  body="$(cat)"
  if [ "$DRY_RUN" = 1 ]; then printf '#%-2s  %-55s [%s]\n' "$N" "$title" "$labels"; return; fi
  local args=(--title "$title" --milestone "$ms" --body "$body")
  local l; IFS=',' read -ra _L <<< "$labels"
  for l in "${_L[@]}"; do args+=(--label "$l"); done
  echo "#$N -> $(gh issue create "${args[@]}")"
  sleep 1   # évite les limites secondaires de l'API
}

############################  M0 — Socle & Préparation  ########################

issue "Choix de la stack technique & ADR" "$M0" "docs,infra" <<'BODY'
> Priorité Must · Effort M · PRD §10 / §18 Sprint 0

Trancher chaque brique recommandée au §10 et la figer via des ADR :
- app mobile : Flutter vs React Native (Android prioritaire)
- interface web gérant/admin : Next.js / React
- backend : FastAPI vs Django REST (API REST + JWT)
- données : PostgreSQL + Redis ; fichiers : S3-compatible ; notifications : FCM + SMS

**Critères d'acceptation :**
- Un ADR par décision majeure committé dans `docs/adr/`.
- Justification du compromis (coût, écosystème, cible Android entrée de gamme).
- Aucune décision de stack ne reste ouverte pour M1.
BODY

issue "Initialisation du dépôt & structure du projet" "$M0" "infra" <<'BODY'
> Priorité Must · Effort S · PRD §18 Sprint 0

Créer l'arborescence (`app-mobile/`, `web-dashboard/`, `backend/`, `docs/`, `docs/adr/`, `specs/`),
licence, README, `.gitignore`, conventions de commits.

**Critères d'acceptation :**
- Structure en place ; le README documente le build/test de chaque paquet.
- Les chemins attendus par le pipeline ADW existent.

**Dépend de :** #1
BODY

issue "Modèle de données & schéma initial PostgreSQL" "$M0" "infra,tech-debt" <<'BODY'
> Priorité Must · Effort M · PRD §9

Implémenter le schéma des entités du §9 (`User`, `Salon`, `Service`, `Appointment`,
`CustomerProfile`, `Payment`, `CashJournal`, `Notification`) avec migrations versionnées.

**Critères d'acceptation :**
- Migrations up/down exécutables.
- Contraintes clés présentes : RDV lié à un salon + ≥ 1 prestation (§8.1) ; paiement lié à une prestation/RDV (§8.2).
- Schéma documenté.

**Dépend de :** #1, #2
BODY

issue "Pipeline CI/CD (GitHub Actions)" "$M0" "infra" <<'BODY'
> Priorité Must · Effort M · PRD §10 / §18 Sprint 0

Lint, tests unitaires, build apps + backend, scan de dépendances à chaque PR ; build d'images Docker.

**Critères d'acceptation :**
- CI verte obligatoire avant merge.
- Artefacts de build produits ; jobs séparés mobile/web/backend.

**Dépend de :** #2
BODY

issue "Environnements & gestion des secrets" "$M0" "infra,security" <<'BODY'
> Priorité Should · Effort M · PRD §11 / §18 Sprint 0

Environnements dev/staging/prod ; aucune clé en clair dans le dépôt ; configuration par variables
d'environnement ; sauvegardes activées.

**Critères d'acceptation :**
- Secrets injectés hors dépôt ; `staging` reproductible ; politique de secrets documentée.

**Dépend de :** #4
BODY

issue "Plan de tests & configuration du test gate ADW" "$M0" "infra,docs" <<'BODY'
> Priorité Should · Effort S · PRD §18 Sprint 0

Définir la stratégie de tests (unitaire/intégration/e2e) et câbler le test gate du pipeline
(`MX_AGENT_TEST_CMD`, ex. `flutter test` / `pytest`) dans `scripts/adw.env`.

**Critères d'acceptation :**
- `MX_AGENT_TEST_CMD` documenté et fonctionnel ; un test trivial passe via le gate.

**Dépend de :** #1, #4
BODY

issue "Maquettes UX/UI des écrans MVP" "$M0" "ux,docs" <<'BODY'
> Priorité Should · Effort M · PRD §7 / §5

Maquettes des écrans du §7 (mobile client, web gérant, admin) couvrant les parcours du §5.

**Critères d'acceptation :**
- Maquettes des écrans Must validées et référencées par les issues d'implémentation correspondantes.
BODY

#######################  M1 — Authentification & utilisateurs  ################

issue "US-1.1 — Inscription client (nom, téléphone, mot de passe)" "$M1" "feature,security" <<'BODY'
> Priorité Must · Effort M · §6 Épic 1

En tant que client, je veux créer un compte avec mon numéro de téléphone afin de réserver un rendez-vous.
Spécifications : inscription par nom/téléphone/mot de passe ; OTP recommandé ; mot de passe chiffré (§11.1).

**Critères d'acceptation :**
- Un client crée un compte ; un doublon de téléphone est refusé.
- Le mot de passe n'est jamais stocké en clair ; l'OTP est testable.

**Dépend de :** #3
BODY

issue "Inscription gérant & création du compte propriétaire" "$M1" "feature,security" <<'BODY'
> Priorité Must · Effort M · §18 Sprint 1 / §4

Onboarding gérant (compte propriétaire du salon), prérequis de US-2.1.

**Critères d'acceptation :**
- Un gérant crée son compte ; le rôle `Gérant` est attribué ; prêt à créer un salon.

**Dépend de :** #3
BODY

issue "US-1.2 — Connexion (téléphone/email + mot de passe, JWT)" "$M1" "feature,security" <<'BODY'
> Priorité Must · Effort S · §6 Épic 1

Connexion avec émission d'un JWT + refresh token sécurisé ; protection contre les tentatives répétées (§11.1).

**Critères d'acceptation :**
- Une connexion valide émet un JWT ; des identifiants invalides sont refusés.
- Rate-limit sur les échecs de connexion.

**Dépend de :** #8
BODY

issue "US-1.3 — Réinitialisation du mot de passe (OTP)" "$M1" "feature,security" <<'BODY'
> Priorité Must · Effort S · §6 Épic 1

Réinitialisation par OTP SMS ou email.

**Critères d'acceptation :**
- Parcours de reset complet ; OTP à usage unique et expirant ; ancien mot de passe invalidé.

**Dépend de :** #8
BODY

issue "Middleware d'autorisation & RBAC" "$M1" "security" <<'BODY'
> Priorité Must · Effort M · §18 Sprint 1 / §4 / §11.2

Modèle de rôles/permissions (§4) + isolation (§11.2) : un gérant ne voit que son salon, un coiffeur
que son planning, un client que ses RDV.

**Critères d'acceptation :**
- Accès inter-salons bloqué ; tests d'autorisation négatifs par rôle.
- Routes protégées par défaut (deny-by-default).

**Dépend de :** #10
BODY

issue "US-1.4 — Création/invitation de comptes employés" "$M1" "feature" <<'BODY'
> Priorité Should · Effort M · §6 Épic 1

Le gérant crée ou invite des employés (coiffeurs) avec rôles.

**Critères d'acceptation :**
- Un gérant crée un compte coiffeur ; le coiffeur se connecte avec un périmètre restreint.

**Dépend de :** #12
BODY

issue "Squelette du dashboard web gérant" "$M1" "feature,ux" <<'BODY'
> Priorité Must · Effort S · §18 Sprint 1 / §7.2

Shell du dashboard : navigation, layout, garde d'authentification.

**Critères d'acceptation :**
- Un gérant authentifié atteint un dashboard vide protégé ; un non-authentifié est redirigé.

**Dépend de :** #10, #12
BODY

##########################  M2 — Salons & prestations  ########################

issue "US-2.1 — Création d'un salon" "$M2" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 2

Nom, logo, description, téléphone, localisation, photos.

**Critères d'acceptation :**
- Un gérant crée un salon rattaché à son compte.
- Un salon sans horaire n'est pas encore réservable (§8.3).

**Dépend de :** #9, #14
BODY

issue "US-2.2 — Configuration des horaires d'ouverture" "$M2" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 2

Horaires par jour, jours fermés, pauses, jours exceptionnels.

**Critères d'acceptation :**
- Horaires enregistrés par salon.
- Un salon sans horaire ne peut pas recevoir de réservation (§8.3).

**Dépend de :** #15
BODY

issue "US-2.3 — Ajout & gestion des prestations" "$M2" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 2

Nom, durée, prix, description, catégorie ; ajout/modification/suppression.

**Critères d'acceptation :**
- Prestations CRUD par salon ; durée et prix obligatoires ; modification journalisée (§11.4).

**Dépend de :** #15
BODY

issue "Recherche & liste des salons (côté client)" "$M2" "feature,ux" <<'BODY'
> Priorité Must · Effort M · §7.1 / §5.1

Écran de recherche/liste des salons. Seuls les salons actifs sont visibles (§8.3).

**Critères d'acceptation :**
- Un client liste/recherche les salons actifs ; un salon désactivé n'apparaît pas.

**Dépend de :** #15
BODY

issue "US-2.4 — Consultation d'un salon (côté client)" "$M2" "feature,ux" <<'BODY'
> Priorité Must · Effort M · §6 Épic 2

Affichage horaires, prestations, prix, localisation et disponibilité.

**Critères d'acceptation :**
- Le détail d'un salon montre prestations + horaires + disponibilité.
- C'est le point d'entrée de la réservation.

**Dépend de :** #16, #17, #18
BODY

issue "US-2.5 — Modification des informations du salon" "$M2" "feature" <<'BODY'
> Priorité Should · Effort S · §6 Épic 2

Mise à jour des informations depuis le dashboard.

**Critères d'acceptation :**
- Le gérant met à jour son salon ; les changements sont reflétés côté client.

**Dépend de :** #15
BODY

##############################  M3 — Rendez-vous  #############################

issue "US-3.7 — Moteur de disponibilité & anti double-réservation" "$M3" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 3 / §8.1

Vérification automatique des créneaux ; un créneau ne peut être réservé deux fois pour le même coiffeur (§8.1).

**Critères d'acceptation :**
- Deux réservations concurrentes sur le même créneau/coiffeur → une seule acceptée.
- Tests de concurrence.

**Dépend de :** #16, #17
BODY

issue "US-3.1 — Réservation d'un rendez-vous (client)" "$M3" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 3 / §8.1

Choix salon, prestation, date, heure, commentaire optionnel ; un RDV est lié à un salon + ≥ 1 prestation.

**Critères d'acceptation :**
- Un client réserve un créneau disponible ; statut initial `en attente`.
- RDV lié salon + prestation.

**Dépend de :** #19, #21
BODY

issue "US-3.2 — Modification d'un rendez-vous (client)" "$M3" "feature" <<'BODY'
> Priorité Must · Effort S · §6 Épic 3 / §8.1

Modification selon les règles du salon ; un RDV terminé n'est plus modifiable sauf par le gérant.

**Critères d'acceptation :**
- Modification d'un RDV non terminé ; RDV terminé verrouillé côté client.

**Dépend de :** #22
BODY

issue "US-3.3 — Annulation d'un rendez-vous (client)" "$M3" "feature" <<'BODY'
> Priorité Must · Effort S · §6 Épic 3 / §8.1

Annulation avec motif optionnel ; un RDV annulé n'est pas comptabilisé dans le CA.

**Critères d'acceptation :**
- Annulation selon la règle du salon ; RDV annulé exclu du chiffre d'affaires.

**Dépend de :** #22
BODY

issue "US-3.4 — Confirmer/refuser un RDV & cycle de statuts (gérant)" "$M3" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 3 / §8.1

Statuts : en attente, confirmé, annulé, terminé, absent ; assignation optionnelle d'un coiffeur.

**Critères d'acceptation :**
- Transitions de statut valides ; transitions interdites bloquées.
- Changement journalisé (§11.4).

**Dépend de :** #22
BODY

issue "US-3.5 — Planning du salon (vue calendrier)" "$M3" "feature,ux" <<'BODY'
> Priorité Must · Effort M · §6 Épic 3 / §5.2

Vue jour/semaine/mois des RDV par statut.

**Critères d'acceptation :**
- Le planning affiche les RDV du jour par statut et se met à jour après changement de statut.

**Dépend de :** #25
BODY

issue "US-3.6 — Planning personnel du coiffeur" "$M3" "feature" <<'BODY'
> Priorité Should · Effort M · §6 Épic 3 / §11.2

Le coiffeur consulte les RDV qui lui sont assignés (il ne voit que les siens).

**Critères d'acceptation :**
- Un coiffeur voit uniquement son planning ; aucun accès aux RDV non assignés.

**Dépend de :** #13, #26
BODY

#####################  M4 — Clients, encaissement & caisse  ###################

issue "US-4.1 — Création d'une fiche client (gérant)" "$M4" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 4

Nom, téléphone, genre optionnel, notes internes.

**Critères d'acceptation :**
- Le gérant crée une fiche client rattachée à son salon ; isolation par salon (§11.2).

**Dépend de :** #12
BODY

issue "US-4.2 — Historique des visites d'un client (gérant)" "$M4" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 4

Liste des RDV passés, prestations, montants.

**Critères d'acceptation :**
- L'historique liste les RDV terminés du client avec prestations et montants.

**Dépend de :** #25, #28
BODY

issue "US-4.4 — Historique de prestations (côté client mobile)" "$M4" "feature" <<'BODY'
> Priorité Should · Effort S · §6 Épic 4 / §11.2

Historique depuis l'application mobile ; un client ne voit que ses propres RDV.

**Critères d'acceptation :**
- Le client voit son historique de RDV terminés et rien d'autre.

**Dépend de :** #25
BODY

issue "US-4.3 — Prestations préférées d'un client (stats)" "$M4" "feature" <<'BODY'
> Priorité Should · Effort S · §6 Épic 4

Statistiques par client.

**Critères d'acceptation :**
- Affichage des prestations les plus fréquentes du client.

**Dépend de :** #29
BODY

issue "US-4.5 — Note client privée" "$M4" "feature" <<'BODY'
> Priorité Could · Effort S · §6 Épic 4

Notes privées : préférences, allergies, habitudes.

**Critères d'acceptation :**
- Le gérant ajoute/édite une note privée non visible du client.

**Dépend de :** #28
BODY

issue "US-5.1 — Enregistrement d'un paiement" "$M4" "feature,payments" <<'BODY'
> Priorité Must · Effort M · §6 Épic 5 / §8.2 / §5.3

Montant, mode de paiement, prestation liée, client lié ; paiement lié à une prestation/RDV avec
utilisateur responsable ; le montant correspond à la prestation.

**Critères d'acceptation :**
- Paiement enregistré et lié au RDV/prestation ; montant cohérent ; opération journalisée (§11.4).

**Dépend de :** #25
BODY

issue "US-5.3 — Journal de caisse horodaté" "$M4" "feature,payments,security" <<'BODY'
> Priorité Must · Effort M · §6 Épic 5 / §8.2

Journal horodaté + utilisateur ayant enregistré l'opération ; un paiement validé n'est jamais
supprimé ; toute correction crée une opération d'ajustement.

**Critères d'acceptation :**
- Chaque paiement apparaît horodaté + auteur ; suppression interdite ; correction = ligne d'ajustement.

**Dépend de :** #33
BODY

issue "US-5.2 — Historique des transactions (filtrable)" "$M4" "feature,payments" <<'BODY'
> Priorité Must · Effort S · §6 Épic 5

Liste filtrable par date, client, montant, mode de paiement.

**Critères d'acceptation :**
- Filtres fonctionnels ; cohérence avec le journal de caisse.

**Dépend de :** #33
BODY

issue "US-5.4 — Détection des écarts de caisse" "$M4" "feature,payments" <<'BODY'
> Priorité Should · Effort M · §6 Épic 5 / §8.2

Comparaison entre prestations réalisées et paiements enregistrés.

**Critères d'acceptation :**
- Un RDV terminé sans paiement est signalé comme écart.

**Dépend de :** #34
BODY

issue "US-5.6 — Supervision agrégée des transactions (admin)" "$M4" "feature,payments" <<'BODY'
> Priorité Should · Effort M · §6 Épic 5 / §11.2 / §11.3

Statistiques agrégées par salon, sans détails sensibles inutiles.

**Critères d'acceptation :**
- L'admin voit des agrégats par salon sans PII de paiement superflue.

**Dépend de :** #34
BODY

issue "US-5.5 — Reçu numérique de paiement (client)" "$M4" "feature,payments" <<'BODY'
> Priorité Could · Effort S · §6 Épic 5

Reçu numérique ou notification.

**Critères d'acceptation :**
- Un reçu est généré/envoyé après paiement.

**Dépend de :** #33
BODY

########################  M5 — Dashboard & notifications  #####################

issue "US-6.1 — RDV du jour (dashboard)" "$M5" "feature" <<'BODY'
> Priorité Must · Effort S · §6 Épic 6

Total, confirmés, annulés, terminés, absents.

**Critères d'acceptation :**
- Le dashboard affiche le décompte du jour par statut.

**Dépend de :** #14, #25
BODY

issue "US-6.2 — Chiffre d'affaires (jour/semaine/mois)" "$M5" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 6 / §8.1

CA journalier, hebdomadaire, mensuel ; les RDV annulés ne comptent pas.

**Critères d'acceptation :**
- CA calculé à partir des paiements ; annulés exclus ; périodes correctes.

**Dépend de :** #33
BODY

issue "US-6.3 — Prestations les plus demandées" "$M5" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 6

Classement par volume et revenu généré.

**Critères d'acceptation :**
- Top prestations par volume et par revenu.

**Dépend de :** #33
BODY

issue "US-6.4 — Clients actifs" "$M5" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 6

Nouveaux, récurrents, inactifs.

**Critères d'acceptation :**
- Segmentation des clients sur une période donnée.

**Dépend de :** #29
BODY

issue "US-6.5 — Performance des coiffeurs" "$M5" "feature" <<'BODY'
> Priorité Should · Effort M · §6 Épic 6

Nombre de prestations réalisées, CA généré, taux d'annulation.

**Critères d'acceptation :**
- Indicateurs par coiffeur cohérents avec le planning et la caisse.

**Dépend de :** #27, #33
BODY

issue "US-6.6 — KPI globaux plateforme (admin)" "$M5" "feature" <<'BODY'
> Priorité Must · Effort M · §6 Épic 6

Salons inscrits, abonnements, rendez-vous, revenus plateforme.

**Critères d'acceptation :**
- Dashboard admin avec KPI globaux agrégés.

**Dépend de :** #37
BODY

issue "US-7.1 — Notification de confirmation de RDV" "$M5" "feature,notifications" <<'BODY'
> Priorité Must · Effort M · §6 Épic 7 / §8.4

Push, SMS ou WhatsApp selon disponibilité ; envoyée après chaque réservation.

**Critères d'acceptation :**
- Une confirmation part à la création du RDV ; notification critique tracée (§8.4/§11.4).

**Dépend de :** #22
BODY

issue "US-7.2 — Rappel automatique avant RDV" "$M5" "feature,notifications" <<'BODY'
> Priorité Must · Effort M · §6 Épic 7

Rappel configurable 24h / 2h / 30 min via jobs asynchrones.

**Critères d'acceptation :**
- Rappel planifié et envoyé à l'échéance ; l'annulation du RDV annule le rappel.

**Dépend de :** #22
BODY

issue "US-7.3 — Notification au salon à la réservation" "$M5" "feature,notifications" <<'BODY'
> Priorité Must · Effort S · §6 Épic 7

Notification dashboard + option email/SMS.

**Critères d'acceptation :**
- Le salon est notifié à chaque nouvelle réservation.

**Dépend de :** #22
BODY

issue "US-7.4 — Notification d'annulation/modification" "$M5" "feature,notifications" <<'BODY'
> Priorité Must · Effort S · §6 Épic 7 / §8.4

Notification automatique après changement de statut ; une annulation notifie client + salon.

**Critères d'acceptation :**
- Un changement de statut déclenche la notification aux parties concernées.

**Dépend de :** #23, #24, #25
BODY

issue "US-7.5 — Campagnes/messages aux clients" "$M5" "feature,notifications" <<'BODY'
> Priorité Could · Effort M · §6 Épic 7

Campagnes simples : rappel, promotion, fermeture exceptionnelle.

**Critères d'acceptation :**
- Le gérant envoie un message à un segment de clients.

**Dépend de :** #28
BODY

####################  M6 — Tests, corrections & production  ###################

issue "Tests e2e des parcours critiques" "$M6" "tests" <<'BODY'
> Priorité Must · Effort L · §5 / §18 Sprint 6

Parcours réservation (§5.1), gestion RDV gérant (§5.2) et encaissement (§5.3) de bout en bout.

**Critères d'acceptation :**
- Suite e2e verte sur les parcours Must ; intégrée à la CI (#4).

**Dépend de :** jalons M3, M4, M5
BODY

issue "Tests de sécurité (authz, JWT, données perso)" "$M6" "security,tests" <<'BODY'
> Priorité Must · Effort M · §11

Vérifier RBAC/isolation par salon (§11.2), JWT/refresh, protection brute-force, journalisation des
accès sensibles (§11.3/§11.4).

**Critères d'acceptation :**
- Tests négatifs d'autorisation par rôle ; aucune fuite inter-salons ; accès sensibles journalisés.

**Dépend de :** #12
BODY

issue "Tests de performance" "$M6" "tests" <<'BODY'
> Priorité Should · Effort M · §12.1

Charge sur les endpoints critiques selon les cibles du §12.1.

**Critères d'acceptation :**
- Temps de réponse dans les budgets du §12 sous charge nominale.

**Dépend de :** jalons M3, M4
BODY

issue "Documentation utilisateur" "$M6" "docs" <<'BODY'
> Priorité Should · Effort M · §18 Sprint 6

Guides gérant et client.

**Critères d'acceptation :**
- Documentation des parcours Must publiée.
BODY

issue "Déploiement production" "$M6" "infra" <<'BODY'
> Priorité Must · Effort L · §10 / §18 Sprint 6

Docker, hébergement cloud sécurisé, sauvegardes automatiques, monitoring.

**Critères d'acceptation :**
- Prod déployée et monitorée ; sauvegardes vérifiées ; rollback documenté.

**Dépend de :** #5
BODY

issue "Préparation du pilote (10 salons) & formation" "$M6" "docs" <<'BODY'
> Priorité Should · Effort M · §18 Sprint 6

Données de test, onboarding et formation des salons pilotes, suivi post-lancement.

**Critères d'acceptation :**
- 10 salons pilotes prêts ; support opérationnel en place.

**Dépend de :** #54
BODY

echo
echo ">> terminé : $N issue(s) traitée(s)."
