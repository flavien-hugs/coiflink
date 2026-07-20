// Widget UI : ligne d'une prestation dans la fiche salon (#19).
//
// Présentation pure : nom, durée et éventuelle description à gauche, prix à
// droite. Ne porte aucune règle métier ni appel réseau. Seules les prestations
// `ACTIVE` parviennent ici (filtre côté backend).

import 'package:flutter/material.dart';

import '../../../domain/salon/salon_service.dart';

class ServiceListTile extends StatelessWidget {
  const ServiceListTile({super.key, required this.service});

  final SalonService service;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final subtitleParts = <String>[
      if (service.durationMinutes != null) '${service.durationMinutes} min',
      if (service.description != null && service.description!.trim().isNotEmpty)
        service.description!.trim(),
    ];

    return ListTile(
      title: Text(service.name),
      subtitle:
          subtitleParts.isEmpty ? null : Text(subtitleParts.join(' · ')),
      trailing: service.price == null
          ? null
          : Text(
              '${service.price} FCFA',
              style: theme.textTheme.titleSmall,
            ),
    );
  }
}
