# ADR-0006 : Notifications — FCM + SMS

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10.2 (notifications), §8.4 (règles notifications), Épic 7, §11.3/§11.4
  (PII, journalisation), §16 (WhatsApp en V2)

## Contexte et problème

CoifLink doit notifier les utilisateurs : **confirmation, rappel et annulation** de rendez-vous
(Épic 7, §8.4), ainsi que l'**OTP** de réinitialisation (§11.1). La cible est Android prioritaire,
sur un marché où une partie des clients n'a pas (ou pas toujours) l'application installée. Le PRD
§10.2 recommande **Firebase Cloud Messaging** pour le push mobile et un **SMS local ou agrégateur**
comme canal complémentaire, **WhatsApp Business API étant repoussé en V2** (§16). Il faut figer les
**canaux**, sachant que le fournisseur SMS concret est une décision opérationnelle ultérieure.

## Options envisagées

- **Push mobile** : **Firebase Cloud Messaging (FCM)** — standard Android, gratuit, scalable.
- **Canal hors-app / repli** : **SMS** via agrégateur — universel (clients sans app, OTP).
- **WhatsApp Business API** : envisagé mais **différé en V2** (§16) — hors périmètre MVP.

## Décision

Les notifications MVP s'appuient sur **deux canaux** :

- **FCM** pour le **push mobile** (utilisateurs avec l'application) ;
- **SMS via agrégateur** pour les messages **hors-app** et l'**OTP**.

Les envois sont traités en **asynchrone** via la **file Redis** (cohérent avec ADR-0004 et le
backend FastAPI asynchrone, ADR-0003). **WhatsApp** est explicitement **reporté en V2**.

## Justification (compromis)

- **FCM** : standard de push Android (cible prioritaire), gratuit et scalable, bien intégré côté
  Flutter (ADR-0001).
- **SMS** : canal de **repli universel** indispensable pour les clients **sans application** et pour
  l'**OTP** (§8.4, §11.1), où la délivrabilité prime.
- **Asynchrone via Redis** : découple l'envoi des notifications du cycle requête/réponse de l'API
  (budget < 3 s, §12.1) et tolère les latences des fournisseurs externes.
- **WhatsApp différé** : maintient le périmètre MVP (§16) sans surcoût d'intégration immédiat.
- **Compromis accepté** : le SMS introduit une **dépendance à un fournisseur payant** ; le
  **prestataire concret** (agrégateur local Côte d'Ivoire / Afrique de l'Ouest) est une décision
  **opérationnelle différée** (#5). L'ADR fixe les **canaux**, pas le fournisseur.

## Conséquences

- **Positives** : couverture des utilisateurs avec et sans app ; envois asynchrones non bloquants ;
  périmètre MVP tenu.
- **Négatives / risques** : coût et délivrabilité SMS dépendants d'un tiers ; configuration FCM
  (projet Firebase, clés) à prévoir côté ops.
- **Sécurité (renvoi §11.3/§11.4)** — contraintes à respecter par l'implémentation (M5 — Épic 7) :
  - **ne jamais journaliser** le **corps des messages**, les **OTP**, ni les **numéros de
    téléphone / identifiants** (PII) ;
  - **clés FCM et identifiants SMS gérés hors dépôt** (#5), jamais committés ;
  - journalisation limitée aux métadonnées non sensibles (statut d'envoi, horodatage) — la
    journalisation des accès sensibles reste portée par le backend (§11.4).
- **Suivi / à confirmer (non bloquant)** :
  - **fournisseur SMS concret** (agrégateur local) → décision opérationnelle #5 ;
  - intégration WhatsApp → **V2** (§16), hors périmètre M1–M6 MVP courant ;
  - **runner de tâches asynchrones** consommant la file Redis → voir ADR-0003 et #5/#6.
