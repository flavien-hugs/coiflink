// Setup ponctuel de l'imprimante ticket (#160).
//
// Écran affiché **une seule fois**, juste après la première activation de la
// borne (voir `terminal_bootstrap.dart` — état `printerSetup`, tant que
// `TicketPrinterDeviceStore.read()` est `null`) : recherche les imprimantes
// Bluetooth/USB à proximité (`PrinterDeviceScanGateway`), le technicien en
// sélectionne une (persistée via `TicketPrinterDeviceStore`), ou passe l'étape si
// le matériel n'est pas encore branché — non bloquant (décision n°9 de la spec,
// « toujours en direct »).
//
// Contrairement à `TerminalActivationScreen`, cet écran n'est **jamais** rejoué
// automatiquement une fois une imprimante choisie : `EscPosTicketPrinterGateway`
// relit ensuite l'identifiant persisté à chaque connexion, sans repasser par une
// sélection.

import 'package:flutter/material.dart';

import '../../../application/ports/printer_device_scan_gateway.dart';
import '../../../application/ports/ticket_printer_device_store.dart';
import 'terminal_theme.dart';

class TerminalPrinterSetupScreen extends StatefulWidget {
  const TerminalPrinterSetupScreen({
    super.key,
    required this.scanGateway,
    required this.deviceStore,
    required this.onDone,
  });

  final PrinterDeviceScanGateway scanGateway;
  final TicketPrinterDeviceStore deviceStore;

  /// Appelé une fois le setup terminé — sélection faite **ou** passée.
  final VoidCallback onDone;

  @override
  State<TerminalPrinterSetupScreen> createState() =>
      _TerminalPrinterSetupScreenState();
}

class _TerminalPrinterSetupScreenState extends State<TerminalPrinterSetupScreen> {
  bool _scanning = false;
  bool _scanned = false;
  bool _saving = false;
  List<PrinterDeviceInfo> _devices = const <PrinterDeviceInfo>[];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _scan());
  }

  Future<void> _scan() async {
    setState(() => _scanning = true);
    final devices = await widget.scanGateway.scan();
    if (!mounted) return;
    setState(() {
      _devices = devices;
      _scanning = false;
      _scanned = true;
    });
  }

  Future<void> _select(PrinterDeviceInfo device) async {
    setState(() => _saving = true);
    await widget.deviceStore.save(device.id);
    if (!mounted) return;
    widget.onDone();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(TerminalDimensions.screenPadding),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text(
                "Configuration de l'imprimante",
                textAlign: TextAlign.center,
                style: theme.textTheme.headlineSmall
                    ?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 6),
              Text(
                "Sélectionnez l'imprimante de tickets de cette borne. Cette "
                "étape ne s'affichera plus une fois configurée.",
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: TerminalColors.muted),
              ),
              const SizedBox(height: TerminalDimensions.screenPadding),
              Expanded(child: _body(theme)),
              const SizedBox(height: TerminalDimensions.touchSpacing),
              if (_scanning)
                const SizedBox.shrink()
              else
                OutlinedButton(
                  onPressed: _saving ? null : _scan,
                  child: const Text('Rechercher à nouveau'),
                ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: _saving ? null : widget.onDone,
                child: const Text('Configurer plus tard'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _body(ThemeData theme) {
    if (_scanning) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_scanned && _devices.isEmpty) {
      return Center(
        child: Text(
          'Aucune imprimante trouvée. Vérifiez que celle-ci est allumée et à '
          'proximité, puis réessayez.',
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium?.copyWith(color: TerminalColors.muted),
        ),
      );
    }
    return ListView.separated(
      itemCount: _devices.length,
      separatorBuilder: (_, _) => const SizedBox(height: 12),
      itemBuilder: (context, index) {
        final device = _devices[index];
        return Card(
          child: ListTile(
            title: Text(device.name),
            subtitle: Text(device.id),
            trailing: const Icon(Icons.chevron_right),
            onTap: _saving ? null : () => _select(device),
          ),
        );
      },
    );
  }
}
