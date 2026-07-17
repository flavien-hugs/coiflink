// Écran UI : recherche/liste des salons (§7.1, #18).
//
// Compose le cas d'usage `SearchSalons` (injecté) avec un champ de recherche
// (debounce ~300 ms), un filtre de zone (ville), une liste paginée et les états
// chargement / vide / erreur. Aucune règle métier ni appel HTTP direct : l'écran
// ne connaît que le cas d'usage et le domaine (`SalonSummary`).

import 'dart:async';

import 'package:flutter/material.dart';

import '../../application/ports/salon_catalog_gateway.dart';
import '../../application/use_cases/search_salons.dart';
import '../../domain/salon/salon_summary.dart';
import 'widgets/salon_card.dart';

/// Délai de temporisation entre la dernière frappe et la requête de recherche.
const Duration kSearchDebounce = Duration(milliseconds: 300);

class SalonSearchScreen extends StatefulWidget {
  const SalonSearchScreen({super.key, required this.searchSalons});

  final SearchSalons searchSalons;

  @override
  State<SalonSearchScreen> createState() => _SalonSearchScreenState();
}

class _SalonSearchScreenState extends State<SalonSearchScreen> {
  final TextEditingController _textController = TextEditingController();
  final TextEditingController _cityController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  Timer? _debounce;
  bool _loading = false;
  bool _loadingMore = false;
  String? _error;
  final List<SalonSummary> _salons = <SalonSummary>[];
  int _total = 0;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
    _runSearch();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _textController.dispose();
    _cityController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _onQueryChanged() {
    _debounce?.cancel();
    _debounce = Timer(kSearchDebounce, _runSearch);
  }

  void _onScroll() {
    final threshold = _scrollController.position.maxScrollExtent - 200;
    if (_scrollController.position.pixels >= threshold) {
      _loadMore();
    }
  }

  Future<void> _runSearch() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.searchSalons.call(
        text: _textController.text,
        city: _cityController.text,
      );
      if (!mounted) return;
      setState(() {
        _salons
          ..clear()
          ..addAll(page.items);
        _total = page.total;
        _loading = false;
      });
    } on SalonCatalogException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _loading = false;
      });
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || _loading || _salons.length >= _total) return;
    setState(() => _loadingMore = true);
    try {
      final page = await widget.searchSalons.call(
        text: _textController.text,
        city: _cityController.text,
        offset: _salons.length,
      );
      if (!mounted) return;
      setState(() {
        _salons.addAll(page.items);
        _total = page.total;
        _loadingMore = false;
      });
    } on SalonCatalogException {
      if (!mounted) return;
      setState(() => _loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Rechercher un salon')),
      body: Column(
        children: <Widget>[
          _SearchFilters(
            textController: _textController,
            cityController: _cityController,
            onChanged: _onQueryChanged,
          ),
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _ErrorState(message: _error!, onRetry: _runSearch);
    }
    if (_salons.isEmpty) {
      return const _EmptyState();
    }
    return ListView.builder(
      controller: _scrollController,
      itemCount: _salons.length + (_loadingMore ? 1 : 0),
      itemBuilder: (context, index) {
        if (index >= _salons.length) {
          return const Padding(
            padding: EdgeInsets.all(16),
            child: Center(child: CircularProgressIndicator()),
          );
        }
        return SalonCard(salon: _salons[index]);
      },
    );
  }
}

class _SearchFilters extends StatelessWidget {
  const _SearchFilters({
    required this.textController,
    required this.cityController,
    required this.onChanged,
  });

  final TextEditingController textController;
  final TextEditingController cityController;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: <Widget>[
          TextField(
            controller: textController,
            onChanged: (_) => onChanged(),
            decoration: const InputDecoration(
              labelText: 'Nom du salon',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: cityController,
            onChanged: (_) => onChanged(),
            decoration: const InputDecoration(
              labelText: 'Ville',
              prefixIcon: Icon(Icons.location_city),
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Text('Aucun salon trouvé.', textAlign: TextAlign.center),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: onRetry, child: const Text('Réessayer')),
          ],
        ),
      ),
    );
  }
}
