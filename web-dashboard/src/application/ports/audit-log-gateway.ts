// Port sortant (driven) vers l'API journal d'audit du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent
// **fetch et cookie** ; ce port abstrait le contrat de
// `GET /salons/{id}/audit-logs` (lecture seule). Implémenté par un adapter
// dans `src/adapters/api/`.

import type {
  AuditLogFilterInput,
  AuditLogPage,
  AuditLogPageOptions,
} from "@/src/domain/audit/audit-log";

// `invalid` = `422` (filtre incohérent côté backend : plage de dates ou
// catégorie), les autres motifs sont **génériques** (aucune divulgation).
export type ListAuditLogsResult =
  | { ok: true; page: AuditLogPage }
  | {
      ok: false;
      reason: "invalid" | "forbidden" | "unauthenticated" | "unavailable";
    };

export interface AuditLogGateway {
  // Proxifie `GET /salons/{id}/audit-logs` : liste **filtrable** (plage de
  // dates + catégorie) et paginée du journal d'audit du salon, du plus récent
  // au plus ancien. Le filtrage est **serveur** ; les critères sont sérialisés
  // en query params.
  listAuditLogs(
    salonId: string,
    filter: AuditLogFilterInput,
    page?: AuditLogPageOptions,
  ): Promise<ListAuditLogsResult>;
}
