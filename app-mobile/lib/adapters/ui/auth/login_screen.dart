// Écran UI : connexion cliente (§7.1, #22).
//
// Formulaire minimal (identifiant = téléphone ou e-mail + mot de passe) branché
// sur le cas d'usage `SignIn` (injecté), qui enregistre le jeton en session. Sur
// succès, l'écran se referme en renvoyant `true` — le tunnel de réservation reprend.
//
// Sécurité (§11.1) : ni l'identifiant, ni le mot de passe, ni le jeton ne sont
// journalisés ; l'erreur affichée est le message **neutre** de `AuthException`.

import 'package:flutter/material.dart';

import '../../../application/ports/auth_gateway.dart';
import '../../../application/use_cases/sign_in.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.signIn});

  final SignIn signIn;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final TextEditingController _identifier = TextEditingController();
  final TextEditingController _password = TextEditingController();

  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      _identifier.text.trim().isNotEmpty && _password.text.isNotEmpty;

  Future<void> _submit() async {
    if (!_canSubmit || _submitting) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await widget.signIn.call(
        identifier: _identifier.text.trim(),
        password: _password.text,
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on AuthException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _submitting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Connexion')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: <Widget>[
          Text(
            'Connectez-vous pour réserver votre rendez-vous.',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 24),
          TextField(
            controller: _identifier,
            keyboardType: TextInputType.text,
            autocorrect: false,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Téléphone ou e-mail',
              prefixIcon: Icon(Icons.person_outline),
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _password,
            obscureText: true,
            onChanged: (_) => setState(() {}),
            onSubmitted: (_) => _submit(),
            decoration: const InputDecoration(
              labelText: 'Mot de passe',
              prefixIcon: Icon(Icons.lock_outline),
              border: OutlineInputBorder(),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: (_canSubmit && !_submitting) ? _submit : null,
              child: _submitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Se connecter'),
            ),
          ),
        ],
      ),
    );
  }
}
