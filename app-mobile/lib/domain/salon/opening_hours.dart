// Entité de domaine « horaires d'ouverture » (fiche salon client, #19).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète le JSONB normalisé de `salons.opening_hours` (#16) tel que republié par
// la fiche publique `GET /catalog/salons/{id}` : fuseau + horaires hebdomadaires
// (jour → intervalles) + jours exceptionnels. Le formatage d'affichage est la
// responsabilité de la couche UI (spec, décision 5).

/// Ordre canonique des jours de la semaine (lun → dim) — miroir du backend.
const List<String> kWeekDayKeys = <String>[
  'mon',
  'tue',
  'wed',
  'thu',
  'fri',
  'sat',
  'sun',
];

/// Intervalle d'ouverture `HH:MM`–`HH:MM` (24 h).
class OpeningInterval {
  const OpeningInterval({required this.start, required this.end});

  final String start;
  final String end;
}

/// Surcharge datée : `closed=true` ⇒ fermé ; sinon horaires exceptionnels.
class OpeningException {
  const OpeningException({
    required this.date,
    required this.closed,
    this.intervals = const <OpeningInterval>[],
  });

  final String date;
  final bool closed;
  final List<OpeningInterval> intervals;
}

/// Horaires d'ouverture d'un salon (forme normalisée, lecture seule).
class SalonOpeningHours {
  const SalonOpeningHours({
    required this.timezone,
    required this.weekly,
    this.exceptions = const <OpeningException>[],
  });

  /// Fuseau horaire (p. ex. « Africa/Abidjan »).
  final String timezone;

  /// Intervalles par jour (`mon`, `tue`, …) ; un jour absent est **fermé**.
  final Map<String, List<OpeningInterval>> weekly;

  /// Surcharges datées (fermetures / horaires exceptionnels).
  final List<OpeningException> exceptions;

  /// Intervalles du jour donné (liste vide ⇒ jour fermé).
  List<OpeningInterval> intervalsFor(String dayKey) =>
      weekly[dayKey] ?? const <OpeningInterval>[];
}
