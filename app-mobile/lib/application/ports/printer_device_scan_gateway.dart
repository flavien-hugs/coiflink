// Port (interface) de recherche des imprimantes disponibles — application, #160.
//
// Contrat interne au paquet, indépendant de Flutter et du plugin de transport
// concret (ADR-0008), consommé uniquement par `TerminalPrinterSetupScreen` : un
// technicien recherche l'imprimante Bluetooth de la borne **une seule fois**, à
// l'installation (voir `TicketPrinterDeviceStore`). Distinct du port
// `TicketPrinterGateway` (qui imprime) : la recherche/sélection est une
// préoccupation de mise en service, pas du parcours client.

/// Appareil détecté lors de la recherche (nom + identifiant stable, propre au
/// transport — ex. adresse MAC Bluetooth).
class PrinterDeviceInfo {
  const PrinterDeviceInfo({required this.id, required this.name});

  final String id;
  final String name;
}

/// Port de recherche des imprimantes disponibles (setup ponctuel de la borne).
abstract class PrinterDeviceScanGateway {
  /// Recherche active des imprimantes à proximité (fenêtre de temps fixe côté
  /// implémentation) — ne suppose aucun appairage préalable côté OS.
  Future<List<PrinterDeviceInfo>> scan();
}
