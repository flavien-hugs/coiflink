// Tests unitaires — KioskDeviceSession (US-8.5, #159).
//
// Couverture : authenticate (succès, credential refusé, réseau) ; salonId /
// authorizationHeaders avant et après authenticate ; seedDevSalon (dev) ;
// reauthenticate (réutilise le dernier credential, lève StateError avant tout
// premier succès). Le credential est fourni à chaque appel (`KioskBootstrap` le
// lit de `KioskCredentialStore`) — cette classe ne le lit ni ne le persiste
// elle-même. Aucune dépendance Flutter ni réseau.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/kiosk_device_session.dart';
import 'package:coiflink_mobile/application/ports/kiosk_auth_gateway.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubAuthGateway implements KioskAuthGateway {
  _StubAuthGateway({this.tokens, this.error});

  final KioskDeviceTokens? tokens;
  final Object? error;
  final List<KioskCredential> loginCalls = <KioskCredential>[];

  @override
  Future<KioskDeviceTokens> login(KioskCredential credential) async {
    loginCalls.add(credential);
    if (error != null) throw error!;
    return tokens!;
  }
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const _credential = KioskCredential(deviceId: 'dev-001', secret: 's3cr3t');

KioskDeviceSession _session({KioskAuthGateway? auth}) => KioskDeviceSession(
      auth ??
          _StubAuthGateway(
            tokens: const KioskDeviceTokens(accessToken: 'acc', salonId: 'sal-1'),
          ),
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('KioskDeviceSession.isAuthenticated', () {
    test('false avant authenticate', () {
      expect(_session().isAuthenticated, isFalse);
    });

    test('true après authenticate réussie', () async {
      final s = _session();
      await s.authenticate(_credential);
      expect(s.isAuthenticated, isTrue);
    });
  });

  group('KioskDeviceSession.authenticate', () {
    test('succès : expose le salonId de la réponse', () async {
      final s = KioskDeviceSession(
        _StubAuthGateway(
          tokens: const KioskDeviceTokens(accessToken: 'tok', salonId: 'salon-xyz'),
        ),
      );
      await s.authenticate(_credential);
      expect(s.salonId, 'salon-xyz');
    });

    test('transmet le credential fourni au gateway', () async {
      final auth = _StubAuthGateway(
        tokens: const KioskDeviceTokens(accessToken: 'tok', salonId: 'sal'),
      );
      final s = KioskDeviceSession(auth);
      await s.authenticate(_credential);
      expect(auth.loginCalls, <KioskCredential>[_credential]);
    });

    test('credential refusé → lève KioskInvalidCredentialException', () async {
      final s = KioskDeviceSession(
        _StubAuthGateway(error: const KioskInvalidCredentialException()),
      );
      await expectLater(
        s.authenticate(_credential),
        throwsA(isA<KioskInvalidCredentialException>()),
      );
      expect(s.isAuthenticated, isFalse);
    });

    test('échec réseau → lève KioskAuthException', () async {
      final s = KioskDeviceSession(
        _StubAuthGateway(error: const KioskAuthException()),
      );
      await expectLater(
        s.authenticate(_credential),
        throwsA(isA<KioskAuthException>()),
      );
    });
  });

  group('KioskDeviceSession.salonId', () {
    test('lève StateError avant authenticate', () {
      expect(() => _session().salonId, throwsStateError);
    });
  });

  group('KioskDeviceSession.authorizationHeaders', () {
    test('lève StateError avant authenticate', () {
      expect(() => _session().authorizationHeaders(), throwsStateError);
    });

    test('contient Authorization: Bearer <accessToken> après authenticate', () async {
      final s = KioskDeviceSession(
        _StubAuthGateway(
          tokens: const KioskDeviceTokens(accessToken: 'my-token-123', salonId: 'sal'),
        ),
      );
      await s.authenticate(_credential);
      expect(
        s.authorizationHeaders(),
        {'Authorization': 'Bearer my-token-123'},
      );
    });
  });

  group('KioskDeviceSession.authenticate — état après échec', () {
    test('salonId lève StateError après un KioskAuthException', () async {
      final s = KioskDeviceSession(
        _StubAuthGateway(error: const KioskAuthException('réseau KO')),
      );
      await expectLater(s.authenticate(_credential), throwsA(isA<KioskAuthException>()));

      // salonId ne doit pas être exposé après un échec réseau
      expect(() => s.salonId, throwsStateError);
    });

    test('authorizationHeaders lève StateError après un KioskAuthException', () async {
      final s = KioskDeviceSession(
        _StubAuthGateway(error: const KioskAuthException('réseau KO')),
      );
      await expectLater(s.authenticate(_credential), throwsA(isA<KioskAuthException>()));

      expect(() => s.authorizationHeaders(), throwsStateError);
    });
  });

  group('KioskDeviceSession.reauthenticate', () {
    test('lève StateError si authenticate n\'a jamais réussi', () {
      expect(() => _session().reauthenticate(), throwsStateError);
    });

    test('réutilise le dernier credential authentifié avec succès', () async {
      final auth = _StubAuthGateway(
        tokens: const KioskDeviceTokens(accessToken: 'tok', salonId: 'sal'),
      );
      final s = KioskDeviceSession(auth);
      await s.authenticate(_credential);

      await s.reauthenticate();

      expect(auth.loginCalls, <KioskCredential>[_credential, _credential]);
    });

    test('rafraîchit le jeton d\'accès', () async {
      var call = 0;
      final auth = _RotatingTokenAuthGateway(() {
        call++;
        return KioskDeviceTokens(accessToken: 'tok-$call', salonId: 'sal');
      });
      final s = KioskDeviceSession(auth);
      await s.authenticate(_credential);
      expect(s.authorizationHeaders(), {'Authorization': 'Bearer tok-1'});

      await s.reauthenticate();

      expect(s.authorizationHeaders(), {'Authorization': 'Bearer tok-2'});
    });
  });

  group('KioskDeviceSession.seedDevSalon', () {
    test('expose un salonId sans authentification (usage dev)', () {
      final s = _session();
      s.seedDevSalon('dev-salon-abc');
      expect(s.salonId, 'dev-salon-abc');
    });

    test('authorizationHeaders lève toujours StateError après seedDevSalon', () {
      final s = _session();
      s.seedDevSalon('dev-salon');
      expect(() => s.authorizationHeaders(), throwsStateError);
    });
  });
}

class _RotatingTokenAuthGateway implements KioskAuthGateway {
  _RotatingTokenAuthGateway(this._next);

  final KioskDeviceTokens Function() _next;

  @override
  Future<KioskDeviceTokens> login(KioskCredential credential) async => _next();
}
