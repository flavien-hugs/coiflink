// Widget UI : galerie de photos de la fiche salon (§B, #19).
//
// Présentation pure : bande horizontale défilante de vignettes (URLs signées).
// N'affiche rien si la liste est vide — le logo (affiché séparément dans
// l'en-tête) suffit alors.

import 'package:flutter/material.dart';

import '../../../domain/salon/salon_detail.dart';

class SalonPhotoGallery extends StatelessWidget {
  const SalonPhotoGallery({super.key, required this.photos});

  final List<SalonPhoto> photos;

  @override
  Widget build(BuildContext context) {
    if (photos.isEmpty) {
      return const SizedBox.shrink();
    }
    return SizedBox(
      height: 96,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: photos.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (context, index) => _PhotoThumbnail(photo: photos[index]),
      ),
    );
  }
}

class _PhotoThumbnail extends StatelessWidget {
  const _PhotoThumbnail({required this.photo});

  final SalonPhoto photo;

  @override
  Widget build(BuildContext context) {
    final url = photo.url;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        width: 96,
        height: 96,
        child: url == null
            ? ColoredBox(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                child: const Icon(Icons.image_not_supported_outlined),
              )
            : Image.network(
                url,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => ColoredBox(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  child: const Icon(Icons.image_not_supported_outlined),
                ),
              ),
      ),
    );
  }
}
