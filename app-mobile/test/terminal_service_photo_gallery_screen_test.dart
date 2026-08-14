// Tests widget — TerminalServicePhotoGalleryScreen (#160).
//
// Couverture :
//   - le nom de la prestation s'affiche dans l'en-tête ;
//   - une seule photo → pas de compteur ni de points de pagination (rien à
//     naviguer) ;
//   - plusieurs photos → compteur « 1 / N » et points de pagination, mis à
//     jour au balayage ;
//   - fermeture via le bouton « Fermer » retire l'écran (pop) ;
//   - aucune photo (liste vide, cas défensif) → repli sur le placeholder sans
//     exception.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_service_photo_gallery_screen.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_service.dart';

Widget _buildScreen(SalonService service) {
  return MaterialApp(
    home: TerminalServicePhotoGalleryScreen(service: service),
  );
}

void main() {
  group('TerminalServicePhotoGalleryScreen — en-tête', () {
    testWidgets('affiche le nom de la prestation', (tester) async {
      await tester.pumpWidget(_buildScreen(
        const SalonService(
          id: 'a',
          name: 'Tresses africaines',
          photos: [SalonPhoto(id: 'p1', url: 'https://x/1.png')],
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Tresses africaines'), findsOneWidget);
    });
  });

  group('TerminalServicePhotoGalleryScreen — une seule photo', () {
    testWidgets('aucun compteur ni point de pagination', (tester) async {
      await tester.pumpWidget(_buildScreen(
        const SalonService(
          id: 'a',
          name: 'Coloration',
          photos: [SalonPhoto(id: 'p1', url: 'https://x/1.png')],
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.textContaining('/'), findsNothing);
    });
  });

  group('TerminalServicePhotoGalleryScreen — plusieurs photos', () {
    testWidgets('affiche le compteur 1 / N', (tester) async {
      await tester.pumpWidget(_buildScreen(
        const SalonService(
          id: 'a',
          name: 'Tresses',
          photos: [
            SalonPhoto(id: 'p1', url: 'https://x/1.png'),
            SalonPhoto(id: 'p2', url: 'https://x/2.png'),
            SalonPhoto(id: 'p3', url: 'https://x/3.png'),
          ],
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('1 / 3'), findsOneWidget);
    });

    testWidgets('balayer met à jour le compteur', (tester) async {
      await tester.pumpWidget(_buildScreen(
        const SalonService(
          id: 'a',
          name: 'Tresses',
          photos: [
            SalonPhoto(id: 'p1', url: 'https://x/1.png'),
            SalonPhoto(id: 'p2', url: 'https://x/2.png'),
          ],
        ),
      ));
      await tester.pumpAndSettle();

      await tester.drag(find.byType(PageView), const Offset(-400, 0));
      await tester.pumpAndSettle();

      expect(find.text('2 / 2'), findsOneWidget);
      expect(find.text('1 / 2'), findsNothing);
    });
  });

  group('TerminalServicePhotoGalleryScreen — fermeture', () {
    testWidgets('le bouton Fermer retire l\'écran', (tester) async {
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(MaterialApp(
        navigatorKey: navKey,
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: FilledButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => const TerminalServicePhotoGalleryScreen(
                      service: SalonService(
                        id: 'a',
                        name: 'Coupe homme',
                        photos: [SalonPhoto(id: 'p1', url: 'https://x/1.png')],
                      ),
                    ),
                  ),
                ),
                child: const Text('Ouvrir'),
              ),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('Ouvrir'));
      await tester.pumpAndSettle();
      expect(find.byType(TerminalServicePhotoGalleryScreen), findsOneWidget);

      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalServicePhotoGalleryScreen), findsNothing);
    });
  });

  group('TerminalServicePhotoGalleryScreen — cas défensif', () {
    testWidgets('galerie vide affiche le repli sans exception', (tester) async {
      await tester.pumpWidget(_buildScreen(
        const SalonService(id: 'a', name: 'Brushing'),
      ));
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(find.byIcon(Icons.content_cut), findsOneWidget);
    });
  });
}
