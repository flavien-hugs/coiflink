// Tests unitaires — SignIn, AuthSession, InMemoryTokenStore (#22).
//
// Couverture : SignIn enregistre le jeton en session sur succès ; ne modifie pas
// la session sur AuthException ; AuthSession.isAuthenticated ; AuthSession.clear ;
// InMemoryTokenStore read/write/clear.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/auth_session.dart';
import 'package:coiflink_mobile/application/ports/auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/token_store.dart';
import 'package:coiflink_mobile/application/use_cases/sign_in.dart';

// ---------------------------------------------------------------------------
// Faux gateways
// ---------------------------------------------------------------------------

class _SuccessAuthGateway implements AuthGateway {
  _SuccessAuthGateway({required this.tokens});

  final AuthTokens tokens;
  String? lastIdentifier;

  @override
  Future<AuthTokens> login({
    required String identifier,
    required String password,
  }) async {
    lastIdentifier = identifier;
    return tokens;
  }
}

class _FailingAuthGateway implements AuthGateway {
  @override
  Future<AuthTokens> login({
    required String identifier,
    required String password,
  }) async {
    throw const AuthException();
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('InMemoryTokenStore', () {
    test('read retourne null initialement', () async {
      final store = InMemoryTokenStore();

      expect(await store.read(), isNull);
    });

    test('write puis read retourne le jeton', () async {
      final store = InMemoryTokenStore();

      await store.write('tok-abc');

      expect(await store.read(), 'tok-abc');
    });

    test('clear → read retourne null', () async {
      final store = InMemoryTokenStore();
      await store.write('tok-abc');

      await store.clear();

      expect(await store.read(), isNull);
    });

    test('write écrase le jeton précédent', () async {
      final store = InMemoryTokenStore();
      await store.write('tok-old');
      await store.write('tok-new');

      expect(await store.read(), 'tok-new');
    });
  });

  group('AuthSession', () {
    test('isAuthenticated → false sans session', () async {
      final session = AuthSession(InMemoryTokenStore());

      expect(await session.isAuthenticated(), isFalse);
    });

    test('isAuthenticated → true après save', () async {
      final session = AuthSession(InMemoryTokenStore());

      await session.save('tok-xyz');

      expect(await session.isAuthenticated(), isTrue);
    });

    test('currentToken → null sans session', () async {
      final session = AuthSession(InMemoryTokenStore());

      expect(await session.currentToken(), isNull);
    });

    test('currentToken → jeton après save', () async {
      final session = AuthSession(InMemoryTokenStore());

      await session.save('tok-xyz');

      expect(await session.currentToken(), 'tok-xyz');
    });

    test('clear → isAuthenticated retourne false', () async {
      final session = AuthSession(InMemoryTokenStore());
      await session.save('tok-xyz');

      await session.clear();

      expect(await session.isAuthenticated(), isFalse);
    });

    test('clear → currentToken retourne null', () async {
      final session = AuthSession(InMemoryTokenStore());
      await session.save('tok-xyz');

      await session.clear();

      expect(await session.currentToken(), isNull);
    });
  });

  group('SignIn', () {
    test('succès : enregistre le jeton en session', () async {
      final gateway = _SuccessAuthGateway(
        tokens: const AuthTokens(accessToken: 'acc-tok'),
      );
      final session = AuthSession(InMemoryTokenStore());
      final useCase = SignIn(gateway, session);

      await useCase.call(identifier: 'user@example.com', password: 'pass');

      expect(await session.currentToken(), 'acc-tok');
      expect(await session.isAuthenticated(), isTrue);
    });

    test('échec AuthException : session NON modifiée', () async {
      final gateway = _FailingAuthGateway();
      final session = AuthSession(InMemoryTokenStore());
      final useCase = SignIn(gateway, session);

      await expectLater(
        useCase.call(identifier: 'user@example.com', password: 'wrong'),
        throwsA(isA<AuthException>()),
      );

      expect(await session.isAuthenticated(), isFalse);
    });

    test('propage AuthException du gateway', () async {
      final gateway = _FailingAuthGateway();
      final session = AuthSession(InMemoryTokenStore());
      final useCase = SignIn(gateway, session);

      await expectLater(
        useCase.call(identifier: 'id', password: 'pw'),
        throwsA(isA<AuthException>()),
      );
    });

    test('transmet l\'identifiant au gateway', () async {
      final gateway = _SuccessAuthGateway(
        tokens: const AuthTokens(accessToken: 'tok'),
      );
      final session = AuthSession(InMemoryTokenStore());
      final useCase = SignIn(gateway, session);

      await useCase.call(identifier: 'mon.identifiant', password: 'pw');

      expect(gateway.lastIdentifier, 'mon.identifiant');
    });

    test('message AuthException ne contient pas l\'identifiant ni le mot de passe',
        () async {
      final gateway = _FailingAuthGateway();
      final session = AuthSession(InMemoryTokenStore());
      final useCase = SignIn(gateway, session);

      Object? caught;
      try {
        await useCase.call(identifier: 'user@secret.com', password: 'pw123');
      } catch (e) {
        caught = e;
      }

      expect(caught, isA<AuthException>());
      final msg = (caught as AuthException).message;
      expect(msg.contains('user@secret.com'), isFalse);
      expect(msg.contains('pw123'), isFalse);
    });
  });
}
