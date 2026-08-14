// Carte tactile d'une prestation (US-004, #159 · galerie #160).
//
// Ligne pleine largeur (une prestation par ligne, §Design) : photo carrée à
// gauche (120×120 dp, dérivée de `TerminalDimensions.serviceRowHeight` moins
// le padding de la carte), nom, prix et durée à droite. La cible tactile
// réelle est la **ligne entière** (largeur d'écran × `serviceRowHeight`), pas
// la seule vignette. Repli sur un dégradé de marque + icône générique si la
// photo est absente ou si le réseau échoue. Bascule on/off (sélection
// **multiple**, §F.4) matérialisée par une bordure/badge — pas de radio
// (contrairement à `_ServiceStep`, à sélection unique).
//
// Galerie (#160) : un badge « pile de photos » apparaît en coin de la
// vignette **uniquement si la prestation a plus d'une photo** — cible
// tactile distincte du `onTap` de la ligne (sélection), ouvre
// `TerminalServicePhotoGalleryScreen` sur `onViewPhotos`. Aucun badge sur 0
// ou 1 photo : l'écran reste identique à avant la galerie.

import 'package:flutter/material.dart';

import '../../../domain/salon/salon_service.dart';
import 'terminal_theme.dart';

/// Dégradés de repli tournants pour la vignette d'une prestation sans photo —
/// mêmes tons que la palette de marque, jamais une couleur hors charte.
const List<List<Color>> _fallbackGradients = <List<Color>>[
  <Color>[TerminalColors.nude, Color(0xFFE0C19A)],
  <Color>[Color(0xFFECD8C8), Color(0xFFCF9A76)],
  <Color>[Color(0xFFE3D2BA), Color(0xFFA9805A)],
  <Color>[Color(0xFFDED2C6), TerminalColors.gold],
];

class TerminalServiceCard extends StatelessWidget {
  const TerminalServiceCard({
    super.key,
    required this.service,
    required this.selected,
    required this.onTap,
    this.onViewPhotos,
  });

  final SalonService service;
  final bool selected;
  final VoidCallback onTap;

  /// Ouvre la galerie plein écran de la prestation. `null` désactive le badge
  /// (aucun appelant qui ne veut pas de galerie n'a besoin de le filtrer par
  /// nombre de photos lui-même).
  final VoidCallback? onViewPhotos;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final borderColor = selected ? TerminalColors.accent : TerminalColors.border;

    return ConstrainedBox(
      constraints: const BoxConstraints(
        minHeight: TerminalDimensions.serviceRowHeight,
      ),
      child: Material(
        color: TerminalColors.surface,
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
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: <Widget>[
                      SizedBox(
                        width: TerminalDimensions.serviceRowHeight - 20,
                        height: TerminalDimensions.serviceRowHeight - 20,
                        child: Stack(
                          children: <Widget>[
                            Positioned.fill(child: _image(theme)),
                            if (service.photos.length > 1 && onViewPhotos != null)
                              Positioned(
                                right: 6,
                                bottom: 6,
                                child: _PhotoCountBadge(
                                  count: service.photos.length,
                                  serviceName: service.name,
                                  onTap: onViewPhotos!,
                                ),
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: <Widget>[
                            Text(
                              service.name,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                            if (_subtitle().isNotEmpty) ...<Widget>[
                              const SizedBox(height: 4),
                              Text(
                                _subtitle(),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.bodyMedium
                                    ?.copyWith(color: TerminalColors.muted),
                              ),
                            ],
                          ],
                        ),
                      ),
                      const SizedBox(width: 12),
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
                        color: TerminalColors.accent,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.check,
                        size: 16,
                        color: TerminalColors.accentForeground,
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
      child: const Icon(Icons.content_cut, size: 32, color: TerminalColors.ink),
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
        height: double.infinity,
        // Une `image_url` signée expirée/injoignable retombe sur l'espace réservé,
        // sans casser la liste (repli silencieux, cohérent avec §G).
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

/// Médaillon « N photos » — cible tactile distincte du `onTap` de la ligne
/// (sélection). `Semantics` porte le libellé complet ; le badge lui-même ne
/// montre que le compte, la borne privilégiant les gros repères visuels au
/// texte (§Design).
class _PhotoCountBadge extends StatelessWidget {
  const _PhotoCountBadge({
    required this.count,
    required this.serviceName,
    required this.onTap,
  });

  final int count;
  final String serviceName;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Voir les $count photos de $serviceName',
      child: Material(
        color: TerminalColors.ink.withValues(alpha: 0.78),
        shape: const StadiumBorder(
          side: BorderSide(color: Colors.white24, width: 1.2),
        ),
        child: InkWell(
          customBorder: const StadiumBorder(),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                const Icon(Icons.photo_library_outlined, size: 13, color: Colors.white),
                const SizedBox(width: 4),
                Text(
                  '$count',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    height: 1,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
