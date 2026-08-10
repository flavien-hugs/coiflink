// Formatage du texte partagé d'un reçu (US-5.5, #38 · ADR-0040).
//
// Fonction **pure**, testable sans harnais widget (même patron que
// `booking_labels.dart`) : compose un texte simple (salon, numéro, date,
// prestations, total) pour le partage natif (`share_plus`). Aucune donnée de
// gestion, aucun jeton.

import '../../../domain/receipt/receipt.dart';
import '../booking/booking_labels.dart';

String formatReceiptShareText(Receipt receipt) {
  final buffer = StringBuffer()
    ..writeln(receipt.salonName)
    ..writeln(receipt.receiptNumber)
    ..writeln(formatFullDate(receipt.paidAt))
    ..writeln();

  for (final line in receipt.lines) {
    buffer.writeln('${line.serviceName} — ${line.amount} FCFA');
  }
  if (receipt.lines.isNotEmpty) buffer.writeln();

  buffer.writeln('Total : ${receipt.amount} FCFA');
  if (receipt.reference != null && receipt.reference!.trim().isNotEmpty) {
    buffer.writeln('Référence : ${receipt.reference}');
  }

  return buffer.toString().trim();
}
