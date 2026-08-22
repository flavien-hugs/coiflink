// Composition root de l'application CoifLink Borne (US-8.5, #159).
//
// Seul mode de ce paquet (voir README.md) : aucune session personnelle n'existe
// dans ce graphe d'imports — physiquement ni `AuthSession`, ni `SignIn`, ni écran
// « Mes … » ne sont importables depuis ici.
//
// Amorçage : voir `TerminalBootstrap` (`terminal_bootstrap.dart`), qui porte toute la
// logique de démarrage (activation par code, authentification device silencieuse,
// réessai) dans un widget public et directement testable.
//
// `TerminalInactivityGuard` est posé **une seule fois** via `builder:`, au-dessus du
// `Navigator` : tout écran poussé ensuite hérite du minuteur d'inactivité (§E).

import 'package:flutter/material.dart';

import '../../../application/terminal_device_session.dart';
import '../../../application/ports/printer_device_scan_gateway.dart';
import '../../../application/ports/terminal_activation_gateway.dart';
import '../../../application/ports/terminal_auth_gateway.dart';
import '../../../application/ports/terminal_credential_store.dart';
import '../../../application/ports/terminal_identity_gateway.dart';
import '../../../application/ports/terminal_queue_gateway.dart';
import '../../../application/ports/ticket_printer_device_store.dart';
import '../../../application/ports/ticket_printer_gateway.dart';
import '../../../application/use_cases/get_salon_detail.dart';
import '../../data/api_config.dart';
import '../../data/esc_pos_ticket_printer_gateway.dart';
import '../../data/flutter_thermal_printer_scan_gateway.dart';
import '../../data/http_terminal_activation_gateway.dart';
import '../../data/http_terminal_auth_gateway.dart';
import '../../data/http_terminal_identity_gateway.dart';
import '../../data/http_terminal_queue_gateway.dart';
import '../../data/http_salon_catalog_gateway.dart';
import '../../data/secure_terminal_credential_store.dart';
import '../../data/secure_ticket_printer_device_store.dart';
import 'terminal_bootstrap.dart';
import 'terminal_deps.dart';
import 'terminal_inactivity_guard.dart';
import 'terminal_theme.dart';

class TerminalApp extends StatefulWidget {
  const TerminalApp({
    super.key,
    this.credentialStore,
    this.authGateway,
    this.activationGateway,
    this.identityGateway,
    this.queueGateway,
    this.printerGateway,
    this.printerScanGateway,
    this.printerDeviceStore,
    this.getSalonDetail,
    this.apiConfig,
  });

  // Tous les ports sont **injectables** (tests/dev) ; en production, ils sont
  // construits à partir d'`ApiConfig.fromEnvironment()`.
  final TerminalCredentialStore? credentialStore;
  final TerminalAuthGateway? authGateway;
  final TerminalActivationGateway? activationGateway;
  final TerminalIdentityGateway? identityGateway;
  final TerminalQueueGateway? queueGateway;
  final TicketPrinterGateway? printerGateway;
  final PrinterDeviceScanGateway? printerScanGateway;
  final TicketPrinterDeviceStore? printerDeviceStore;
  final GetSalonDetail? getSalonDetail;
  final ApiConfig? apiConfig;

  @override
  State<TerminalApp> createState() => _TerminalAppState();
}

class _TerminalAppState extends State<TerminalApp> {
  // Un `GlobalKey<NavigatorState>` dédié : `TerminalInactivityGuard` s'en sert pour
  // revenir à l'accueil depuis n'importe quelle profondeur (§E).
  final GlobalKey<NavigatorState> _navigatorKey =
      GlobalKey<NavigatorState>(debugLabel: 'terminal');

  late final ApiConfig _apiConfig;
  late final TerminalCredentialStore _credentialStore;
  late final TerminalActivationGateway _activationGateway;
  late final TerminalDeviceSession _session;
  late final GetSalonDetail _getSalonDetail;
  late final TerminalIdentityGateway _identityGateway;
  late final TerminalQueueGateway _queueGateway;
  late final TicketPrinterDeviceStore _printerDeviceStore;
  late final TicketPrinterGateway _printerGateway;
  late final PrinterDeviceScanGateway _printerScanGateway;

  @override
  void initState() {
    super.initState();
    _apiConfig = widget.apiConfig ?? ApiConfig.fromEnvironment();
    _credentialStore = widget.credentialStore ?? SecureTerminalCredentialStore();
    _activationGateway =
        widget.activationGateway ?? HttpTerminalActivationGateway(config: _apiConfig);
    final authGateway =
        widget.authGateway ?? HttpTerminalAuthGateway(config: _apiConfig);
    _session = TerminalDeviceSession(authGateway);

    final catalogGateway = HttpSalonCatalogGateway(config: _apiConfig);
    _getSalonDetail = widget.getSalonDetail ?? GetSalonDetail(catalogGateway);
    _identityGateway = widget.identityGateway ??
        HttpTerminalIdentityGateway(config: _apiConfig, session: _session);
    _queueGateway = widget.queueGateway ??
        HttpTerminalQueueGateway(config: _apiConfig, session: _session);
    _printerDeviceStore =
        widget.printerDeviceStore ?? SecureTicketPrinterDeviceStore();
    _printerGateway = widget.printerGateway ??
        EscPosTicketPrinterGateway(deviceStore: _printerDeviceStore);
    _printerScanGateway =
        widget.printerScanGateway ?? FlutterThermalPrinterScanGateway();
  }

  TerminalDeps _buildDeps() => TerminalDeps(
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
      theme: buildTerminalTheme(),
      navigatorKey: _navigatorKey,
      builder: (context, child) => TerminalInactivityGuard(
        navigatorKey: _navigatorKey,
        child: child!,
      ),
      home: TerminalBootstrap(
        session: _session,
        credentialStore: _credentialStore,
        activationGateway: _activationGateway,
        printerScanGateway: _printerScanGateway,
        printerDeviceStore: _printerDeviceStore,
        buildDeps: _buildDeps,
      ),
    );
  }
}
