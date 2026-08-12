// Composition root de l'application CoifLink Borne (US-8.5, #159).
//
// Seul mode de ce paquet (voir README.md) : aucune session personnelle n'existe
// dans ce graphe d'imports — physiquement ni `AuthSession`, ni `SignIn`, ni écran
// « Mes … » ne sont importables depuis ici.
//
// Amorçage : voir `KioskBootstrap` (`kiosk_bootstrap.dart`), qui porte toute la
// logique de démarrage (activation par code, authentification device silencieuse,
// réessai) dans un widget public et directement testable.
//
// `KioskInactivityGuard` est posé **une seule fois** via `builder:`, au-dessus du
// `Navigator` : tout écran poussé ensuite hérite du minuteur d'inactivité (§E).

import 'package:flutter/material.dart';

import '../../../application/kiosk_device_session.dart';
import '../../../application/ports/kiosk_activation_gateway.dart';
import '../../../application/ports/kiosk_auth_gateway.dart';
import '../../../application/ports/kiosk_credential_store.dart';
import '../../../application/ports/kiosk_identity_gateway.dart';
import '../../../application/ports/kiosk_queue_gateway.dart';
import '../../../application/ports/ticket_printer_gateway.dart';
import '../../../application/use_cases/get_salon_detail.dart';
import '../../data/api_config.dart';
import '../../data/http_kiosk_activation_gateway.dart';
import '../../data/http_kiosk_auth_gateway.dart';
import '../../data/http_kiosk_identity_gateway.dart';
import '../../data/http_kiosk_queue_gateway.dart';
import '../../data/http_salon_catalog_gateway.dart';
import '../../data/noop_ticket_printer_gateway.dart';
import '../../data/secure_kiosk_credential_store.dart';
import 'kiosk_bootstrap.dart';
import 'kiosk_deps.dart';
import 'kiosk_inactivity_guard.dart';
import 'kiosk_theme.dart';

class KioskApp extends StatefulWidget {
  const KioskApp({
    super.key,
    this.credentialStore,
    this.authGateway,
    this.activationGateway,
    this.identityGateway,
    this.queueGateway,
    this.printerGateway,
    this.getSalonDetail,
    this.apiConfig,
  });

  // Tous les ports sont **injectables** (tests/dev) ; en production, ils sont
  // construits à partir d'`ApiConfig.fromEnvironment()`.
  final KioskCredentialStore? credentialStore;
  final KioskAuthGateway? authGateway;
  final KioskActivationGateway? activationGateway;
  final KioskIdentityGateway? identityGateway;
  final KioskQueueGateway? queueGateway;
  final TicketPrinterGateway? printerGateway;
  final GetSalonDetail? getSalonDetail;
  final ApiConfig? apiConfig;

  @override
  State<KioskApp> createState() => _KioskAppState();
}

class _KioskAppState extends State<KioskApp> {
  // Un `GlobalKey<NavigatorState>` dédié : `KioskInactivityGuard` s'en sert pour
  // revenir à l'accueil depuis n'importe quelle profondeur (§E).
  final GlobalKey<NavigatorState> _navigatorKey =
      GlobalKey<NavigatorState>(debugLabel: 'kiosk');

  late final ApiConfig _apiConfig;
  late final KioskCredentialStore _credentialStore;
  late final KioskActivationGateway _activationGateway;
  late final KioskDeviceSession _session;
  late final GetSalonDetail _getSalonDetail;
  late final KioskIdentityGateway _identityGateway;
  late final KioskQueueGateway _queueGateway;
  late final TicketPrinterGateway _printerGateway;

  @override
  void initState() {
    super.initState();
    _apiConfig = widget.apiConfig ?? ApiConfig.fromEnvironment();
    _credentialStore = widget.credentialStore ?? SecureKioskCredentialStore();
    _activationGateway =
        widget.activationGateway ?? HttpKioskActivationGateway(config: _apiConfig);
    final authGateway =
        widget.authGateway ?? HttpKioskAuthGateway(config: _apiConfig);
    _session = KioskDeviceSession(authGateway);

    final catalogGateway = HttpSalonCatalogGateway(config: _apiConfig);
    _getSalonDetail = widget.getSalonDetail ?? GetSalonDetail(catalogGateway);
    _identityGateway = widget.identityGateway ??
        HttpKioskIdentityGateway(config: _apiConfig, session: _session);
    _queueGateway = widget.queueGateway ??
        HttpKioskQueueGateway(config: _apiConfig, session: _session);
    _printerGateway = widget.printerGateway ?? const NoopTicketPrinterGateway();
  }

  KioskDeps _buildDeps() => KioskDeps(
        salonId: _session.salonId,
        getSalonDetail: _getSalonDetail,
        identityGateway: _identityGateway,
        queueGateway: _queueGateway,
        printerGateway: _printerGateway,
      );

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CoifLink — Borne',
      debugShowCheckedModeBanner: false,
      theme: buildKioskTheme(),
      navigatorKey: _navigatorKey,
      builder: (context, child) => KioskInactivityGuard(
        navigatorKey: _navigatorKey,
        child: child!,
      ),
      home: KioskBootstrap(
        session: _session,
        credentialStore: _credentialStore,
        activationGateway: _activationGateway,
        buildDeps: _buildDeps,
      ),
    );
  }
}
