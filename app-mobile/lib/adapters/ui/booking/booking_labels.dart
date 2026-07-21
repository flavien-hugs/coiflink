// Helpers d'affichage des dates du tunnel de réservation (#22).
//
// Formatage **local** francophone sans dépendance `intl` : le tunnel raisonne en
// composantes de date (repère Africa/Abidjan UTC+0), jamais en conversion de
// fuseau. Fonctions pures, réutilisables par les écrans du tunnel.

const List<String> _weekdaysShort = <String>[
  'lun.',
  'mar.',
  'mer.',
  'jeu.',
  'ven.',
  'sam.',
  'dim.',
];

const List<String> _weekdaysLong = <String>[
  'Lundi',
  'Mardi',
  'Mercredi',
  'Jeudi',
  'Vendredi',
  'Samedi',
  'Dimanche',
];

const List<String> _monthsLong = <String>[
  'janvier',
  'février',
  'mars',
  'avril',
  'mai',
  'juin',
  'juillet',
  'août',
  'septembre',
  'octobre',
  'novembre',
  'décembre',
];

/// Étiquette compacte d'un jour sélectionnable : « lun. 21/07 ».
String formatDateChip(DateTime date) {
  final wd = _weekdaysShort[date.weekday - 1];
  final d = date.day.toString().padLeft(2, '0');
  final m = date.month.toString().padLeft(2, '0');
  return '$wd $d/$m';
}

/// Étiquette complète d'une date : « Lundi 21 juillet 2026 ».
String formatFullDate(DateTime date) {
  final wd = _weekdaysLong[date.weekday - 1];
  final month = _monthsLong[date.month - 1];
  return '$wd ${date.day} $month ${date.year}';
}
