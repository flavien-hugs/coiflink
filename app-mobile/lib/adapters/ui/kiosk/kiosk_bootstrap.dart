// Amorçage de la session device de la borne (US-8.5, #159 · consomme #155).
//
// Extrait de `KioskApp` dans son propre fichier (widget **public**, testable
// directement) : `KioskApp.initState` porte une assertion de démarrage
// (`assert(KioskConfig.isKioskMode)`) qui échoue systématiquement sous
// `flutter test` (le dart-define `APP_MODE=kiosk` n'y est pas défini) — la couvrir
// exigerait de compiler chaque exécution des tests avec ce dart-define, ce que la
// CI ne fait pas. `KioskBootstrap` porte toute la logique métier de l'amorçage sans
// cette assertion, donc sans cette contrainte.
//
//   1. override de développement local `--dart-define=KIOSK_SALON_ID` → session amorcée
//      sans authentification (catalogue public seul), écran d'accueil directement ;
//   2. sinon, lecture du credential device stocké (`KioskCredentialStore`) :
//        - **absent** (borne jamais activée) → `KioskActivationScreen` (code à 6
//          chiffres, une seule fois) ;
//        - **présent** → authentification **silencieuse**
//          (`KioskDeviceSession.authenticate`, `POST /auth/kiosk/login`, #155) :
//            - credential refusé (`401`) → **effacé** + retour à l'activation (rien
//              d'autre à faire depuis l'écran : la borne doit être réactivée) ;
//            - échec réseau/serveur → `KioskUnavailableScreen` + réessai (le
//              credential stocké reste, il est peut-être valide, c'est le serveur
//              qui est momentanément indisponible) ;
//            - succès → `KioskHomeScreen` (le `salon_id` de la borne provient de la
//              réponse du login, un APK unique pour toutes les bornes).

import 'dart:async';

import 'package:flutter/material.dart';

import '../../../application/kiosk_device_session.dart';
import '../../../application/ports/kiosk_activation_gateway.dart';
import '../../../application/ports/kiosk_auth_gateway.dart';
import '../../../application/ports/kiosk_credential_store.dart';
import '../../data/kiosk_config.dart';
import 'kiosk_activation_screen.dart';
import 'kiosk_deps.dart';
import 'kiosk_home_screen.dart';
import 'kiosk_unavailable_screen.dart';

enum _BootState { loading, activation, unavailable, ready }

/// Amorce la session device puis affiche l'écran adapté (activation,
/// indisponibilité, ou accueil).
class KioskBootstrap extends StatefulWidget {
  const KioskBootstrap({
    super.key,
    required this.session,
    required this.credentialStore,
    required this.activationGateway,
    required this.buildDeps,
  });

  final KioskDeviceSession session;
  final KioskCredentialStore credentialStore;
  final KioskActivationGateway activationGateway;
  final KioskDeps Function() buildDeps;

  @override
  State<KioskBootstrap> createState() => _KioskBootstrapState();
}

class _KioskBootstrapState extends State<KioskBootstrap> {
  _BootState _state = _BootState.loading;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    // Override de développement local : pas d'authentification, salon figé en dur.
    final devSalonId = KioskConfig.devSalonId;
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

  Future<void> _authenticate(KioskCredential credential) async {
    if (!mounted) return;
    setState(() => _state = _BootState.loading);
    try {
      await widget.session.authenticate(credential);
      if (!mounted) return;
      setState(() => _state = _BootState.ready);
    } on KioskInvalidCredentialException {
      // Credential refusé (révoqué/faux) : rien de réparable depuis l'écran — la
      // borne doit être réactivée avec un nouveau code.
      await widget.credentialStore.clear();
      if (!mounted) return;
      setState(() => _state = _BootState.activation);
    } on KioskAuthException {
      // Réseau/serveur momentanément indisponible : le credential reste, réessai
      // possible sans repasser par l'activation.
      if (!mounted) return;
      setState(() => _state = _BootState.unavailable);
    }
  }

  void _onActivated(KioskCredential credential) {
    unawaited(_authenticate(credential));
  }

  @override
  Widget build(BuildContext context) {
    switch (_state) {
      case _BootState.loading:
        return const Scaffold(
          body: Center(child: CircularProgressIndicator()),
        );
      case _BootState.activation:
        return KioskActivationScreen(
          activationGateway: widget.activationGateway,
          credentialStore: widget.credentialStore,
          onActivated: _onActivated,
        );
      case _BootState.unavailable:
        return KioskUnavailableScreen(onRetry: _bootstrap);
      case _BootState.ready:
        return KioskHomeScreen(deps: widget.buildDeps());
    }
  }
}
