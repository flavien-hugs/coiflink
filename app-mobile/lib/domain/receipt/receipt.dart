// Entité de domaine « reçu de paiement » côté client (US-5.5, #38 · ADR-0040).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète la projection renvoyée par `GET /me/receipts` / `GET /me/receipts/{id}`
// (lecture d'appartenance, `PAYMENT_READ_OWN`) : montant, mode, statut,
// référence, horodatage, identité **publique** du salon et prestations réglées.
// Ne porte **jamais** de donnée de gestion (`recorded_by`) ni l'identité d'un
// autre client (§11.3) — le reçu client ne connaît d'ailleurs pas sa propre
// identité ici, contrairement au reçu imprimable côté gérant.

/// Ligne de prestation d'un reçu : libellé + montant figé.
class ReceiptLine {
  const ReceiptLine({required this.serviceName, required this.amount});

  /// Libellé de la prestation.
  final String serviceName;

  /// Montant figé (chaîne décimale, p. ex. « 3000.00 »). Conservé en chaîne
  /// pour ne pas introduire d'imprécision flottante.
  final String amount;
}

/// Reçu numérique d'un paiement, tel que renvoyé au client authentifié.
class Receipt {
  const Receipt({
    required this.receiptNumber,
    required this.paymentId,
    required this.salonName,
    required this.amount,
    required this.currency,
    required this.paymentMethod,
    required this.status,
    required this.paidAt,
    this.reference,
    this.lines = const <ReceiptLine>[],
  });

  /// Numéro de reçu présentable (p. ex. « REC-000042 »).
  final String receiptNumber;

  /// Identifiant opaque du paiement (UUID côté backend).
  final String paymentId;

  /// Identité **publique** du salon (déjà exposée sans authentification par le
  /// catalogue, #18/#19) — jamais de donnée de gestion.
  final String salonName;

  /// Montant payé (chaîne décimale, p. ex. « 5000.00 »).
  final String amount;

  final String currency;
  final String paymentMethod;
  final String status;
  final String? reference;

  /// Horodatage du paiement (serveur).
  final DateTime paidAt;

  /// Prestations réglées — peut être vide.
  final List<ReceiptLine> lines;
}
