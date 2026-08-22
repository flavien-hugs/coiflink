// Amorçage de la session device de la borne (US-8.5, #159 · consomme #155).
//
// Extrait de `TerminalApp` dans son propre fichier (widget **public**, testable
// directement) : `TerminalApp.initState` porte une assertion de démarrage
// (`assert(TerminalConfig.isTerminalMode)`) qui échoue systématiquement sous
// `flutter test` (le dart-define `APP_MODE=terminal` n'y est pas défini) — la couvrir
// exigerait de compiler chaque exécution des tests avec ce dart-define, ce que la
// CI ne fait pas. `TerminalBootstrap` porte toute la logique métier de l'amorçage sans
// cette assertion, donc sans cette contrainte.
//
//   1. override de développement local `--dart-define=TERMINAL_SALON_ID` → session amorcée
//      sans authentification (catalogue public seul), écran d'accueil directement ;
//   2. sinon, lecture du credential device stocké (`TerminalCredentialStore`) :
//        - **absent** (borne jamais activée) → `TerminalActivationScreen` (code à 6
//          chiffres, une seule fois) ;
//        - **présent** → authentification **silencieuse**
//          (`TerminalDeviceSession.authenticate`, `POST /auth/terminal/login`, #155) :
//            - credential refusé (`401`) → **effacé** + retour à l'activation (rien
//              d'autre à faire depuis l'écran : la borne doit être réactivée) ;
//            - échec réseau/serveur → `TerminalUnavailableScreen` + réessai (le
//              credential stocké reste, il est peut-être valide, c'est le serveur
//              qui est momentanément indisponible) ;
//            - succès, imprimante **déjà** configurée (`TicketPrinterDeviceStore`,
//              #160) → `TerminalHomeScreen` directement ;
//            - succès, imprimante **jamais** configurée → `TerminalPrinterSetupScreen`
//              (setup ponctuel, #160) une seule fois, avant l'accueil — non bloquant
//              (« Configurer plus tard » mène aussi à l'accueil) ; le `salon_id` de
//              la borne provient de la réponse du login, un APK unique pour toutes
//              les bornes.

import 'dart:async';

import 'package:flutter/material.dart';

import '../../../application/terminal_device_session.dart';
import '../../../application/ports/printer_device_scan_gateway.dart';
import '../../../application/ports/terminal_activation_gateway.dart';
import '../../../application/ports/terminal_auth_gateway.dart';
import '../../../application/ports/terminal_credential_store.dart';
import '../../../application/ports/ticket_printer_device_store.dart';
import '../../data/terminal_config.dart';
import 'terminal_activation_screen.dart';
import 'terminal_deps.dart';
import 'terminal_home_screen.dart';
import 'terminal_printer_setup_screen.dart';
import 'terminal_unavailable_screen.dart';

enum _BootState { loading, activation, unavailable, printerSetup, ready }

/// Amorce la session device puis affiche l'écran adapté (activation,
/// indisponibilité, ou accueil).
class TerminalBootstrap extends StatefulWidget {
  const TerminalBootstrap({
    super.key,
    required this.session,
    required this.credentialStore,
    required this.activationGateway,
    required this.printerScanGateway,
    required this.printerDeviceStore,
    required this.buildDeps,
  });

  final TerminalDeviceSession session;
  final TerminalCredentialStore credentialStore;
  final TerminalActivationGateway activationGateway;

  /// Recherche des imprimantes disponibles pour `TerminalPrinterSetupScreen` (#160).
  final PrinterDeviceScanGateway printerScanGateway;

  /// Sélection persistée de l'imprimante (#160) : `null` déclenche le setup
  /// ponctuel une seule fois, avant le premier accès à l'accueil.
  final TicketPrinterDeviceStore printerDeviceStore;

  final TerminalDeps Function() buildDeps;

  @override
  State<TerminalBootstrap> createState() => _TerminalBootstrapState();
}

class _TerminalBootstrapState extends State<TerminalBootstrap> {
  _BootState _state = _BootState.loading;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    // Override de développement local : pas d'authentification, salon figé en dur.
    final devSalonId = TerminalConfig.devSalonId;
    if (devSalonId != null) {
      widget.session.seedDevSalon(devSalonId);
      if (!mounted) return;
      setState(() => _state = _BootState.ready);
      return;
    }

    setState(() => _state = _BootState.loading);
    final credential = await widget.credentialStore.read();
    if (credential == null) {
      if (!mounted) return;
      setState(() => _state = _BootState.activation);
      return;
    }
    await _authenticate(credential);
  }

  Future<void> _authenticate(TerminalCredential credential) async {
    if (!mounted) return;
    setState(() => _state = _BootState.loading);
    try {
      await widget.session.authenticate(credential);
      if (!mounted) return;
      final printerDeviceId = await widget.printerDeviceStore.read();
      if (!mounted) return;
      setState(
        () => _state =
            printerDeviceId == null ? _BootState.printerSetup : _BootState.ready,
      );
    } on TerminalInvalidCredentialException {
      // Credential refusé (révoqué/faux) : rien de réparable depuis l'écran — la
      // borne doit être réactivée avec un nouveau code.
      await widget.credentialStore.clear();
      if (!mounted) return;
      setState(() => _state = _BootState.activation);
    } on TerminalAuthException {
      // Réseau/serveur momentanément indisponible : le credential reste, réessai
      // possible sans repasser par l'activation.
      if (!mounted) return;
      setState(() => _state = _BootState.unavailable);
    }
  }

  void _onActivated(TerminalCredential credential) {
    unawaited(_authenticate(credential));
  }

  void _onPrinterSetupDone() {
    if (!mounted) return;
    setState(() => _state = _BootState.ready);
  }

  @override
  Widget build(BuildContext context) {
    switch (_state) {
      case _BootState.loading:
        return const Scaffold(
          body: Center(child: CircularProgressIndicator()),
        );
      case _BootState.activation:
        return TerminalActivationScreen(
          activationGateway: widget.activationGateway,
          credentialStore: widget.credentialStore,
          onActivated: _onActivated,
        );
      case _BootState.unavailable:
        return TerminalUnavailableScreen(onRetry: _bootstrap);
      case _BootState.printerSetup:
        return TerminalPrinterSetupScreen(
          scanGateway: widget.printerScanGateway,
          deviceStore: widget.printerDeviceStore,
          onDone: _onPrinterSetupDone,
        );
      case _BootState.ready:
        return TerminalHomeScreen(deps: widget.buildDeps());
    }
  }
}
