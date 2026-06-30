// Point d'entrée de l'application mobile CoifLink (Flutter).
//
// Squelette d'initialisation du dépôt (#2) : écran d'accueil neutre, sans
// aucune fonctionnalité métier (réservation, historique, rappels → issues M1→).
// Conforme à ADR-0001 (Flutter, Android prioritaire).

import 'package:flutter/material.dart';

void main() {
  runApp(const CoifLinkApp());
}

class CoifLinkApp extends StatelessWidget {
  const CoifLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CoifLink',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('CoifLink')),
      body: const Center(
        child: Text('CoifLink'),
      ),
    );
  }
}
