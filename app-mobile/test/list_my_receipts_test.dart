// Tests unitaires — cas d'usage ListMyReceipts (US-5.5, #38 · ADR-0040).
//
// Couverture : délégation au gateway avec le bon accessToken ; retour de la
// liste fournie par le gateway (liste pleine, liste vide) ; propagation de
// UnauthorizedException et ReceiptGatewayException.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/receipt_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/list_my_receipts.dart';
import 'package:coiflink_mobile/domain/receipt/receipt.dart';

class _StubGateway implements ReceiptGateway {
  _StubGateway({this.listResult, this.error});

  final List<Receipt>? listResult;
  final Object? error;

  String? lastToken;

  @override
  Future<List<Receipt>> myReceipts({required String accessToken}) async {
    lastToken = accessToken;
    if (error != null) throw error!;
    return listResult ?? const <Receipt>[];
  }

  @override
  Future<Receipt> receiptDetail({
    required String paymentId,
    required String accessToken,
  }) =>
      throw UnimplementedError();
}

Receipt _receipt({String paymentId = 'payment-1'}) {
  return Receipt(
    receiptNumber: 'REC-000001',
    paymentId: paymentId,
    salonName: 'Salon Élégance',
    amount: '5000.00',
    currency: 'XOF',
    paymentMethod: 'CASH',
    status: 'VALIDATED',
    paidAt: DateTime(2026, 7, 30, 10, 15),
  );
}

void main() {
  group('ListMyReceipts', () {
    group('délégation au gateway', () {
      test('transmet exactement l\'accessToken reçu au gateway', () async {
        final gateway = _StubGateway(listResult: const <Receipt>[]);
        final useCase = ListMyReceipts(gateway);

        await useCase.call(accessToken: 'client-bearer-xyz');

        expect(gateway.lastToken, 'client-bearer-xyz');
      });

      test('retourne la liste de reçus fournie par le gateway', () async {
        final expected = <Receipt>[
          _receipt(paymentId: 'payment-a'),
          _receipt(paymentId: 'payment-b'),
        ];
        final gateway = _StubGateway(listResult: expected);
        final useCase = ListMyReceipts(gateway);

        final result = await useCase.call(accessToken: 'tok');

        expect(result, same(expected));
        expect(result, hasLength(2));
      });

      test('retourne une liste vide quand le gateway renvoie une liste vide',
          () async {
        final gateway = _StubGateway(listResult: const <Receipt>[]);
        final useCase = ListMyReceipts(gateway);

        final result = await useCase.call(accessToken: 'tok');

        expect(result, isEmpty);
      });
    });

    group('propagation des erreurs du gateway', () {
      test('propage UnauthorizedException (jeton expiré, §11.1)', () async {
        final gateway = _StubGateway(error: const UnauthorizedException());
        final useCase = ListMyReceipts(gateway);

        await expectLater(
          useCase.call(accessToken: 'expired-token'),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('propage ReceiptGatewayException (erreur réseau/serveur)', () async {
        final gateway = _StubGateway(
          error: const ReceiptGatewayException('Impossible de joindre le serveur.'),
        );
        final useCase = ListMyReceipts(gateway);

        await expectLater(
          useCase.call(accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });
    });
  });
}
