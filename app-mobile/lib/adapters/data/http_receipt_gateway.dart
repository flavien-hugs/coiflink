// Adapter data (sortant) : lecture des reçus de paiement HTTP (US-5.5, #38 ·
// ADR-0040).
//
// Implémente le port `ReceiptGateway` sur les endpoints d'appartenance livrés
// par #38 : `GET /me/receipts` et `GET /me/receipts/{payment_id}` (en-tête
// `Authorization: Bearer <accessToken>`). Seul cet adapter connaît `http` et le
// format JSON du fil : il mappe JSON → domaine et retraduit tout échec en
// exception **neutre** (jamais de détail de transport au domaine).
//
// Sécurité (§11) : cet adapter ne **journalise jamais** d'URL, de corps, de
// jeton ni de PII.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/ports/receipt_gateway.dart';
import '../../domain/receipt/receipt.dart';
import 'api_config.dart';

class HttpReceiptGateway implements ReceiptGateway {
  HttpReceiptGateway({required this.config, http.Client? client})
      : _client = client ?? http.Client();

  final ApiConfig config;
  final http.Client _client;

  @override
  Future<List<Receipt>> myReceipts({required String accessToken}) async {
    final uri = config.resolve('/me/receipts');

    final http.Response response;
    try {
      response = await _client.get(
        uri,
        headers: <String, String>{'authorization': 'Bearer $accessToken'},
      );
    } catch (_) {
      throw const ReceiptGatewayException('Impossible de joindre le serveur.');
    }

    switch (response.statusCode) {
      case 200:
        break;
      case 401:
        throw const UnauthorizedException();
      default:
        throw const ReceiptGatewayException('Impossible de charger vos reçus.');
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final items = (body['items'] as List<dynamic>? ?? const <dynamic>[]);
      return items
          .map((r) => _receiptFromJson(r as Map<String, dynamic>))
          .toList(growable: false);
    } catch (_) {
      throw const ReceiptGatewayException('Réponse du serveur illisible.');
    }
  }

  @override
  Future<Receipt> receiptDetail({
    required String paymentId,
    required String accessToken,
  }) async {
    final uri = config.resolve('/me/receipts/$paymentId');

    final http.Response response;
    try {
      response = await _client.get(
        uri,
        headers: <String, String>{'authorization': 'Bearer $accessToken'},
      );
    } catch (_) {
      throw const ReceiptGatewayException('Impossible de joindre le serveur.');
    }

    switch (response.statusCode) {
      case 200:
        break;
      case 401:
        throw const UnauthorizedException();
      case 404:
        throw const ReceiptNotFoundException();
      default:
        throw const ReceiptGatewayException('Impossible de charger ce reçu.');
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return _receiptFromJson(body);
    } catch (_) {
      throw const ReceiptGatewayException('Réponse du serveur illisible.');
    }
  }

  static Receipt _receiptFromJson(Map<String, dynamic> json) {
    final rawLines = (json['lines'] as List<dynamic>? ?? const <dynamic>[]);
    return Receipt(
      receiptNumber: json['receipt_number'] as String,
      paymentId: json['payment_id'] as String,
      salonName: json['salon_name'] as String,
      amount: json['amount'] as String,
      currency: json['currency'] as String,
      paymentMethod: json['payment_method'] as String,
      status: json['status'] as String,
      reference: json['reference'] as String?,
      paidAt: DateTime.parse(json['paid_at'] as String),
      lines: rawLines
          .map((l) => _lineFromJson(l as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  static ReceiptLine _lineFromJson(Map<String, dynamic> json) {
    return ReceiptLine(
      serviceName: json['service_name'] as String,
      amount: json['amount'] as String,
    );
  }
}
