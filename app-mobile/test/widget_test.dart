// Test trivial du squelette mobile : l'écran d'accueil neutre s'affiche.
//
// Sert de point d'ancrage vert au test gate `flutter test` (cf. ADR-0001 / #6).

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/main.dart';

void main() {
  testWidgets('L\'écran d\'accueil affiche le nom CoifLink',
      (WidgetTester tester) async {
    await tester.pumpWidget(const CoifLinkApp());

    expect(find.text('CoifLink'), findsWidgets);
  });
}
