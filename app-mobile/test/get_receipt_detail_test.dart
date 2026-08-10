// Tests unitaires — cas d'usage GetReceiptDetail (US-5.5, #38 · ADR-0040).
//
// Couverture : délégation au gateway avec le paymentId/accessToken reçus ;
// retour du reçu fourni par le gateway ; propagation de UnauthorizedException,
// ReceiptNotFoundException et ReceiptGatewayException.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/receipt_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_receipt_detail.dart';
import 'package:coiflink_mobile/domain/receipt/receipt.dart';

class _StubGateway implements ReceiptGateway {
  _StubGateway({this.detailResult, this.error});

  final Receipt? detailResult;
  final Object? error;

  String? lastPaymentId;
  String? lastToken;

  @override
  Future<List<Receipt>> myReceipts({required String accessToken}) =>
      throw UnimplementedError();

  @override
  Future<Receipt> receiptDetail({
    required String paymentId,
    required String accessToken,
  }) async {
    lastPaymentId = paymentId;
    lastToken = accessToken;
    if (error != null) throw error!;
    return detailResult!;
  }
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
  group('GetReceiptDetail', () {
    group('délégation au gateway', () {
      test('transmet exactement le paymentId et l\'accessToken', () async {
        final gateway = _StubGateway(detailResult: _receipt());
        final useCase = GetReceiptDetail(gateway);

        await useCase.call(paymentId: 'payment-42', accessToken: 'client-bearer-xyz');

        expect(gateway.lastPaymentId, 'payment-42');
        expect(gateway.lastToken, 'client-bearer-xyz');
      });

      test('retourne le reçu fourni par le gateway', () async {
        final expected = _receipt(paymentId: 'payment-a');
        final gateway = _StubGateway(detailResult: expected);
        final useCase = GetReceiptDetail(gateway);

        final result = await useCase.call(paymentId: 'payment-a', accessToken: 'tok');

        expect(result, same(expected));
      });
    });

    group('propagation des erreurs du gateway', () {
      test('propage UnauthorizedException (jeton expiré, §11.1)', () async {
        final gateway = _StubGateway(error: const UnauthorizedException());
        final useCase = GetReceiptDetail(gateway);

        await expectLater(
          useCase.call(paymentId: 'payment-1', accessToken: 'expired-token'),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('propage ReceiptNotFoundException (404 neutre, §11.3)', () async {
        final gateway = _StubGateway(error: const ReceiptNotFoundException());
        final useCase = GetReceiptDetail(gateway);

        await expectLater(
          useCase.call(paymentId: 'payment-other', accessToken: 'tok'),
          throwsA(isA<ReceiptNotFoundException>()),
        );
      });

      test('propage ReceiptGatewayException (erreur réseau/serveur)', () async {
        final gateway = _StubGateway(
          error: const ReceiptGatewayException('Impossible de joindre le serveur.'),
        );
        final useCase = GetReceiptDetail(gateway);

        await expectLater(
          useCase.call(paymentId: 'payment-1', accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });
    });
  });
}
