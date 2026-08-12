// Dépendances du parcours kiosque, transportées d'un écran à l'autre (US-8.5, #159).
//
// Petit objet de composition (assemblé une seule fois par `KioskApp`) passé de
// l'accueil jusqu'à la confirmation, pour éviter de re-déclarer cinq paramètres sur
// chaque constructeur d'écran. **Aucune** dépendance de session personnelle n'y
// figure (ni `AuthSession`, ni `SignIn`, ni écran « Mes … ») — c'est structurellement
// impossible d'en injecter une par ce canal (garantie §I de la spec).

import '../../../application/ports/kiosk_identity_gateway.dart';
import '../../../application/ports/kiosk_queue_gateway.dart';
import '../../../application/ports/ticket_printer_gateway.dart';
import '../../../application/use_cases/get_salon_detail.dart';

class KioskDeps {
  const KioskDeps({
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
  final KioskIdentityGateway identityGateway;

  /// Création du ticket de passage (#157).
  final KioskQueueGateway queueGateway;

  /// Impression du ticket (#160) — no-op tant que l'adaptateur ESC/POS n'est pas livré.
  final TicketPrinterGateway printerGateway;
}
