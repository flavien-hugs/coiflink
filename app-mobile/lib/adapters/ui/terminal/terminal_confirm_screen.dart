// Vérification avant création du ticket (US-005, #159 · consomme #157).
//
// Dernier point de contrôle : récapitule le client et les prestations choisies
// **avant** d'appeler `joinQueue` (#157) — jusque-là, aucune écriture n'a eu lieu.
// « Confirmer » crée le ticket et enchaîne vers le numéro de passage (US-006) ;
// « Modifier mon choix » (et le chevron retour) reviennent au choix de prestation
// (US-004) sans rien avoir créé.
//
// Erreur réseau → message neutre, sélection conservée, aucune navigation automatique
// (décision n°9, « toujours en direct »), comme les écrans précédents du parcours.

import 'package:flutter/material.dart';

import '../../../application/ports/terminal_queue_gateway.dart';
import '../../../domain/salon/salon_service.dart';
import 'terminal_deps.dart';
import 'terminal_theme.dart';
import 'terminal_ticket_number_screen.dart';
import 'terminal_widgets.dart';

class TerminalConfirmScreen extends StatefulWidget {
  const TerminalConfirmScreen({
    super.key,
    required this.deps,
    required this.customerProfileId,
    required this.customerFirstName,
    required this.salonName,
    required this.services,
  });

  final TerminalDeps deps;
  final String customerProfileId;
  final String customerFirstName;
  final String salonName;

  /// Prestations choisies sur US-004 (≥ 1) — pas encore de ticket créé.
  final List<SalonService> services;

  @override
  State<TerminalConfirmScreen> createState() => _TerminalConfirmScreenState();
}

class _TerminalConfirmScreenState extends State<TerminalConfirmScreen> {
  bool _submitting = false;
  String? _error;

  Future<void> _confirm() async {
    if (_submitting) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final ticket = await widget.deps.queueGateway.joinQueue(
        customerProfileId: widget.customerProfileId,
        serviceIds: widget.services.map((s) => s.id).toList(growable: false),
      );
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => TerminalTicketNumberScreen(
            deps: widget.deps,
            ticket: ticket,
            salonName: widget.salonName,
            serviceNames: widget.services.map((s) => s.name).toList(growable: false),
          ),
        ),
      );
    } on TerminalQueueException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _submitting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Stack(
        children: <Widget>[
          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(
                TerminalDimensions.screenPadding,
                72,
                TerminalDimensions.screenPadding,
                TerminalDimensions.screenPadding,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  Text(
                    'Vérifiez',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.headlineSmall
                        ?.copyWith(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    "Un dernier coup d'œil avant validation.",
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: TerminalColors.muted),
                  ),
                  const SizedBox(height: TerminalDimensions.screenPadding),
                  _ConfirmCard(
                    customerFirstName: widget.customerFirstName,
                    services: widget.services,
                  ),
                  if (_error != null) ...<Widget>[
                    const SizedBox(height: TerminalDimensions.touchSpacing),
                    Text(
                      _error!,
                      textAlign: TextAlign.center,
                      style: TextStyle(color: theme.colorScheme.error),
                    ),
                  ],
                  const SizedBox(height: TerminalDimensions.screenPadding),
                  FilledButton(
                    onPressed: _submitting ? null : _confirm,
                    child: _submitting
                        ? const SizedBox(
                            height: 24,
                            width: 24,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Confirmer'),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: _submitting
                        ? null
                        : () => Navigator.of(context).maybePop(),
                    child: const Text('Modifier mon choix'),
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

class _ConfirmCard extends StatelessWidget {
  const _ConfirmCard({required this.customerFirstName, required this.services});

  final String customerFirstName;
  final List<SalonService> services;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[
      _row(context, 'Client', customerFirstName),
      for (final service in services)
        _row(context, service.name, _serviceLine(service)),
    ];
    return Container(
      decoration: BoxDecoration(
        color: TerminalColors.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: TerminalColors.border, width: 1.5),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Column(
        children: <Widget>[
          for (var i = 0; i < rows.length; i++) ...<Widget>[
            if (i > 0) const Divider(height: 1),
            rows[i],
          ],
        ],
      ),
    );
  }

  Widget _row(BuildContext context, String label, String value) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: <Widget>[
          Text(label, style: theme.textTheme.bodyMedium?.copyWith(color: TerminalColors.muted)),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }

  String _serviceLine(SalonService service) {
    final parts = <String>[
      if (service.price != null && service.price!.trim().isNotEmpty)
        '${service.price} F',
      if (service.durationMinutes != null) '${service.durationMinutes} min',
    ];
    return parts.isEmpty ? '—' : parts.join(' · ');
  }
}
