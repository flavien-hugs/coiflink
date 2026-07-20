// Tests unitaires — cas d'usage GetSalonDetail (#19).
//
// Couverture : délégation au gateway (retour du détail), propagation de
// SalonNotFoundException (404 → introuvable) et de SalonCatalogException (réseau).
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';

class _StubGateway implements SalonCatalogGateway {
  _StubGateway({this.detail, this.error});

  final SalonDetail? detail;
  final Object? error;
  String? lastId;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async {
    lastId = id;
    if (error != null) throw error!;
    return detail!;
  }
}

void main() {
  group('GetSalonDetail', () {
    test('délègue au gateway et retourne le détail', () async {
      const detail = SalonDetail(id: 'uuid-1', name: 'Salon X', isBookable: true);
      final gateway = _StubGateway(detail: detail);

      final result = await GetSalonDetail(gateway).call('uuid-1');

      expect(result, same(detail));
      expect(gateway.lastId, 'uuid-1');
    });

    test('propage SalonNotFoundException (404 → introuvable)', () async {
      final gateway = _StubGateway(error: const SalonNotFoundException());

      await expectLater(
        GetSalonDetail(gateway).call('uuid-1'),
        throwsA(isA<SalonNotFoundException>()),
      );
    });

    test('propage SalonCatalogException (erreur réseau)', () async {
      final gateway =
          _StubGateway(error: const SalonCatalogException('Réseau indisponible.'));

      await expectLater(
        GetSalonDetail(gateway).call('uuid-1'),
        throwsA(isA<SalonCatalogException>()),
      );
    });
  });
}
