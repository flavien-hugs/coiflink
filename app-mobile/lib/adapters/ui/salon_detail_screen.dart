// Écran UI : fiche de détail d'un salon (§7.1 / §5.1, #19).
//
// Charge la fiche via le cas d'usage `GetSalonDetail` (injecté) et affiche :
// en-tête (logo, nom, localisation, badge `isBookable`), horaires, prestations +
// prix, téléphone, et le **point d'entrée réservation** — un bouton « Réserver »
// dérivé de `isBookable`. Quand un lanceur de réservation est câblé (#22), le
// bouton ouvre réellement le tunnel ; sinon il reste une affordance honnête
// (désactivé « Bientôt disponible », ou message « bientôt disponible »). États :
// chargement / introuvable / erreur.

import 'package:flutter/material.dart';

import '../../application/ports/salon_catalog_gateway.dart';
import '../../application/use_cases/get_salon_detail.dart';
import '../../domain/salon/salon_detail.dart';
import 'widgets/opening_hours_view.dart';
import 'widgets/salon_photo_gallery.dart';
import 'widgets/service_list_tile.dart';

/// Ouvre le tunnel de réservation pour un salon `ACTIVE` réservable (#22).
///
/// Câblé par le composition root (`app.dart`) ; `null` ⇒ le point d'entrée reste
/// inerte (message honnête), ce qui préserve les écrans/tests sans réservation.
typedef BookingLauncher = void Function(BuildContext context, SalonDetail salon);

class SalonDetailScreen extends StatefulWidget {
  const SalonDetailScreen({
    super.key,
    required this.salonId,
    required this.getSalonDetail,
    this.salonName,
    this.onBook,
  });

  final String salonId;
  final GetSalonDetail getSalonDetail;

  /// Nom déjà connu (depuis la liste) — affiché dans la barre pendant le
  /// chargement pour éviter un titre vide (facultatif).
  final String? salonName;

  /// Lanceur du tunnel de réservation (#22). `null` ⇒ point d'entrée inerte.
  final BookingLauncher? onBook;

  @override
  State<SalonDetailScreen> createState() => _SalonDetailScreenState();
}

class _SalonDetailScreenState extends State<SalonDetailScreen> {
  bool _loading = true;
  SalonDetail? _salon;
  String? _error;
  bool _notFound = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _notFound = false;
    });
    try {
      final salon = await widget.getSalonDetail.call(widget.salonId);
      if (!mounted) return;
      setState(() {
        _salon = salon;
        _loading = false;
      });
    } on SalonNotFoundException {
      if (!mounted) return;
      setState(() {
        _notFound = true;
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_salon?.name ?? widget.salonName ?? 'Salon')),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_notFound) {
      return const _NotFoundState();
    }
    if (_error != null) {
      return _ErrorState(message: _error!, onRetry: _load);
    }
    return _SalonDetailBody(salon: _salon!, onBook: widget.onBook);
  }
}

class _SalonDetailBody extends StatelessWidget {
  const _SalonDetailBody({required this.salon, this.onBook});

  final SalonDetail salon;
  final BookingLauncher? onBook;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final location = salon.locationLabel;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        _Header(salon: salon),
        const SizedBox(height: 16),
        if (salon.photos.isNotEmpty) ...[
          SalonPhotoGallery(photos: salon.photos),
          const SizedBox(height: 16),
        ],
        if (salon.description != null && salon.description!.trim().isNotEmpty) ...[
          Text(salon.description!.trim(), style: theme.textTheme.bodyMedium),
          const SizedBox(height: 16),
        ],
        if (salon.address != null && salon.address!.trim().isNotEmpty) ...[
          _IconLine(icon: Icons.place_outlined, text: salon.address!.trim()),
        ],
        if (location.isNotEmpty)
          _IconLine(icon: Icons.location_city_outlined, text: location),
        if (salon.phone != null && salon.phone!.trim().isNotEmpty)
          _IconLine(icon: Icons.phone_outlined, text: salon.phone!.trim()),
        const SizedBox(height: 24),
        _SectionTitle('Horaires'),
        OpeningHoursView(openingHours: salon.openingHours),
        const SizedBox(height: 24),
        _SectionTitle('Prestations'),
        if (salon.services.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text('Aucune prestation'),
          )
        else
          for (final service in salon.services)
            ServiceListTile(service: service),
        const SizedBox(height: 24),
        _BookingCta(salon: salon, onBook: onBook),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.salon});

  final SalonDetail salon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        _Logo(url: salon.logoUrl),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(salon.name, style: theme.textTheme.titleLarge),
              const SizedBox(height: 8),
              _BookableBadge(isBookable: salon.isBookable),
            ],
          ),
        ),
      ],
    );
  }
}

class _Logo extends StatelessWidget {
  const _Logo({required this.url});

  final String? url;

  @override
  Widget build(BuildContext context) {
    if (url == null) {
      return const CircleAvatar(radius: 32, child: Icon(Icons.store));
    }
    return CircleAvatar(
      radius: 32,
      backgroundImage: NetworkImage(url!),
      onBackgroundImageError: (_, _) {},
    );
  }
}

class _BookableBadge extends StatelessWidget {
  const _BookableBadge({required this.isBookable});

  final bool isBookable;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = isBookable ? 'Réservable' : 'Bientôt disponible';
    final color = isBookable ? Colors.green : theme.disabledColor;

    return Chip(
      label: Text(label),
      labelStyle: theme.textTheme.labelSmall,
      backgroundColor: color.withValues(alpha: 0.12),
      side: BorderSide(color: color),
      visualDensity: VisualDensity.compact,
    );
  }
}

/// Point d'entrée de la réservation (#22).
///
/// - `isBookable == false` (§8.3) → bouton désactivé « Bientôt disponible ».
/// - `isBookable == true` **et** un lanceur câblé → ouvre le tunnel (#22).
/// - `isBookable == true` sans lanceur → affordance honnête (message), pour les
///   contextes/tests sans réservation.
class _BookingCta extends StatelessWidget {
  const _BookingCta({required this.salon, this.onBook});

  final SalonDetail salon;
  final BookingLauncher? onBook;

  @override
  Widget build(BuildContext context) {
    if (!salon.isBookable) {
      return const SizedBox(
        width: double.infinity,
        child: FilledButton(
          onPressed: null,
          child: Text('Bientôt disponible'),
        ),
      );
    }
    return SizedBox(
      width: double.infinity,
      child: FilledButton.icon(
        icon: const Icon(Icons.event_available),
        label: const Text('Réserver'),
        onPressed: () {
          final launcher = onBook;
          if (launcher == null) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('Réservation bientôt disponible.'),
              ),
            );
            return;
          }
          launcher(context, salon);
        },
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(text, style: Theme.of(context).textTheme.titleMedium),
    );
  }
}

class _IconLine extends StatelessWidget {
  const _IconLine({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}

class _NotFoundState extends StatelessWidget {
  const _NotFoundState();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Text(
              'Ce salon est introuvable.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Retour à la liste'),
            ),
          ],
        ),
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
