// Tests widget — ReceiptDetailScreen (US-5.5, #38 · ADR-0040).
//
// Couverture : titre AppBar ; indicateur de chargement ; contenu du reçu
// (salon, numéro, ligne de prestation, total) ; reçu introuvable (bouton
// « Retour à la liste ») ; erreur réseau + « Réessayer » ; session absente ;
// UnauthorizedException ; bouton « Partager » invoque le callback injecté avec
// le texte formaté (aucun appel réel à `share_plus`).
// Aucun appel HTTP réel ; aucun jeton de production dans les fixtures (§11).

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/receipts/receipt_detail_screen.dart';
import 'package:coiflink_mobile/application/auth_session.dart';
import 'package:coiflink_mobile/application/ports/receipt_gateway.dart';
import 'package:coiflink_mobile/application/ports/token_store.dart';
import 'package:coiflink_mobile/application/use_cases/get_receipt_detail.dart';
import 'package:coiflink_mobile/domain/receipt/receipt.dart';

// ---------------------------------------------------------------------------
// Faux gateway
// ---------------------------------------------------------------------------

class _StubGateway implements ReceiptGateway {
  _StubGateway({this.detail, this.error, this.future});

  final Receipt? detail;
  final Object? error;
  final Future<Receipt>? future;

  @override
  Future<List<Receipt>> myReceipts({required String accessToken}) =>
      throw UnimplementedError();

  @override
  Future<Receipt> receiptDetail({
    required String paymentId,
    required String accessToken,
  }) async {
    if (future != null) return future!;
    if (error != null) throw error!;
    return detail!;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

AuthSession _sessionWithToken(String token) {
  final store = InMemoryTokenStore();
  store.write(token);
  return AuthSession(store);
}

InMemoryTokenStore _emptyStore() => InMemoryTokenStore();

AuthSession _emptySession() => AuthSession(_emptyStore());

Receipt _receipt() {
  return Receipt(
    receiptNumber: 'REC-000001',
    paymentId: 'payment-1',
    salonName: 'Salon Élégance',
    amount: '5000.00',
    currency: 'XOF',
    paymentMethod: 'CASH',
    status: 'VALIDATED',
    paidAt: DateTime(2026, 7, 30, 10, 15),
    lines: const <ReceiptLine>[
      ReceiptLine(serviceName: 'Coupe homme', amount: '5000.00'),
    ],
  );
}

Widget _screen({
  required ReceiptGateway gateway,
  required AuthSession session,
  Future<bool> Function(BuildContext)? onRequireLogin,
  ReceiptShareInvoker? shareInvoker,
}) {
  return MaterialApp(
    home: ReceiptDetailScreen(
      paymentId: 'payment-1',
      getReceiptDetail: GetReceiptDetail(gateway),
      session: session,
      onRequireLogin: onRequireLogin ?? (_) async => false,
      shareInvoker: shareInvoker ?? (_) async {},
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('ReceiptDetailScreen', () {
    group('titre', () {
      testWidgets('AppBar affiche "Reçu"', (tester) async {
        final gateway = _StubGateway(detail: _receipt());
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Reçu'), findsOneWidget);
      });
    });

    group('état de chargement', () {
      testWidgets('CircularProgressIndicator visible avant résolution',
          (tester) async {
        final completer = Completer<Receipt>();
        final gateway = _StubGateway(future: completer.future);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );

        expect(find.byType(CircularProgressIndicator), findsOneWidget);

        completer.complete(_receipt());
        await tester.pumpAndSettle();
      });
    });

    group('contenu du reçu', () {
      testWidgets('affiche le salon, le numéro, la ligne et le total',
          (tester) async {
        final gateway = _StubGateway(detail: _receipt());
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Salon Élégance'), findsOneWidget);
        expect(find.text('REC-000001'), findsOneWidget);
        expect(find.text('Coupe homme'), findsOneWidget);
        expect(find.text('5000.00 FCFA'), findsAtLeastNWidgets(1));
      });
    });

    group('reçu introuvable (404 neutre, §11.3)', () {
      testWidgets('message "Ce reçu est introuvable." + bouton "Retour à la liste"',
          (tester) async {
        final gateway = _StubGateway(error: const ReceiptNotFoundException());
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Ce reçu est introuvable.'), findsOneWidget);
        expect(find.text('Retour à la liste'), findsOneWidget);
      });
    });

    group('session absente', () {
      testWidgets('sans jeton : onRequireLogin est appelé', (tester) async {
        var loginCalled = false;
        final gateway = _StubGateway(detail: _receipt());
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
      testWidgets('401 → session effacée + message "Session expirée..."',
          (tester) async {
        final store = InMemoryTokenStore();
        store.write('valid-token-abc');
        final session = AuthSession(store);
        final gateway = _StubGateway(error: const UnauthorizedException());
        await tester.pumpWidget(_screen(gateway: gateway, session: session));
        await tester.pumpAndSettle();

        expect(await store.read(), isNull);
        expect(
          find.text('Session expirée, veuillez vous reconnecter.'),
          findsOneWidget,
        );
      });
    });

    group('erreur réseau / serveur', () {
      testWidgets('message d\'erreur + bouton "Réessayer"', (tester) async {
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

    group('Partager', () {
      testWidgets('tap sur l\'icône Partager invoque le callback avec le texte formaté',
          (tester) async {
        String? sharedText;
        final gateway = _StubGateway(detail: _receipt());
        await tester.pumpWidget(
          _screen(
            gateway: gateway,
            session: _sessionWithToken('tok'),
            shareInvoker: (text) async {
              sharedText = text;
            },
          ),
        );
        await tester.pumpAndSettle();

        await tester.tap(find.byIcon(Icons.share_outlined));
        await tester.pumpAndSettle();

        expect(sharedText, isNotNull);
        expect(sharedText, contains('Salon Élégance'));
        expect(sharedText, contains('Coupe homme'));
        expect(sharedText, isNot(contains('tok')));
      });

      testWidgets('aucune icône Partager pendant le chargement', (tester) async {
        final completer = Completer<Receipt>();
        final gateway = _StubGateway(future: completer.future);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );

        expect(find.byIcon(Icons.share_outlined), findsNothing);

        completer.complete(_receipt());
        await tester.pumpAndSettle();
      });
    });
  });
}
