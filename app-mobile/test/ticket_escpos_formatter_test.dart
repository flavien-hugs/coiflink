// Tests unitaires — TicketEscPosFormatter (#160).
//
// Couverture : octets non vides, présence des séquences de commande attendues
// (découpe papier), présence du texte en clair (salon, numéro, prestations,
// accents français) dans les octets générés — `esc_pos_utils_plus` encode le texte
// en Latin-1/CP1252, donc les caractères accentués restent des octets directs
// comparables à `latin1.encode`.
//
// `TestWidgetsFlutterBinding.ensureInitialized()` est nécessaire : le générateur
// charge son profil de capacités via `rootBundle` (asset embarqué du package),
// même si `format` ne fait par ailleurs aucune E/S propre au paquet borne.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/data/ticket_escpos_formatter.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const formatter = TicketEscPosFormatter();

  TicketPrintPayload payload({
    String salonName = 'Salon Étoile',
    int ticketNumber = 14,
    List<String> serviceNames = const <String>['Coupe homme', 'Barbe'],
  }) =>
      TicketPrintPayload(
        salonName: salonName,
        ticketNumber: ticketNumber,
        issuedAt: DateTime(2024, 7, 1, 9, 5),
        serviceNames: serviceNames,
      );

  bool containsLatin1(List<int> bytes, String text) {
    final needle = latin1.encode(text);
    for (var i = 0; i <= bytes.length - needle.length; i++) {
      var match = true;
      for (var j = 0; j < needle.length; j++) {
        if (bytes[i + j] != needle[j]) {
          match = false;
          break;
        }
      }
      if (match) return true;
    }
    return false;
  }

  group('TicketEscPosFormatter', () {
    test('produit des octets non vides', () async {
      final bytes = await formatter.format(payload());
      expect(bytes, isNotEmpty);
    });

    test('inclut le nom du salon en majuscules', () async {
      final bytes = await formatter.format(payload(salonName: 'Salon Étoile'));
      expect(containsLatin1(bytes, 'SALON ÉTOILE'), isTrue);
    });

    test('inclut le numéro de ticket formaté (N° 014)', () async {
      final bytes = await formatter.format(payload(ticketNumber: 14));
      expect(containsLatin1(bytes, 'N° 014'), isTrue);
    });

    test('inclut chaque prestation', () async {
      final bytes = await formatter.format(
        payload(serviceNames: const <String>['Coupe homme', 'Barbe']),
      );
      expect(containsLatin1(bytes, 'Coupe homme'), isTrue);
      expect(containsLatin1(bytes, 'Barbe'), isTrue);
    });

    test('gère les accents français dans les noms de prestations', () async {
      final bytes = await formatter.format(
        payload(serviceNames: const <String>['Défrisage', 'Crème coiffante']),
      );
      expect(containsLatin1(bytes, 'Défrisage'), isTrue);
      expect(containsLatin1(bytes, 'Crème coiffante'), isTrue);
    });

    test('termine par la commande de découpe papier (GS V 0 — coupe totale)', () async {
      final bytes = await formatter.format(payload());
      // `Generator.cut()` (mode par défaut `PosCutMode.full`) ajoute `GS V 0` :
      // 0x1D ('\x1D'), 0x56 ('V'), 0x30 ('0').
      final cutBytes = <int>[0x1D, 0x56, 0x30];
      final tail = bytes.sublist((bytes.length - cutBytes.length).clamp(0, bytes.length));
      expect(tail, cutBytes);
    });
  });
}
