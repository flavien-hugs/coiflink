// Port (interface) de persistance de l'imprimante sélectionnée — application, #160.
//
// Contrat interne au paquet, indépendant de Flutter et du stockage concret
// (ADR-0008) — même forme que `TerminalCredentialStore`
// (`terminal_credential_store.dart`, #159). L'identifiant persisté ici (propre au
// transport, ex. adresse MAC Bluetooth) est choisi **une seule fois**, au setup
// ponctuel (`TerminalPrinterSetupScreen`), puis relu par
// `EscPosTicketPrinterGateway.connect()` à chaque impression — aucune sélection
// n'a lieu au moment d'imprimer.
//
// `null` a deux significations distinctes selon l'appelant : pour
// `TerminalBootstrap`, c'est le signal que le setup n'a jamais été fait (écran à
// afficher) ; pour `EscPosTicketPrinterGateway`, c'est l'équivalent d'une
// imprimante non configurée ([PrinterNotConnectedException] côté port
// d'impression).

abstract class TicketPrinterDeviceStore {
  /// Lit l'identifiant de l'imprimante sélectionnée, ou `null` si le setup n'a
  /// jamais été fait (ou a été explicitement passé/effacé).
  Future<String?> read();

  /// Persiste l'identifiant de l'imprimante sélectionnée (écrase une éventuelle
  /// sélection précédente).
  Future<void> save(String deviceId);

  /// Efface la sélection (redemande le setup au prochain démarrage).
  Future<void> clear();
}
