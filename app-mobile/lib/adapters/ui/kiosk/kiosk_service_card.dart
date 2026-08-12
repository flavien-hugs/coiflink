// Carte tactile d'une prestation (US-004, #159).
//
// Grande cible (≥ 160×160 dp, §D) affichant la photo de la prestation (`imageUrl`,
// #158, avec repli sur un dégradé de marque + icône générique si absente ou si le
// réseau échoue), le nom, le prix et la durée. Bascule on/off (sélection
// **multiple**, §F.4) matérialisée par une bordure/badge — pas de radio
// (contrairement à `_ServiceStep`, à sélection unique).

import 'package:flutter/material.dart';

import '../../../domain/salon/salon_service.dart';
import 'kiosk_theme.dart';

/// Dégradés de repli tournants pour la vignette d'une prestation sans photo —
/// mêmes tons que la palette de marque, jamais une couleur hors charte.
const List<List<Color>> _fallbackGradients = <List<Color>>[
  <Color>[KioskColors.nude, Color(0xFFE0C19A)],
  <Color>[Color(0xFFECD8C8), Color(0xFFCF9A76)],
  <Color>[Color(0xFFE3D2BA), Color(0xFFA9805A)],
  <Color>[Color(0xFFDED2C6), KioskColors.gold],
];

class KioskServiceCard extends StatelessWidget {
  const KioskServiceCard({
    super.key,
    required this.service,
    required this.selected,
    required this.onTap,
  });

  final SalonService service;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final borderColor = selected ? KioskColors.accent : KioskColors.border;

    return ConstrainedBox(
      constraints: const BoxConstraints(
        minWidth: KioskDimensions.serviceCardMinSide,
        minHeight: KioskDimensions.serviceCardMinSide,
      ),
      child: Material(
        color: KioskColors.surface,
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(20),
          child: Container(
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(20),
              border: Border.all(
                color: borderColor,
                width: selected ? 2.5 : 1.5,
              ),
            ),
            child: Stack(
              children: <Widget>[
                Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Expanded(child: _image(theme)),
                      const SizedBox(height: 8),
                      Text(
                        service.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                      if (_subtitle().isNotEmpty) ...<Widget>[
                        const SizedBox(height: 2),
                        Text(
                          _subtitle(),
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(color: KioskColors.muted),
                        ),
                      ],
                    ],
                  ),
                ),
                if (selected)
                  Positioned(
                    top: 6,
                    right: 6,
                    child: Container(
                      width: 26,
                      height: 26,
                      alignment: Alignment.center,
                      decoration: const BoxDecoration(
                        color: KioskColors.accent,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.check,
                        size: 16,
                        color: KioskColors.accentForeground,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _image(ThemeData theme) {
    final imageUrl = service.imageUrl;
    final gradient = _fallbackGradients[service.id.hashCode.abs() % _fallbackGradients.length];
    final placeholder = Container(
      alignment: Alignment.center,
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: gradient,
        ),
      ),
      child: const Icon(Icons.content_cut, size: 32, color: KioskColors.ink),
    );
    if (imageUrl == null || imageUrl.isEmpty) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: placeholder,
      );
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: Image.network(
        imageUrl,
        fit: BoxFit.cover,
        width: double.infinity,
        // Une `image_url` signée expirée/injoignable retombe sur l'espace réservé,
        // sans casser la grille (repli silencieux, cohérent avec §G).
        errorBuilder: (context, error, stackTrace) => placeholder,
      ),
    );
  }

  String _subtitle() {
    final parts = <String>[
      if (service.price != null && service.price!.trim().isNotEmpty)
        '${service.price} F',
      if (service.durationMinutes != null) '${service.durationMinutes} min',
    ];
    return parts.join(' · ');
  }
}
