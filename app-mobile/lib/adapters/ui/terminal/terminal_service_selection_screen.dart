// Choix de prestation(s) (US-004, #159 · consomme #158).
//
//  - **présentation** : liste de `TerminalServiceCard` (photo #158), **une
//    prestation par ligne** pleine largeur (jamais une grille à colonnes
//    multiples — lisibilité à distance constante, quelle que soit la largeur
//    de la tablette) ;
//  - **cardinalité** : sélection **multiple** (le contrat #157 accepte
//    `service_ids` au pluriel) — déviation assumée par rapport à un radio unique.
//
// Ne crée **pas** le ticket : transmet la sélection à `TerminalConfirmScreen` (US-005),
// point de contrôle avant l'appel `joinQueue` (#157).

import 'package:flutter/material.dart';

import '../../../application/ports/salon_catalog_gateway.dart';
import '../../../domain/salon/salon_detail.dart';
import '../../../domain/salon/salon_service.dart';
import 'terminal_confirm_screen.dart';
import 'terminal_deps.dart';
import 'terminal_service_card.dart';
import 'terminal_service_photo_gallery_screen.dart';
import 'terminal_theme.dart';
import 'terminal_unavailable_screen.dart';
import 'terminal_widgets.dart';

class TerminalServiceSelectionScreen extends StatefulWidget {
  const TerminalServiceSelectionScreen({
    super.key,
    required this.deps,
    required this.customerProfileId,
    required this.customerFirstName,
  });

  final TerminalDeps deps;

  /// Fiche client identifiée/créée — `customer_profile_id` que #157 consommera.
  final String customerProfileId;

  /// Prénom seul (§11.3) — affiché en en-tête, repris jusqu'à la confirmation (US-005).
  final String customerFirstName;

  @override
  State<TerminalServiceSelectionScreen> createState() =>
      _TerminalServiceSelectionScreenState();
}

class _TerminalServiceSelectionScreenState
    extends State<TerminalServiceSelectionScreen> {
  SalonDetail? _detail;
  bool _loading = true;
  bool _failed = false;

  final Set<String> _selectedIds = <String>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _failed = false;
    });
    try {
      final detail = await widget.deps.getSalonDetail.call(widget.deps.salonId);
      if (!mounted) return;
      setState(() {
        _detail = detail;
        _loading = false;
      });
    } on SalonCatalogException {
      if (!mounted) return;
      setState(() {
        _failed = true;
        _loading = false;
      });
    }
  }

  void _toggle(SalonService service) {
    setState(() {
      if (_selectedIds.contains(service.id)) {
        _selectedIds.remove(service.id);
      } else {
        _selectedIds.add(service.id);
      }
    });
  }

  void _viewPhotos(SalonService service) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (context) => TerminalServicePhotoGalleryScreen(service: service),
      ),
    );
  }

  void _continue(SalonDetail detail) {
    if (_selectedIds.isEmpty) return;
    final selected = detail.services
        .where((service) => _selectedIds.contains(service.id))
        .toList(growable: false);
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => TerminalConfirmScreen(
          deps: widget.deps,
          customerProfileId: widget.customerProfileId,
          customerFirstName: widget.customerFirstName,
          salonName: detail.name,
          services: selected,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_failed) {
      return TerminalUnavailableScreen(onRetry: _load);
    }
    if (_loading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    final theme = Theme.of(context);
    final detail = _detail!;
    final services = detail.services;

    return Scaffold(
      body: Stack(
        children: <Widget>[
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                TerminalDimensions.screenPadding,
                72,
                TerminalDimensions.screenPadding,
                0,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: <Widget>[
                  Text(
                    'Bonjour, ${widget.customerFirstName}',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.headlineSmall
                        ?.copyWith(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Choisissez vos prestations.',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: TerminalColors.muted),
                  ),
                  const SizedBox(height: TerminalDimensions.touchSpacing),
                  Expanded(
                    child: services.isEmpty
                        ? const Center(
                            child: Text('Ce salon ne propose aucune prestation.'),
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.only(
                              bottom: TerminalDimensions.screenPadding,
                            ),
                            // Liste **une prestation par ligne** (pleine largeur),
                            // jamais une grille à colonnes multiples.
                            separatorBuilder: (context, index) =>
                                const SizedBox(height: TerminalDimensions.touchSpacing),
                            itemCount: services.length,
                            itemBuilder: (context, index) {
                              final service = services[index];
                              return TerminalServiceCard(
                                service: service,
                                selected: _selectedIds.contains(service.id),
                                onTap: () => _toggle(service),
                                onViewPhotos: () => _viewPhotos(service),
                              );
                            },
                          ),
                  ),
                  SafeArea(
                    top: false,
                    child: Padding(
                      padding:
                          const EdgeInsets.only(bottom: TerminalDimensions.touchSpacing),
                      child: SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: (_selectedIds.isEmpty || services.isEmpty)
                              ? null
                              : () => _continue(detail),
                          child: Text(
                            _selectedIds.isEmpty
                                ? 'Sélectionnez au moins une prestation'
                                : 'Continuer',
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const TerminalBackButton(),
        ],
      ),
    );
  }
}
