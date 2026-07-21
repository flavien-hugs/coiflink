// Créneau libre de réservation (domaine réservation, #22).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète un élément de `slots[]` renvoyé par `GET .../availability` (#21) : une
// date et un intervalle horaire `HH:MM` **libre**. La disponibilité ne renvoie
// **jamais** que des créneaux libres (§11.3) — ce value object ne porte aucune
// identité de qui occupe un créneau.

/// Un créneau **libre** proposé à la réservation : `date` + intervalle `HH:MM`.
class AvailabilitySlot {
  const AvailabilitySlot({
    required this.date,
    required this.start,
    required this.end,
  });

  /// Jour du créneau (composantes de date seules ; repère Africa/Abidjan UTC+0).
  final DateTime date;

  /// Heure de début, format `HH:MM` (repère UTC+0, cohérent avec le backend).
  final String start;

  /// Heure de fin, format `HH:MM`.
  final String end;

  @override
  bool operator ==(Object other) =>
      other is AvailabilitySlot &&
      other.date.year == date.year &&
      other.date.month == date.month &&
      other.date.day == date.day &&
      other.start == start &&
      other.end == end;

  @override
  int get hashCode => Object.hash(date.year, date.month, date.day, start, end);

  @override
  String toString() => 'AvailabilitySlot($start–$end)';
}
