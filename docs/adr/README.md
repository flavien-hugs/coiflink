# Architecture Decision Records (ADR)

Ce répertoire trace les **décisions d'architecture** de CoifLink. Chaque décision majeure fait
l'objet d'**un fichier ADR** versionné. Le format, la numérotation et les statuts sont définis par
**[ADR-0000](./0000-processus-et-gabarit-adr.md)**.

Les ADR sont la **source de vérité de la stack technique** (cf. README §4 et PRD §10). Une décision
n'est jamais réécrite : on en crée une nouvelle qui remplace l'ancienne (statut
`Remplacé par ADR-XXXX`).

## Index

| ADR | Titre | Statut | Issue |
| --- | --- | --- | --- |
| [0000](./0000-processus-et-gabarit-adr.md) | Processus et gabarit des ADR | Accepté | #1 |
| [0001](./0001-app-mobile-flutter.md) | Application mobile — Flutter | Accepté | #1 |
| [0002](./0002-web-gerant-admin-nextjs.md) | Interface web gérant / admin — Next.js (React) | Accepté | #1 |
| [0003](./0003-backend-fastapi.md) | Backend — FastAPI (API REST + JWT) | Accepté | #1 |
| [0004](./0004-donnees-postgresql-redis.md) | Données — PostgreSQL + Redis | Accepté | #1 |
| [0005](./0005-stockage-objet-s3-compatible.md) | Stockage de fichiers — objet S3-compatible | Accepté | #1 |
| [0006](./0006-notifications-fcm-sms.md) | Notifications — FCM + SMS | Accepté | #1 |
| [0007](./0007-arborescence-monorepo-versions.md) | Arborescence du monorepo, versions de référence & app web unique | Accepté | #2 |
| [0008](./0008-architecture-hexagonale.md) | Architecture hexagonale (ports & adapters) — tous les paquets | Accepté | suite #2 |

## Décisions volontairement différées (non bloquantes pour M1)

Ces points ne sont **pas** des décisions de stack majeures ouvertes ; ils sont rattachés à une issue
ultérieure et signalés en *Conséquences* des ADR concernés :

- **Plateforme d'hébergement & région des données** — ADR de déploiement (#4/#5).
- **Fournisseur SMS concret** (agrégateur local) — opérations (#5), voir ADR-0006.
- **Fournisseur de stockage objet** (AWS S3 / MinIO / R2 / bucket plateforme) — déploiement (#4/#5),
  voir ADR-0005.
- **ORM + migrations, runner de tâches async, libs JWT/hash** — voir ADR-0003, précisés en #3/#5/#6.
- **Versions de référence** (Flutter/Dart, Python, PostgreSQL, Redis, Node) — **arrêtées en #2**, voir
  [ADR-0007](./0007-arborescence-monorepo-versions.md).
