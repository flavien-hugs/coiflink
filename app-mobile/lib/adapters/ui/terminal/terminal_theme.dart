// Thème & dimensions du mode terminal (US-8.5, #159).
//
// Palette **fixe**, identique aux tokens CSS du dashboard web
// (`web-dashboard/app/globals.css:29-46`) — l'écran borne ne suit jamais le thème
// clair/sombre de l'appareil qui l'affiche : c'est un monde visuel propre à la
// marque, comme un écran de caisse ou une borne bancaire. Typographie éditoriale
// (Fraunces pour les titres/le wordmark/le numéro de ticket, Outfit pour le corps/
// les formulaires/le clavier/les boutons), chargée via `google_fonts` puis mise en
// cache disque par le paquet après le premier lancement.
//
// Les valeurs de `TerminalDimensions` restent des cibles « gros boutons tactiles » à
// distance de bras, sous un éclairage de salon variable — centralisées ici pour
// rester ajustables sans toucher aux écrans qui les consomment.

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Cibles tactiles et typographiques « gros boutons » (§D de la spec).
class TerminalDimensions {
  const TerminalDimensions._();

  /// Hauteur minimale d'un bouton principal (CTA) — bien au-dessus des 48 dp
  /// Material : cible confortable à bout de bras, tolérante à une frappe imprécise.
  static const double primaryButtonHeight = 88;

  /// Hauteur minimale d'une ligne de prestation (liste pleine largeur, une
  /// prestation par ligne) — la photo carrée à gauche fait ce même côté.
  static const double serviceRowHeight = 140;

  /// Espacement minimal entre deux cibles tactiles adjacentes (anti-clic voisin).
  static const double touchSpacing = 24;

  /// Marge de contenu confortable des écrans borne.
  static const double screenPadding = 32;

  /// Taille de police du numéro de ticket sur la confirmation (identifiable d'un
  /// coup d'œil, même si le client s'éloigne aussitôt).
  static const double ticketNumberFontSize = 84;

  /// Taille de police du corps de texte / libellés de bouton (lisible à distance).
  static const double bodyFontSize = 22;
}

/// Palette de marque — mêmes valeurs hex que `web-dashboard/app/globals.css:29-46`
/// (`:root`), **jamais** recalculées depuis une graine Material. Toute nouvelle
/// couleur introduite sur un écran borne doit venir d'ici, pas d'un littéral local.
class TerminalColors {
  const TerminalColors._();

  /// `--background` — fond crème chaud, unique fond des écrans borne.
  static const Color background = Color(0xFFF8EFE1);

  /// `--foreground` — texte principal, quasi-noir chaud.
  static const Color ink = Color(0xFF1F1811);

  /// `--muted` — texte secondaire.
  static const Color muted = Color(0xFF74604C);

  /// `--border` — séparateurs, contours de champs/cartes au repos.
  static const Color border = Color(0xFFE5D8C4);

  /// `--surface` — fond des cartes, champs de saisie, touches du clavier.
  static const Color surface = Color(0xFFFFFEFD);

  /// `--accent` — terracotta, couleur du CTA principal.
  static const Color accent = Color(0xFFA94C35);

  /// `--accent-foreground` — texte sur fond accent.
  static const Color accentForeground = Color(0xFFFFFFFF);

  /// `--gold` — détails discrets (puce décorative, liseré).
  static const Color gold = Color(0xFF8A5A13);

  /// `--nude` — halos, badges, fond d'avatar.
  static const Color nude = Color(0xFFEAD9C4);

  /// `--danger` — messages d'erreur neutres (même rôle que le web, pas un rouge
  /// Material par défaut).
  static const Color danger = Color(0xFFA1213E);
}

