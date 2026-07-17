// Widget UI : carte d'un salon dans la liste du catalogue (#18).
//
// Présentation pure : nom, localisation, logo (URL signée) et badge de
// réservabilité (§8.3). Ne porte aucune règle métier ni appel réseau.

import 'package:flutter/material.dart';

import '../../../domain/salon/salon_summary.dart';

class SalonCard extends StatelessWidget {
  const SalonCard({super.key, required this.salon});

  final SalonSummary salon;

  @override
  Widget build(BuildContext context) {
    final location = salon.locationLabel;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: ListTile(
        leading: _Logo(url: salon.logoUrl),
        title: Text(salon.name),
        subtitle: location.isEmpty ? null : Text(location),
        trailing: _BookableBadge(isBookable: salon.isBookable),
      ),
    );
  }
}

class _Logo extends StatelessWidget {
  const _Logo({required this.url});

  final String? url;

  @override
  Widget build(BuildContext context) {
    if (url == null) {
      return const CircleAvatar(child: Icon(Icons.store));
    }
    return CircleAvatar(
      backgroundImage: NetworkImage(url!),
      onBackgroundImageError: (_, _) {},
    );
  }
}

class _BookableBadge extends StatelessWidget {
  const _BookableBadge({required this.isBookable});

  final bool isBookable;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = isBookable ? 'Réservable' : 'Bientôt disponible';
    final color = isBookable ? Colors.green : theme.disabledColor;

    return Chip(
      label: Text(label),
      labelStyle: theme.textTheme.labelSmall,
      backgroundColor: color.withValues(alpha: 0.12),
      side: BorderSide(color: color),
      visualDensity: VisualDensity.compact,
    );
  }
}
