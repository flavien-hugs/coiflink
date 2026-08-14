// Tests unitaires — TerminalDeviceSession (US-8.5, #159).
//
// Couverture : authenticate (succès, credential refusé, réseau) ; salonId /
// authorizationHeaders avant et après authenticate ; seedDevSalon (dev) ;
// reauthenticate (réutilise le dernier credential, lève StateError avant tout
// premier succès). Le credential est fourni à chaque appel (`TerminalBootstrap` le
// lit de `TerminalCredentialStore`) — cette classe ne le lit ni ne le persiste
// elle-même. Aucune dépendance Flutter ni réseau.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/terminal_device_session.dart';
import 'package:coiflink_mobile/application/ports/terminal_auth_gateway.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubAuthGateway implements TerminalAuthGateway {
  _StubAuthGateway({this.tokens, this.error});

  final TerminalDeviceTokens? tokens;
  final Object? error;
  final List<TerminalCredential> loginCalls = <TerminalCredential>[];

  @override
  Future<TerminalDeviceTokens> login(TerminalCredential credential) async {
    loginCalls.add(credential);
    if (error != null) throw error!;
    return tokens!;
  }
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const _credential = TerminalCredential(deviceId: 'dev-001', secret: 's3cr3t');

TerminalDeviceSession _session({TerminalAuthGateway? auth}) => TerminalDeviceSession(
      auth ??
          _StubAuthGateway(
            tokens: const TerminalDeviceTokens(accessToken: 'acc', salonId: 'sal-1'),
          ),
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalDeviceSession.isAuthenticated', () {
    test('false avant authenticate', () {
      expect(_session().isAuthenticated, isFalse);
    });

    test('true après authenticate réussie', () async {
      final s = _session();
      await s.authenticate(_credential);
      expect(s.isAuthenticated, isTrue);
    });
  });

  group('TerminalDeviceSession.authenticate', () {
    test('succès : expose le salonId de la réponse', () async {
      final s = TerminalDeviceSession(
        _StubAuthGateway(
          tokens: const TerminalDeviceTokens(accessToken: 'tok', salonId: 'salon-xyz'),
        ),
      );
      await s.authenticate(_credential);
      expect(s.salonId, 'salon-xyz');
    });

    test('transmet le credential fourni au gateway', () async {
      final auth = _StubAuthGateway(
        tokens: const TerminalDeviceTokens(accessToken: 'tok', salonId: 'sal'),
      );
      final s = TerminalDeviceSession(auth);
      await s.authenticate(_credential);
      expect(auth.loginCalls, <TerminalCredential>[_credential]);
    });

    test('credential refusé → lève TerminalInvalidCredentialException', () async {
      final s = TerminalDeviceSession(
        _StubAuthGateway(error: const TerminalInvalidCredentialException()),
      );
      await expectLater(
        s.authenticate(_credential),
        throwsA(isA<TerminalInvalidCredentialException>()),
      );
      expect(s.isAuthenticated, isFalse);
    });

    test('échec réseau → lève TerminalAuthException', () async {
      final s = TerminalDeviceSession(
        _StubAuthGateway(error: const TerminalAuthException()),
      );
      await expectLater(
        s.authenticate(_credential),
        throwsA(isA<TerminalAuthException>()),
      );
    });
  });

  group('TerminalDeviceSession.salonId', () {
    test('lève StateError avant authenticate', () {
      expect(() => _session().salonId, throwsStateError);
    });
  });

  group('TerminalDeviceSession.authorizationHeaders', () {
    test('lève StateError avant authenticate', () {
      expect(() => _session().authorizationHeaders(), throwsStateError);
    });

    test('contient Authorization: Bearer <accessToken> après authenticate', () async {
      final s = TerminalDeviceSession(
        _StubAuthGateway(
          tokens: const TerminalDeviceTokens(accessToken: 'my-token-123', salonId: 'sal'),
        ),
      );
      await s.authenticate(_credential);
      expect(
        s.authorizationHeaders(),
        {'Authorization': 'Bearer my-token-123'},
      );
    });
  });

  group('TerminalDeviceSession.authenticate — état après échec', () {
    test('salonId lève StateError après un TerminalAuthException', () async {
      final s = TerminalDeviceSession(
        _StubAuthGateway(error: const TerminalAuthException('réseau KO')),
      );
      await expectLater(s.authenticate(_credential), throwsA(isA<TerminalAuthException>()));

      // salonId ne doit pas être exposé après un échec réseau
      expect(() => s.salonId, throwsStateError);
    });

    test('authorizationHeaders lève StateError après un TerminalAuthException', () async {
      final s = TerminalDeviceSession(
        _StubAuthGateway(error: const TerminalAuthException('réseau KO')),
      );
      await expectLater(s.authenticate(_credential), throwsA(isA<TerminalAuthException>()));

      expect(() => s.authorizationHeaders(), throwsStateError);
    });
  });

  group('TerminalDeviceSession.reauthenticate', () {
    test('lève StateError si authenticate n\'a jamais réussi', () {
      expect(() => _session().reauthenticate(), throwsStateError);
    });

    test('réutilise le dernier credential authentifié avec succès', () async {
      final auth = _StubAuthGateway(
        tokens: const TerminalDeviceTokens(accessToken: 'tok', salonId: 'sal'),
      );
      final s = TerminalDeviceSession(auth);
      await s.authenticate(_credential);

      await s.reauthenticate();

      expect(auth.loginCalls, <TerminalCredential>[_credential, _credential]);
    });

    test('rafraîchit le jeton d\'accès', () async {
      var call = 0;
      final auth = _RotatingTokenAuthGateway(() {
        call++;
        return TerminalDeviceTokens(accessToken: 'tok-$call', salonId: 'sal');
      });
      final s = TerminalDeviceSession(auth);
      await s.authenticate(_credential);
      expect(s.authorizationHeaders(), {'Authorization': 'Bearer tok-1'});

      await s.reauthenticate();

      expect(s.authorizationHeaders(), {'Authorization': 'Bearer tok-2'});
    });
  });

  group('TerminalDeviceSession.seedDevSalon', () {
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

class _RotatingTokenAuthGateway implements TerminalAuthGateway {
  _RotatingTokenAuthGateway(this._next);

  final TerminalDeviceTokens Function() _next;

  @override
  Future<TerminalDeviceTokens> login(TerminalCredential credential) async => _next();
}
