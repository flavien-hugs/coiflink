// Numéro de passage (US-006, #159 · consomme #157).
//
// Écran de lecture pure : le ticket est **déjà créé** (par US-005) — ce numéro et
// cette estimation d'attente sont figés à l'émission, seulement affichés ici. Aucune
// action cliente possible : le parcours enchaîne **seul**, après un court délai de
// lecture, vers l'impression (US-007). Le minuteur d'inactivité tourne normalement
// ici — seule l'impression (US-007) le suspend.

import 'dart:async';

import 'package:flutter/material.dart';

import '../../../application/ports/kiosk_queue_gateway.dart';
import 'kiosk_deps.dart';
import 'kiosk_print_screen.dart';
import 'kiosk_theme.dart';
import 'ticket_preview.dart';

/// Délai de lecture avant l'enchaînement automatique vers l'impression (US-007).
const Duration _autoAdvanceDelay = Duration(milliseconds: 1800);

class KioskTicketNumberScreen extends StatefulWidget {
  const KioskTicketNumberScreen({
    super.key,
    required this.deps,
    required this.ticket,
    required this.salonName,
    required this.serviceNames,
  });

  final KioskDeps deps;
  final QueueTicket ticket;
  final String salonName;
  final List<String> serviceNames;

  @override
  State<KioskTicketNumberScreen> createState() =>
      _KioskTicketNumberScreenState();
}

class _KioskTicketNumberScreenState extends State<KioskTicketNumberScreen> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer(_autoAdvanceDelay, _advance);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _advance() {
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(
        builder: (_) => KioskPrintScreen(
          deps: widget.deps,
          ticket: widget.ticket,
          salonName: widget.salonName,
          serviceNames: widget.serviceNames,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(KioskDimensions.screenPadding),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  'Votre numéro',
                  style: theme.textTheme.labelLarge?.copyWith(
                    color: KioskColors.muted,
                    letterSpacing: 2,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  formatKioskTicketNumber(widget.ticket.ticketNumber),
                  style: TextStyle(
                    fontFamily: theme.textTheme.displayLarge?.fontFamily,
                    fontSize: KioskDimensions.ticketNumberFontSize,
                    fontWeight: FontWeight.bold,
                    color: KioskColors.accent,
                    height: 1,
                  ),
                ),
                const SizedBox(height: KioskDimensions.screenPadding),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    _Stat(value: formatKioskTime(widget.ticket.createdAt), label: 'Heure'),
                    const SizedBox(width: 12),
                    _Stat(
                      value: '~${widget.ticket.estimatedWaitMinutes} min',
                      label: 'Attente',
                    ),
                  ],
                ),
                const SizedBox(height: KioskDimensions.screenPadding),
                Text(
                  "Votre ticket s'imprime, patientez un instant.",
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium?.copyWith(color: KioskColors.muted),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      constraints: const BoxConstraints(minWidth: 108),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
      decoration: BoxDecoration(
        color: KioskColors.nude,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(
            value,
            style: theme.textTheme.titleLarge?.copyWith(
              fontFamily: theme.textTheme.bodyLarge?.fontFamily,
              fontWeight: FontWeight.w700,
              color: KioskColors.ink,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label.toUpperCase(),
            style: theme.textTheme.labelSmall?.copyWith(
              color: KioskColors.muted,
              letterSpacing: 1,
            ),
          ),
        ],
      ),
    );
  }
}
