// Élément visuel partagé entre les écrans du parcours borne (US-8.5, #159).
//
// Aucun écran client de la borne n'utilise l'AppBar Material — remplacée par ce
// chevron flottant, cohérent avec l'identité visuelle propre à la borne (§storyboard
// approuvé). Un seul geste : revenir à l'écran précédent.

import 'package:flutter/material.dart';

import 'kiosk_theme.dart';

class KioskBackButton extends StatelessWidget {
  const KioskBackButton({super.key});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Align(
        alignment: Alignment.topLeft,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Material(
            color: KioskColors.surface,
            shape: const CircleBorder(
              side: BorderSide(color: KioskColors.border, width: 1.5),
            ),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: () => Navigator.of(context).maybePop(),
              child: const SizedBox(
                width: 44,
                height: 44,
                child: Icon(
                  Icons.arrow_back_ios_new,
                  size: 18,
                  color: KioskColors.muted,
                  semanticLabel: 'Retour',
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
