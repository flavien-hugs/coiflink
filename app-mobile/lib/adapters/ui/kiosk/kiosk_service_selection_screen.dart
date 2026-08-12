// Choix de prestation(s) (US-004, #159 · consomme #158).
//
//  - **présentation** : grille de `KioskServiceCard` (photo #158), toujours sur
//    **2 colonnes** (lisibilité à distance constante, quelle que soit la largeur de
//    la tablette — pas un nombre de colonnes qui varie avec l'espace disponible) ;
//  - **cardinalité** : sélection **multiple** (le contrat #157 accepte
//    `service_ids` au pluriel) — déviation assumée par rapport à un radio unique.
//
// Ne crée **pas** le ticket : transmet la sélection à `KioskConfirmScreen` (US-005),
// point de contrôle avant l'appel `joinQueue` (#157).

import 'package:flutter/material.dart';

import '../../../application/ports/salon_catalog_gateway.dart';
import '../../../domain/salon/salon_detail.dart';
import '../../../domain/salon/salon_service.dart';
import 'kiosk_confirm_screen.dart';
import 'kiosk_deps.dart';
import 'kiosk_service_card.dart';
import 'kiosk_theme.dart';
import 'kiosk_unavailable_screen.dart';
import 'kiosk_widgets.dart';

class KioskServiceSelectionScreen extends StatefulWidget {
  const KioskServiceSelectionScreen({
    super.key,
    required this.deps,
    required this.customerProfileId,
    required this.customerFirstName,
  });

  final KioskDeps deps;

  /// Fiche client identifiée/créée — `customer_profile_id` que #157 consommera.
  final String customerProfileId;

  /// Prénom seul (§11.3) — affiché en en-tête, repris jusqu'à la confirmation (US-005).
  final String customerFirstName;

  @override
  State<KioskServiceSelectionScreen> createState() =>
      _KioskServiceSelectionScreenState();
}

class _KioskServiceSelectionScreenState
    extends State<KioskServiceSelectionScreen> {
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

  void _continue(SalonDetail detail) {
    if (_selectedIds.isEmpty) return;
    final selected = detail.services
        .where((service) => _selectedIds.contains(service.id))
        .toList(growable: false);
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => KioskConfirmScreen(
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
      return KioskUnavailableScreen(onRetry: _load);
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
                KioskDimensions.screenPadding,
                72,
                KioskDimensions.screenPadding,
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
                        ?.copyWith(color: KioskColors.muted),
                  ),
                  const SizedBox(height: KioskDimensions.touchSpacing),
                  Expanded(
                    child: services.isEmpty
                        ? const Center(
                            child: Text('Ce salon ne propose aucune prestation.'),
                          )
                        : GridView.builder(
                            padding: const EdgeInsets.only(
                              bottom: KioskDimensions.screenPadding,
                            ),
                            // Grille **fixée** à 2 colonnes (lisibilité constante),
                            // jamais un nombre de colonnes dérivé de la largeur.
                            gridDelegate:
                                const SliverGridDelegateWithFixedCrossAxisCount(
                              crossAxisCount: 2,
                              crossAxisSpacing: KioskDimensions.touchSpacing,
                              mainAxisSpacing: KioskDimensions.touchSpacing,
                              mainAxisExtent: 224,
                            ),
                            itemCount: services.length,
                            itemBuilder: (context, index) {
                              final service = services[index];
                              return KioskServiceCard(
                                service: service,
                                selected: _selectedIds.contains(service.id),
                                onTap: () => _toggle(service),
                              );
                            },
                          ),
                  ),
                  SafeArea(
                    top: false,
                    child: Padding(
                      padding:
                          const EdgeInsets.only(bottom: KioskDimensions.touchSpacing),
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
          const KioskBackButton(),
        ],
      ),
    );
  }
}
