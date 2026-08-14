// Tests unitaires — formatTerminalTicketNumber, formatTerminalIssuedAt (US-8.5, #159).
//
// Couverture : formatage du numéro de passage (zéro-padding à 3 chiffres) et
// formatage de la date/heure (JJ/MM/AAAA HH:MM). Aucune dépendance Flutter.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/ticket_preview.dart';

void main() {
  group('formatTerminalTicketNumber', () {
    test('1 → N° 001', () {
      expect(formatTerminalTicketNumber(1), 'N° 001');
    });

    test('14 → N° 014', () {
      expect(formatTerminalTicketNumber(14), 'N° 014');
    });

    test('100 → N° 100 (pas de padding)', () {
      expect(formatTerminalTicketNumber(100), 'N° 100');
    });

    test('0 → N° 000', () {
      expect(formatTerminalTicketNumber(0), 'N° 000');
    });

    test('nombre > 999 → pas de troncature', () {
      expect(formatTerminalTicketNumber(1234), 'N° 1234');
    });
  });

  group('formatTerminalIssuedAt', () {
    test('date et heure formatées JJ/MM/AAAA HH:MM', () {
      final dt = DateTime(2024, 7, 5, 9, 3);
      expect(formatTerminalIssuedAt(dt), '05/07/2024 09:03');
    });

    test('minuit → 00:00', () {
      final dt = DateTime(2024, 1, 1, 0, 0);
      expect(formatTerminalIssuedAt(dt), '01/01/2024 00:00');
    });

    test('fin de journée → 23:59', () {
      final dt = DateTime(2024, 12, 31, 23, 59);
      expect(formatTerminalIssuedAt(dt), '31/12/2024 23:59');
    });

    test('mois et jour en un chiffre sont complétés à deux chiffres', () {
      final dt = DateTime(2025, 3, 9, 8, 5);
      expect(formatTerminalIssuedAt(dt), '09/03/2025 08:05');
    });
  });
}
