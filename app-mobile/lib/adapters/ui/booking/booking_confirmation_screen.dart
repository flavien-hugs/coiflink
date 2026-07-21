// Écran UI : confirmation de réservation (§7.1, #22).
//
// Affiché après un `POST` réussi, à partir de la **réponse** du backend (aucune
// lecture supplémentaire) : récapitulatif du RDV et statut initial **« En
// attente »** (`AppointmentStatus.pending` → libellé). L'étape « Notification »
// (§8.4) relève de l'Épic 7 — ici, la confirmation est **à l'écran**.

import 'package:flutter/material.dart';

import '../../../domain/appointment/appointment.dart';
import 'booking_labels.dart';

class BookingConfirmationScreen extends StatelessWidget {
  const BookingConfirmationScreen({
    super.key,
    required this.appointment,
    required this.salonName,
    required this.serviceName,
  });

  final Appointment appointment;
  final String salonName;
  final String serviceName;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Réservation'),
        automaticallyImplyLeading: false,
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: <Widget>[
          Icon(
            Icons.check_circle_outline,
            size: 72,
            color: theme.colorScheme.primary,
          ),
          const SizedBox(height: 16),
          Text(
            'Votre demande de réservation est enregistrée.',
            style: theme.textTheme.titleMedium,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 8),
          Center(
            child: Chip(
              avatar: const Icon(Icons.hourglass_top, size: 18),
              // Statut initial d'une réservation cliente (critère d'acceptation #22).
              label: Text(appointment.status.label),
            ),
          ),
          const SizedBox(height: 24),
          _RecapTile(label: 'Salon', value: salonName),
          _RecapTile(label: 'Prestation', value: serviceName),
          _RecapTile(
            label: 'Date',
            value: formatFullDate(appointment.date),
          ),
          _RecapTile(
            label: 'Créneau',
            value: '${appointment.startTime} – ${appointment.endTime}',
          ),
          if (appointment.clientNote != null &&
              appointment.clientNote!.trim().isNotEmpty)
            _RecapTile(label: 'Commentaire', value: appointment.clientNote!.trim()),
          const SizedBox(height: 32),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Terminer'),
            ),
          ),
        ],
      ),
    );
  }
}

class _RecapTile extends StatelessWidget {
  const _RecapTile({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 110,
            child: Text(label, style: theme.textTheme.labelLarge),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
