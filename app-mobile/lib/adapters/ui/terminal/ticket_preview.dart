// Aperçu à l'écran du ticket de passage (US-007, #159 — chemin confirmé par #160).
//
// Rend à l'écran, en style « reçu » monospace à bordure pointillée, le **même**
// contenu que celui qui part vers l'imprimante (nom du salon, numéro formaté
// « N° 014 », date/heure, une ligne par prestation), **indépendamment** du succès de
// l'impression : le client voit toujours son numéro, même si le papier ne sort pas.
//
// #160 pourra affiner ce widget quand il livrera le formateur ESC/POS ; le chemin
// `adapters/ui/terminal/ticket_preview.dart` est celui attendu par les deux specs.

import 'package:flutter/material.dart';

import '../../../domain/ticket/ticket_print_payload.dart';
import 'terminal_theme.dart';

String _two(int value) => value.toString().padLeft(2, '0');

/// Formate le numéro de passage pour l'affichage : « N° 014 » (zéro-padding à 3
/// chiffres), miroir du formatage papier. Le domaine reste un **entier brut** (#157).
String formatTerminalTicketNumber(int ticketNumber) {
  return 'N° ${ticketNumber.toString().padLeft(3, '0')}';
}

/// Formate l'heure d'émission en `HH:MM` (heure locale déjà résolue).
String formatTerminalTime(DateTime issuedAt) {
  return '${_two(issuedAt.hour)}:${_two(issuedAt.minute)}';
}

/// Formate la date/heure d'émission en `JJ/MM/AAAA HH:MM` (heure locale déjà résolue).
String formatTerminalIssuedAt(DateTime issuedAt) {
  final date = '${_two(issuedAt.day)}/${_two(issuedAt.month)}/${issuedAt.year}';
  return '$date ${formatTerminalTime(issuedAt)}';
}

class TicketPreview extends StatelessWidget {
  const TicketPreview({super.key, required this.payload});

  final TicketPrintPayload payload;

  @override
  Widget build(BuildContext context) {
    const monospace = TextStyle(
      fontFamily: 'monospace',
      fontSize: 15,
      color: TerminalColors.ink,
    );
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 300),
      child: CustomPaint(
        painter: const _DashedRectPainter(color: TerminalColors.border),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text(
                payload.salonName.toUpperCase(),
                textAlign: TextAlign.center,
                style: monospace.copyWith(
                  fontWeight: FontWeight.bold,
                  letterSpacing: 0.6,
                ),
              ),
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 10),
                child: _DashedDivider(),
              ),
              _receiptLine('N°', formatTerminalTicketNumber(payload.ticketNumber)),
              _receiptLine('Date', formatTerminalIssuedAt(payload.issuedAt)),
              for (final serviceName in payload.serviceNames)
                _receiptLine('Prestation', serviceName),
            ],
          ),
        ),
      ),
    );
  }

  Widget _receiptLine(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: <Widget>[
          Text(
            label,
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 12,
              color: TerminalColors.muted,
            ),
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: TerminalColors.ink,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DashedDivider extends StatelessWidget {
  const _DashedDivider();

  @override
  Widget build(BuildContext context) {
    return const SizedBox(
      height: 1,
      child: CustomPaint(painter: _DashedLinePainter(color: TerminalColors.border)),
    );
  }
}

/// Peint une bordure rectangulaire arrondie **réellement pointillée** (pas une
/// approximation via des `Container` empilés) — style reçu de caisse.
class _DashedRectPainter extends CustomPainter {
  const _DashedRectPainter({required this.color});

  final Color color;

  static const double _strokeWidth = 1.5;
  static const double _radius = 16;

  @override
  void paint(Canvas canvas, Size size) {
    final rrect = RRect.fromRectAndRadius(
      Rect.fromLTWH(
        _strokeWidth / 2,
        _strokeWidth / 2,
        size.width - _strokeWidth,
        size.height - _strokeWidth,
      ),
      const Radius.circular(_radius),
    );
    _paintDashedPath(canvas, Path()..addRRect(rrect), color, _strokeWidth, 5, 4);
  }

  @override
  bool shouldRepaint(covariant _DashedRectPainter oldDelegate) =>
      color != oldDelegate.color;
}

class _DashedLinePainter extends CustomPainter {
  const _DashedLinePainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(0, size.height / 2)
      ..lineTo(size.width, size.height / 2);
    _paintDashedPath(canvas, path, color, 1.5, 5, 4);
  }

  @override
  bool shouldRepaint(covariant _DashedLinePainter oldDelegate) =>
      color != oldDelegate.color;
}

void _paintDashedPath(
  Canvas canvas,
  Path path,
  Color color,
  double strokeWidth,
  double dashWidth,
  double gapWidth,
) {
  final paint = Paint()
    ..color = color
    ..style = PaintingStyle.stroke
    ..strokeWidth = strokeWidth;
  for (final metric in path.computeMetrics()) {
    var distance = 0.0;
    while (distance < metric.length) {
      final next = distance + dashWidth;
      canvas.drawPath(
        metric.extractPath(distance, next.clamp(0, metric.length)),
        paint,
      );
      distance = next + gapWidth;
    }
  }
}
