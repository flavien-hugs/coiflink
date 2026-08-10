// Tests widget — ReceiptsScreen (US-5.5, #38 · ADR-0040).
//
// Couverture : titre AppBar ; indicateur de chargement ; affichage d'un reçu
// (salon, numéro, montant) ; liste multiple ; état vide ; état sans session
// (onRequireLogin appelé) ; UnauthorizedException (session effacée, « Session
// expirée ») ; erreur réseau (« Réessayer ») ; navigation liste → détail.
// Aucun appel HTTP réel ; aucun jeton de production dans les fixtures (§11).

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/receipts/receipt_detail_screen.dart';
import 'package:coiflink_mobile/adapters/ui/receipts/receipts_screen.dart';
import 'package:coiflink_mobile/application/auth_session.dart';
import 'package:coiflink_mobile/application/ports/receipt_gateway.dart';
import 'package:coiflink_mobile/application/ports/token_store.dart';
import 'package:coiflink_mobile/application/use_cases/get_receipt_detail.dart';
import 'package:coiflink_mobile/application/use_cases/list_my_receipts.dart';
import 'package:coiflink_mobile/domain/receipt/receipt.dart';

// ---------------------------------------------------------------------------
// Faux gateway
// ---------------------------------------------------------------------------

class _StubGateway implements ReceiptGateway {
  _StubGateway({
    this.result,
    this.error,
    this.future,
    this.detail,
  });

  final List<Receipt>? result;
  final Object? error;
  final Future<List<Receipt>>? future;
  final Receipt? detail;

  @override
  Future<List<Receipt>> myReceipts({required String accessToken}) async {
    if (future != null) return future!;
    if (error != null) throw error!;
    return result ?? const [];
  }

  @override
  Future<Receipt> receiptDetail({
    required String paymentId,
    required String accessToken,
  }) async {
    final d = detail;
    if (d == null) throw const ReceiptNotFoundException();
    return d;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

AuthSession _sessionWithToken(String token) {
  final store = InMemoryTokenStore();
  store.write(token); // corps synchrone avant tout await
  return AuthSession(store);
}

InMemoryTokenStore _emptyStore() => InMemoryTokenStore();

AuthSession _emptySession() => AuthSession(_emptyStore());

Receipt _receipt({
  String paymentId = 'payment-1',
  String salonName = 'Salon Élégance',
  String amount = '5000.00',
}) {
  return Receipt(
    receiptNumber: 'REC-000001',
    paymentId: paymentId,
    salonName: salonName,
    amount: amount,
    currency: 'XOF',
    paymentMethod: 'CASH',
    status: 'VALIDATED',
    paidAt: DateTime(2026, 7, 30, 10, 15),
  );
}

Widget _screen({
  required ReceiptGateway gateway,
  required AuthSession session,
  Future<bool> Function(BuildContext)? onRequireLogin,
}) {
  return MaterialApp(
    home: ReceiptsScreen(
      listMyReceipts: ListMyReceipts(gateway),
      getReceiptDetail: GetReceiptDetail(gateway),
      session: session,
      onRequireLogin: onRequireLogin ?? (_) async => false,
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('ReceiptsScreen', () {
    group('titre', () {
      testWidgets('AppBar affiche "Mes reçus"', (tester) async {
        final gateway = _StubGateway(result: const []);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Mes reçus'), findsOneWidget);
      });
    });

    group('état de chargement', () {
      testWidgets(
          'CircularProgressIndicator visible pendant le chargement (avant résolution)',
          (tester) async {
        final completer = Completer<List<Receipt>>();
        final gateway = _StubGateway(future: completer.future);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );

        expect(find.byType(CircularProgressIndicator), findsOneWidget);

        completer.complete(const []);
        await tester.pumpAndSettle();
      });
    });

    group('affichage d\'un reçu', () {
      testWidgets('affiche le nom du salon', (tester) async {
        final gateway = _StubGateway(result: [_receipt()]);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Salon Élégance'), findsOneWidget);
      });

      testWidgets('affiche le montant "5000.00 FCFA"', (tester) async {
        final gateway = _StubGateway(result: [_receipt(amount: '5000.00')]);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('5000.00 FCFA'), findsOneWidget);
      });

      testWidgets('plusieurs reçus → autant de cartes', (tester) async {
        final gateway = _StubGateway(
          result: [
            _receipt(paymentId: 'payment-1', salonName: 'Salon A'),
            _receipt(paymentId: 'payment-2', salonName: 'Salon B'),
          ],
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Salon A'), findsOneWidget);
        expect(find.text('Salon B'), findsOneWidget);
      });
    });

    group('état vide', () {
      testWidgets('liste vide → message "Vous n\'avez aucun reçu pour le moment."',
          (tester) async {
        final gateway = _StubGateway(result: const []);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(
          find.text('Vous n\'avez aucun reçu pour le moment.'),
          findsOneWidget,
        );
      });
    });

    group('session absente', () {
      testWidgets(
          'sans jeton : onRequireLogin est appelé et bouton "Se connecter" affiché',
          (tester) async {
        var loginCalled = false;
        final gateway = _StubGateway(result: const []);
        await tester.pumpWidget(
          _screen(
            gateway: gateway,
            session: _emptySession(),
            onRequireLogin: (_) async {
              loginCalled = true;
              return false;
            },
          ),
        );
        await tester.pumpAndSettle();

        expect(loginCalled, isTrue);
        expect(find.text('Se connecter'), findsOneWidget);
      });
    });

    group('UnauthorizedException (jeton expiré, §11.1)', () {
      testWidgets('401 → session effacée (jeton null après règlement)',
          (tester) async {
        final store = InMemoryTokenStore();
        store.write('valid-token-abc');
        final session = AuthSession(store);
        final gateway = _StubGateway(error: const UnauthorizedException());
        await tester.pumpWidget(_screen(gateway: gateway, session: session));
        await tester.pumpAndSettle();

        expect(await store.read(), isNull);
      });

      testWidgets('401 → message "Session expirée, veuillez vous reconnecter."',
          (tester) async {
        final gateway = _StubGateway(error: const UnauthorizedException());
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('expired-token')),
        );
        await tester.pumpAndSettle();

        expect(
          find.text('Session expirée, veuillez vous reconnecter.'),
          findsOneWidget,
        );
      });
    });

    group('erreur réseau / serveur', () {
      testWidgets('ReceiptGatewayException → message d\'erreur + bouton "Réessayer"',
          (tester) async {
        final gateway = _StubGateway(
          error: const ReceiptGatewayException('Impossible de joindre le serveur.'),
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Impossible de joindre le serveur.'), findsOneWidget);
        expect(find.text('Réessayer'), findsOneWidget);
      });
    });

    group('Navigation liste → détail', () {
      testWidgets('taper une carte ouvre le détail du reçu', (tester) async {
        final receipt = _receipt(paymentId: 'payment-1', salonName: 'Salon Cliquable');
        final gateway = _StubGateway(result: [receipt], detail: receipt);

        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        await tester.tap(find.text('Salon Cliquable'));
        await tester.pumpAndSettle();

        expect(find.byType(ReceiptDetailScreen), findsOneWidget);
        expect(find.text('REC-000001'), findsOneWidget);
      });
    });
  });
}
