// Impression du ticket de passage (US-007, #159 · consomme #160).
//
// Écran terminal du parcours walk-in : affiche l'aperçu imprimable (`TicketPreview`),
// rendu **indépendamment** du résultat de l'impression, et déclenche la séquence
// d'impression, encadrée par le minuteur d'inactivité (§E) :
//   1. `pauseForPrinting()` juste avant l'appel matériel ;
//   2. `print(payload)` dans un `try/catch` sur les trois exceptions typées de #160
//      (`PrinterNotConnected`/`OutOfPaper`/`WriteFailed`), chacune affichant son
//      message **neutre** ;
//   3. `resumeAfterPrinting()` dans un `finally` (succès **ou** échec).
// **Aucun échec d'impression** ne raccourcit ni ne bloque le retour automatique : le
// numéro reste visible (aperçu à l'écran) quel que soit le résultat, et « Terminer »
// reste utilisable pendant l'impression (le matériel n'a pas à répondre pour que le
// client parte).

import 'package:flutter/material.dart';

import '../../../application/ports/terminal_queue_gateway.dart';
import '../../../application/ports/ticket_printer_gateway.dart';
import '../../../domain/ticket/ticket_print_payload.dart';
import 'terminal_deps.dart';
import 'terminal_inactivity_guard.dart';
import 'terminal_theme.dart';
import 'ticket_preview.dart';

class TerminalPrintScreen extends StatefulWidget {
  const TerminalPrintScreen({
    super.key,
    required this.deps,
    required this.ticket,
    required this.salonName,
    required this.serviceNames,
    this.controllerOverride,
  });

  final TerminalDeps deps;

  /// Ticket de passage émis par #157 (numéro brut + ETA figés à l'émission).
  final QueueTicket ticket;

  /// Nom de vitrine du salon (en-tête du ticket, pas de PII).
  final String salonName;

  /// Prestations choisies (une ligne imprimée par prestation).
  final List<String> serviceNames;

  /// Contrôleur d'inactivité **injecté** (tests) ; en production, résolu via le
  /// `TerminalInactivityGuard` hérité (`maybeOf`).
  final TerminalInactivityController? controllerOverride;

  @override
  State<TerminalPrintScreen> createState() => _TerminalPrintScreenState();
}

class _TerminalPrintScreenState extends State<TerminalPrintScreen> {
  TerminalInactivityController? _controller;
  bool _printStarted = false;
  bool _printing = false;
  String? _printError;

  TicketPrintPayload get _payload => TicketPrintPayload(
        salonName: widget.salonName,
        ticketNumber: widget.ticket.ticketNumber,
        issuedAt: widget.ticket.createdAt,
        serviceNames: widget.serviceNames,
      );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Résolu ici (et non en `initState`) : `dependOnInheritedWidgetOfExactType`
    // n'est pas disponible avant que les dépendances soient prêtes.
    _controller =
        widget.controllerOverride ?? TerminalInactivityGuard.maybeOf(context);
    if (!_printStarted) {
      _printStarted = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _runPrintSequence();
      });
    }
  }

  Future<void> _runPrintSequence() async {
    final controller = _controller;
    setState(() {
      _printing = true;
      _printError = null;
    });
    // Suspend le minuteur pendant l'impression, avec un plafond de secours (§E) :
    // même si `resumeAfterPrinting()` n'était jamais atteint, le retour à l'accueil
    // resterait garanti par le plafond de 15 s du guard.
    controller?.pauseForPrinting();
    try {
      await widget.deps.printerGateway.print(_payload);
    } on TicketPrinterException catch (exc) {
      // Message **neutre** propre à chaque cause (#160) — jamais le détail brut
      // du plugin. Le numéro reste affiché : l'échec n'interrompt pas le parcours.
      if (mounted) setState(() => _printError = exc.message);
    } catch (_) {
      if (mounted) {
        setState(() => _printError = "Échec de l'impression.");
      }
    } finally {
      // Reprise **systématique** (succès comme échec) — jamais conditionnée à une
      // impression réussie.
      controller?.resumeAfterPrinting();
      if (mounted) setState(() => _printing = false);
    }
  }

  void _finish() {
    // Retour immédiat à l'accueil (sans attendre les 60 s) — le minuteur reste le
    // filet de sécurité pour un client qui s'éloigne sans appuyer.
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(TerminalDimensions.screenPadding),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                TicketPreview(payload: _payload),
                const SizedBox(height: TerminalDimensions.screenPadding),
                if (_printing)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      const SizedBox(width: 12),
                      Text(
                        'Impression en cours…',
                        style: theme.textTheme.bodyMedium
                            ?.copyWith(color: TerminalColors.muted),
                      ),
                    ],
                  ),
                if (_printError != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(
                      // L'échec n'empêche jamais de retenir/afficher le numéro (#160).
                      '$_printError Votre numéro reste valable.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: theme.colorScheme.error),
                    ),
                  ),
                const SizedBox(height: TerminalDimensions.touchSpacing),
                Text(
                  'Récupérez votre ticket au bac d\'impression.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium?.copyWith(color: TerminalColors.muted),
                ),
                const SizedBox(height: TerminalDimensions.screenPadding),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _finish,
                    child: const Text('Terminer'),
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
