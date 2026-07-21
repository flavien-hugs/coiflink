// Statut d'un rendez-vous côté client (domaine réservation, #22).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète la valeur `status` renvoyée par le backend #21 (`AppointmentStatus`
// serveur), avec un **libellé d'affichage** francophone. La valeur initiale d'une
// réservation cliente est `PENDING` → « En attente » (critère d'acceptation #22).

/// Statuts possibles d'un rendez-vous, calqués sur l'énumération serveur.
///
/// [unknown] est un défaut **prudent** : une valeur de statut non reconnue (p. ex.
/// une évolution serveur) ne doit jamais faire planter la désérialisation cliente.
enum AppointmentStatus {
  pending,
  confirmed,
  cancelled,
  completed,
  noShow,
  unknown;

  /// Mappe la chaîne backend (`"PENDING"`, `"CONFIRMED"`, …) vers l'énumération.
  ///
  /// Insensible à la casse et tolérante : une valeur inconnue devient [unknown]
  /// plutôt qu'une exception (robustesse face à une évolution du serveur).
  static AppointmentStatus fromApi(String? raw) {
    switch (raw?.toUpperCase()) {
      case 'PENDING':
        return AppointmentStatus.pending;
      case 'CONFIRMED':
        return AppointmentStatus.confirmed;
      case 'CANCELLED':
        return AppointmentStatus.cancelled;
      case 'COMPLETED':
        return AppointmentStatus.completed;
      case 'NO_SHOW':
        return AppointmentStatus.noShow;
      default:
        return AppointmentStatus.unknown;
    }
  }

  /// Libellé francophone affiché au client (§7.1).
  String get label {
    switch (this) {
      case AppointmentStatus.pending:
        return 'En attente';
      case AppointmentStatus.confirmed:
        return 'Confirmé';
      case AppointmentStatus.cancelled:
        return 'Annulé';
      case AppointmentStatus.completed:
        return 'Terminé';
      case AppointmentStatus.noShow:
        return 'Absent';
      case AppointmentStatus.unknown:
        return 'Statut inconnu';
    }
  }
}
