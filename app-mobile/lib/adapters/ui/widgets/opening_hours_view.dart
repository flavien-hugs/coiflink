// Widget UI : affichage des horaires d'ouverture d'un salon (fiche, #19).
//
// Présentation pure : une ligne par jour de la semaine (ordre lun→dim), avec les
// intervalles d'ouverture ou « Fermé ». Le formatage est une responsabilité UI
// (spec, décision 5) ; l'entité `SalonOpeningHours` reste une donnée brute.

import 'package:flutter/material.dart';

import '../../../domain/salon/opening_hours.dart';

/// Libellés français des jours, indexés par la clé canonique du backend.
const Map<String, String> _dayLabels = <String, String>{
  'mon': 'Lundi',
  'tue': 'Mardi',
  'wed': 'Mercredi',
  'thu': 'Jeudi',
  'fri': 'Vendredi',
  'sat': 'Samedi',
  'sun': 'Dimanche',
};

class OpeningHoursView extends StatelessWidget {
  const OpeningHoursView({super.key, required this.openingHours});

  /// Horaires à afficher, ou `null` si le salon n'en a pas configuré.
  final SalonOpeningHours? openingHours;

  @override
  Widget build(BuildContext context) {
    final hours = openingHours;
    if (hours == null) {
      return const Text('Horaires non renseignés');
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (final dayKey in kWeekDayKeys)
          _DayRow(
            label: _dayLabels[dayKey] ?? dayKey,
            intervals: hours.intervalsFor(dayKey),
          ),
      ],
    );
  }
}

class _DayRow extends StatelessWidget {
  const _DayRow({required this.label, required this.intervals});

  final String label;
  final List<OpeningInterval> intervals;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final closed = intervals.isEmpty;
    final value = closed
        ? 'Fermé'
        : intervals.map((i) => '${i.start} – ${i.end}').join(', ');

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 96,
            child: Text(label, style: theme.textTheme.bodyMedium),
          ),
          Expanded(
            child: Text(
              value,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: closed ? theme.disabledColor : null,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
