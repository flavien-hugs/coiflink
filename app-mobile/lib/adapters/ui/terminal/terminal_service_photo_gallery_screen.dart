// Visionneuse plein écran de la galerie d'une prestation (#160).
//
// Ouverte depuis le badge « N photos » de `TerminalServiceCard` — jamais
// depuis le tap de sélection de la ligne (geste distinct, voir ce fichier).
// Chrome minimal (fond sombre, nom en petit en haut, compteur + points en
// bas) : la photo est le seul contenu à regarder, cohérent avec le reste de
// la borne (peu de texte, grandes cibles tactiles). Balayage horizontal
// (`PageView`) entre les photos ; fermeture ramène à l'écran de sélection,
// sélection déjà faite préservée (aucun état de sélection ici).

import 'package:flutter/material.dart';

import '../../../domain/salon/salon_service.dart';
import 'terminal_theme.dart';

class TerminalServicePhotoGalleryScreen extends StatefulWidget {
  const TerminalServicePhotoGalleryScreen({super.key, required this.service});

  final SalonService service;

  @override
  State<TerminalServicePhotoGalleryScreen> createState() =>
      _TerminalServicePhotoGalleryScreenState();
}

class _TerminalServicePhotoGalleryScreenState
    extends State<TerminalServicePhotoGalleryScreen> {
  late final PageController _controller = PageController();
  int _index = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final photos = widget.service.photos;
    final total = photos.length;

    return Scaffold(
      backgroundColor: TerminalColors.ink,
      body: SafeArea(
        child: Column(
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
              child: Row(
                children: <Widget>[
                  _CloseButton(onTap: () => Navigator.of(context).maybePop()),
                  Expanded(
                    child: Text(
                      widget.service.name,
                      textAlign: TextAlign.center,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            color: TerminalColors.background,
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                  ),
                  const SizedBox(width: 44),
                ],
              ),
            ),
            Expanded(
              child: total == 0
                  ? const _PhotoPlaceholder()
                  : PageView.builder(
                      controller: _controller,
                      itemCount: total,
                      onPageChanged: (value) => setState(() => _index = value),
                      itemBuilder: (context, i) => _GalleryPhoto(url: photos[i].url),
                    ),
            ),
            if (total > 1) ...<Widget>[
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(
                  '${_index + 1} / $total',
                  style: TextStyle(
                    color: TerminalColors.background.withValues(alpha: 0.6),
                    fontSize: 12.5,
                    fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: List<Widget>.generate(total, (i) {
                    final active = i == _index;
                    return AnimatedContainer(
                      duration: const Duration(milliseconds: 220),
                      margin: const EdgeInsets.symmetric(horizontal: 3.5),
                      width: active ? 18 : 6,
                      height: 6,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(999),
                        color: active
                            ? TerminalColors.accent
                            : TerminalColors.background.withValues(alpha: 0.3),
                      ),
                    );
                  }),
                ),
              ),
            ] else
              const SizedBox(height: 26),
          ],
        ),
      ),
    );
  }
}

class _CloseButton extends StatelessWidget {
  const _CloseButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: TerminalColors.background.withValues(alpha: 0.1),
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: const SizedBox(
          width: 44,
          height: 44,
          child: Icon(
            Icons.close,
            size: 20,
            color: TerminalColors.background,
            semanticLabel: 'Fermer la galerie',
          ),
        ),
      ),
    );
  }
}

class _GalleryPhoto extends StatelessWidget {
  const _GalleryPhoto({required this.url});

  final String? url;

  @override
  Widget build(BuildContext context) {
    if (url == null || url!.isEmpty) {
      return const _PhotoPlaceholder();
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Image.network(
        url!,
        fit: BoxFit.contain,
        // Miroir `TerminalServiceCard._image` : repli silencieux, jamais une
        // erreur qui casse la visionneuse (§G).
        errorBuilder: (context, error, stackTrace) => const _PhotoPlaceholder(),
      ),
    );
  }
}

class _PhotoPlaceholder extends StatelessWidget {
  const _PhotoPlaceholder();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Icon(Icons.content_cut, size: 48, color: TerminalColors.gold),
    );
  }
}
