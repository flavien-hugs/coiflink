// Adapter data (sortant) : accès HTTP au catalogue de salons (#18).
//
// Implémente le port `SalonCatalogGateway` sur `GET /catalog/salons` (backend
// public, §8.3). Seul cet adapter connaît `http` et le format JSON du fil : il
// mappe JSON → `SalonSummary` et retraduit tout échec en `SalonCatalogException`
// (jamais de détail de transport ne remonte au domaine).
//
// Sécurité (spec §Security 5/7) : cet adapter ne **journalise jamais** d'URL
// signée (`logo_url` est un secret porteur), de termes de recherche ni de PII.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/ports/salon_catalog_gateway.dart';
import '../../domain/salon/opening_hours.dart';
import '../../domain/salon/salon_detail.dart';
import '../../domain/salon/salon_service.dart';
import '../../domain/salon/salon_summary.dart';
import 'api_config.dart';

class HttpSalonCatalogGateway implements SalonCatalogGateway {
  HttpSalonCatalogGateway({required this.config, http.Client? client})
      : _client = client ?? http.Client();

  final ApiConfig config;
  final http.Client _client;

  static const String _path = '/catalog/salons';

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) async {
    final uri = config.resolve(_path, queryParameters: _queryParams(query));

    final http.Response response;
    try {
      response = await _client.get(uri);
    } catch (_) {
      // Panne réseau : message générique, jamais l'URL (peut contenir le terme
      // de recherche) ni le détail de l'exception de transport.
      throw const SalonCatalogException('Impossible de joindre le serveur.');
    }

    if (response.statusCode != 200) {
      throw SalonCatalogException(
        'Le serveur a répondu avec le statut ${response.statusCode}.',
      );
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return _pageFromJson(body);
    } catch (_) {
      throw const SalonCatalogException('Réponse du serveur illisible.');
    }
  }

  @override
  Future<SalonDetail> getSalon(String id) async {
    final uri = config.resolve('$_path/$id');

    final http.Response response;
    try {
      response = await _client.get(uri);
    } catch (_) {
      // Panne réseau : message générique, jamais l'URL ni le détail de transport.
      throw const SalonCatalogException('Impossible de joindre le serveur.');
    }

    if (response.statusCode == 404) {
      // §8.3 : salon inexistant ou non `ACTIVE` — état « introuvable » dédié.
      throw const SalonNotFoundException();
    }
    if (response.statusCode != 200) {
      throw SalonCatalogException(
        'Le serveur a répondu avec le statut ${response.statusCode}.',
      );
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return _detailFromJson(body);
    } catch (_) {
      throw const SalonCatalogException('Réponse du serveur illisible.');
    }
  }

  Map<String, String> _queryParams(SalonSearchQuery query) {
    return <String, String>{
      if (query.text != null) 'q': query.text!,
      if (query.city != null) 'city': query.city!,
      if (query.commune != null) 'commune': query.commune!,
      'limit': query.limit.toString(),
      'offset': query.offset.toString(),
    };
  }

  static SalonPage _pageFromJson(Map<String, dynamic> json) {
    final rawItems = (json['items'] as List<dynamic>? ?? const <dynamic>[]);
    final items = rawItems
        .map((item) => _summaryFromJson(item as Map<String, dynamic>))
        .toList(growable: false);
    return SalonPage(
      items: items,
      total: (json['total'] as num?)?.toInt() ?? items.length,
      limit: (json['limit'] as num?)?.toInt() ?? catalogLimitDefault,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }

  static SalonSummary _summaryFromJson(Map<String, dynamic> json) {
    return SalonSummary(
      id: json['id'] as String,
      name: json['name'] as String,
      isBookable: json['is_bookable'] as bool? ?? false,
      description: json['description'] as String?,
      address: json['address'] as String?,
      city: json['city'] as String?,
      commune: json['commune'] as String?,
      latitude: (json['latitude'] as num?)?.toDouble(),
      longitude: (json['longitude'] as num?)?.toDouble(),
      logoUrl: json['logo_url'] as String?,
    );
  }

  static SalonDetail _detailFromJson(Map<String, dynamic> json) {
    final rawServices =
        (json['services'] as List<dynamic>? ?? const <dynamic>[]);
    final rawPhotos = (json['photos'] as List<dynamic>? ?? const <dynamic>[]);
    return SalonDetail(
      id: json['id'] as String,
      name: json['name'] as String,
      isBookable: json['is_bookable'] as bool? ?? false,
      description: json['description'] as String?,
      phone: json['phone'] as String?,
      address: json['address'] as String?,
      city: json['city'] as String?,
      commune: json['commune'] as String?,
      latitude: (json['latitude'] as num?)?.toDouble(),
      longitude: (json['longitude'] as num?)?.toDouble(),
      logoUrl: json['logo_url'] as String?,
      photos: rawPhotos
          .map((p) => _photoFromJson(p as Map<String, dynamic>))
          .toList(growable: false),
      openingHours: _openingHoursFromJson(
        json['opening_hours'] as Map<String, dynamic>?,
      ),
      services: rawServices
          .map((s) => _serviceFromJson(s as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  static SalonPhoto _photoFromJson(Map<String, dynamic> json) {
    return SalonPhoto(
      id: json['id'] as String,
      url: json['url'] as String?,
    );
  }

  static SalonService _serviceFromJson(Map<String, dynamic> json) {
    // `price` arrive en chaîne décimale (« 5000.00 ») ; on tolère aussi un nombre.
    return SalonService(
      id: json['id'] as String,
      name: json['name'] as String,
      description: json['description'] as String?,
      price: json['price']?.toString(),
      durationMinutes: (json['duration_minutes'] as num?)?.toInt(),
      category: json['category'] as String?,
    );
  }

  static SalonOpeningHours? _openingHoursFromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    final rawWeekly = (json['weekly'] as Map<String, dynamic>? ?? const {});
    final weekly = <String, List<OpeningInterval>>{};
    rawWeekly.forEach((day, intervals) {
      weekly[day] = _intervalsFromJson(intervals as List<dynamic>?);
    });
    final rawExceptions =
        (json['exceptions'] as List<dynamic>? ?? const <dynamic>[]);
    final exceptions = rawExceptions
        .map((e) => _exceptionFromJson(e as Map<String, dynamic>))
        .toList(growable: false);
    return SalonOpeningHours(
      timezone: json['timezone'] as String? ?? '',
      weekly: weekly,
      exceptions: exceptions,
    );
  }

  static List<OpeningInterval> _intervalsFromJson(List<dynamic>? raw) {
    if (raw == null) return const <OpeningInterval>[];
    return raw
        .map((i) => i as Map<String, dynamic>)
        .map((i) => OpeningInterval(
              start: i['start'] as String,
              end: i['end'] as String,
            ))
        .toList(growable: false);
  }

  static OpeningException _exceptionFromJson(Map<String, dynamic> json) {
    return OpeningException(
      date: json['date'] as String,
      closed: json['closed'] as bool? ?? false,
      intervals: _intervalsFromJson(json['intervals'] as List<dynamic>?),
    );
  }
}