/// `ThemeData` du mode terminal — palette et typographie **fixes** (`TerminalColors`),
/// jamais dérivées d'une graine `ColorScheme.fromSeed`.
ThemeData buildTerminalTheme() {
  const colorScheme = ColorScheme.light(
    surface: TerminalColors.background,
    onSurface: TerminalColors.ink,
    primary: TerminalColors.accent,
    onPrimary: TerminalColors.accentForeground,
    secondary: TerminalColors.gold,
    onSecondary: TerminalColors.accentForeground,
    error: TerminalColors.danger,
    onError: TerminalColors.accentForeground,
    outline: TerminalColors.border,
  );

  // Fraunces habille les titres/le wordmark/le numéro de ticket (display*/headline*/
  // titleLarge) ; Outfit habille le corps, les libellés et les boutons (body*/label*/
  // titleMedium/titleSmall) — même répartition que le dashboard web
  // (`web-dashboard/app/layout.tsx:12-14`).
  //
  // Base explicite et **complète** : `Typography.black` ne porte que la couleur
  // (aucune géométrie — voir sa documentation), `Typography.englishLike` ne porte
  // que la géométrie (taille, graisse, hauteur de ligne). Sans fusionner les deux,
  // chaque style se retrouve avec un `fontSize` nul, ce qui fait échouer
  // l'assertion de `TextTheme.apply(fontSizeFactor: …)` plus bas dès que ce facteur
  // n'est pas 1.0 (`fontSize != null || fontSizeFactor == 1.0`) — piège classique
  // hors d'un `BuildContext`, où ce mélange serait normalement fait pour nous.
  final typography = Typography.material2021();
  final baseTextTheme = typography.black.merge(typography.englishLike);
  final displayTextTheme = GoogleFonts.frauncesTextTheme(baseTextTheme);
  final bodyTextTheme = GoogleFonts.outfitTextTheme(baseTextTheme);
  final textTheme = bodyTextTheme
      .copyWith(
        displayLarge: displayTextTheme.displayLarge,
        displayMedium: displayTextTheme.displayMedium,
        displaySmall: displayTextTheme.displaySmall,
        headlineLarge: displayTextTheme.headlineLarge,
        headlineMedium: displayTextTheme.headlineMedium,
        headlineSmall: displayTextTheme.headlineSmall,
        titleLarge: displayTextTheme.titleLarge,
      )
      .apply(
        bodyColor: TerminalColors.ink,
        displayColor: TerminalColors.ink,
        fontSizeFactor: 1.15,
      );

  final buttonShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(20),
  );
  final buttonTextStyle = GoogleFonts.outfit(
    fontSize: TerminalDimensions.bodyFontSize,
    fontWeight: FontWeight.w600,
  );
  const minButtonSize = Size.fromHeight(TerminalDimensions.primaryButtonHeight);

  return ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    scaffoldBackgroundColor: TerminalColors.background,
    canvasColor: TerminalColors.background,
    textTheme: textTheme,
    appBarTheme: const AppBarTheme(
      backgroundColor: TerminalColors.background,
      foregroundColor: TerminalColors.ink,
      elevation: 0,
      centerTitle: false,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: TerminalColors.accent,
        foregroundColor: TerminalColors.accentForeground,
        minimumSize: minButtonSize,
        textStyle: buttonTextStyle,
        shape: buttonShape,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: TerminalColors.ink,
        side: const BorderSide(color: TerminalColors.border, width: 1.5),
        minimumSize: minButtonSize,
        textStyle: buttonTextStyle,
        shape: buttonShape,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: TerminalColors.muted,
        textStyle: buttonTextStyle.copyWith(fontWeight: FontWeight.w600),
      ),
    ),
    cardTheme: CardThemeData(
      color: TerminalColors.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: const BorderSide(color: TerminalColors.border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: TerminalColors.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 20),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: TerminalColors.border, width: 1.5),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: TerminalColors.border, width: 1.5),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: TerminalColors.accent, width: 2),
      ),
    ),
    dividerColor: TerminalColors.border,
    dividerTheme: const DividerThemeData(color: TerminalColors.border),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: TerminalColors.accent,
    ),
  );
}
