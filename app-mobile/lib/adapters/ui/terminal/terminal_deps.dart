// Dépendances du parcours terminal, transportées d'un écran à l'autre (US-8.5, #159).
//
// Petit objet de composition (assemblé une seule fois par `TerminalApp`) passé de
// l'accueil jusqu'à la confirmation, pour éviter de re-déclarer cinq paramètres sur
// chaque constructeur d'écran. **Aucune** dépendance de session personnelle n'y
// figure (ni `AuthSession`, ni `SignIn`, ni écran « Mes … ») — c'est structurellement
// impossible d'en injecter une par ce canal (garantie §I de la spec).

import '../../../application/ports/terminal_identity_gateway.dart';
import '../../../application/ports/terminal_queue_gateway.dart';
import '../../../application/ports/ticket_printer_gateway.dart';
import '../../../application/use_cases/get_salon_detail.dart';

class TerminalDeps {
  const TerminalDeps({
    required this.salonId,
    required this.getSalonDetail,
    required this.identityGateway,
    required this.queueGateway,
    required this.printerGateway,
  });

  /// `salon_id` figé de la borne (issu du login device, #155).
  final String salonId;

  /// Lecture du catalogue public du salon (nom, logo, prestations + photos #158).
  final GetSalonDetail getSalonDetail;

  /// Identité walk-in (#156) : recherche par téléphone + création de fiche.
  final TerminalIdentityGateway identityGateway;

  /// Création du ticket de passage (#157).
  final TerminalQueueGateway queueGateway;

  /// Impression du ticket (#160) — `EscPosTicketPrinterGateway` en production.
  final TicketPrinterGateway printerGateway;
}
