"use client";

// Galerie de photos d'une prestation — adapter UI (hexagonal, ADR-0008). Le
// binaire ne transite **jamais** par l'API/BFF (ADR-0005) : ce composant (1)
// demande une URL signée au Route Handler BFF
// `/api/salons/{id}/services/media/upload-url`, (2) téléverse le fichier
// **directement** navigateur → stockage objet avec cette URL, puis (3) ajoute
// la clé à la galerie.
//
// Deux modes, selon que la prestation existe déjà :
// - **édition** (`serviceId` connu) : ajout/retrait **immédiats**, chaque
//   action appelle le backend tout de suite (miroir `salon_photos`) ;
// - **création** (`serviceId` encore `null`) : l'ajout est **mis en attente**
//   localement (aperçu `URL.createObjectURL`, aucun appel réseau) — l'API
//   `AddServicePhoto` exige un `service_id`, qui n'existe pas encore. Le
//   parent (`ServiceForm`) reçoit les fichiers en attente via
//   `onPendingFilesChange` et les téléverse/attache une fois la prestation
//   créée.
//
// Le téléversement direct exige que le bucket autorise l'origine du dashboard
// (CORS, configuration d'infrastructure — voir web-dashboard/README.md).

import { useEffect, useRef, useState } from "react";

import { ImageIcon, PlusIcon, TrashIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { uploadServicePhoto } from "@/src/adapters/ui/upload-service-photo";
import {
  isAllowedServiceImageType,
  SERVICE_PHOTO_MAX_COUNT,
  type ServicePhoto,
} from "@/src/domain/service/service";

interface PendingPhoto {
  file: File;
  previewUrl: string;
}

export interface ServicePhotoGalleryProps {
  salonId: string;
  // `null` tant que la prestation n'existe pas encore (création).
  serviceId: string | null;
  // Galerie déjà persistée (mode édition), ignorée en création.
  initialPhotos?: ServicePhoto[];
  // Prévient le parent des fichiers en attente (création uniquement) — le
  // parent les téléverse/attache séquentiellement une fois la prestation créée.
  onPendingFilesChange?: (files: File[]) => void;
}

export function ServicePhotoGallery({
  salonId,
  serviceId,
  initialPhotos = [],
  onPendingFilesChange,
}: ServicePhotoGalleryProps) {
  const [photos, setPhotos] = useState<ServicePhoto[]>(initialPhotos);
  const [pending, setPending] = useState<PendingPhoto[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Miroir de `pending` lu par le nettoyage au démontage (ci-dessous) : un
  // effet à dépendances vides capturerait `pending` tel qu'il était au premier
  // rendu (toujours []) et ne révoquerait jamais les blobs créés ensuite.
  const pendingRef = useRef<PendingPhoto[]>(pending);

  useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);

  // Nettoyage des aperçus locaux (blobs) au démontage — évite une fuite mémoire.
  useEffect(() => {
    return () => {
      pendingRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
  }, []);

  const count = photos.length + pending.length;
  const atLimit = count >= SERVICE_PHOTO_MAX_COUNT;

  async function addExisting(file: File) {
    setBusy(true);
    try {
      const result = await uploadServicePhoto(salonId, serviceId as string, file);
      if (!result.ok) {
        setError(
          result.reason === "conflict"
            ? "Nombre maximal de photos atteint."
            : "Impossible d'ajouter la photo. Veuillez réessayer.",
        );
        return;
      }
      setPhotos(result.photos);
    } finally {
      setBusy(false);
    }
  }

  function addPending(file: File) {
    const previewUrl = URL.createObjectURL(file);
    setPending((prev) => {
      const next = [...prev, { file, previewUrl }];
      onPendingFilesChange?.(next.map((p) => p.file));
      return next;
    });
  }

  function onFileSelected(file: File) {
    setError(null);
    if (!isAllowedServiceImageType(file.type)) {
      setError("Format d'image non pris en charge (PNG, JPEG ou WEBP uniquement).");
      return;
    }
    if (atLimit) {
      setError("Nombre maximal de photos atteint.");
      return;
    }
    if (serviceId) {
      void addExisting(file);
    } else {
      addPending(file);
    }
  }

  async function removeExisting(photoId: string) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/services/${encodeURIComponent(serviceId as string)}/photos/${encodeURIComponent(photoId)}`,
        { method: "DELETE" },
      );
      if (!response.ok && response.status !== 204) {
        setError("Impossible de retirer la photo. Veuillez réessayer.");
        return;
      }
      setPhotos((prev) => prev.filter((p) => p.id !== photoId));
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setBusy(false);
    }
  }

  function removePending(previewUrl: string) {
    setPending((prev) => {
      const next = prev.filter((p) => p.previewUrl !== previewUrl);
      onPendingFilesChange?.(next.map((p) => p.file));
      return next;
    });
    URL.revokeObjectURL(previewUrl);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        {photos.map((photo) => (
          <div
            key={photo.id}
            className="group relative size-20 shrink-0 overflow-hidden rounded-xl border border-border bg-background"
          >
            {photo.url ? (
              // Aperçu d'une URL signée à durée limitée : jamais optimisable par next/image.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={photo.url}
                alt="Photo de la prestation"
                className="size-full object-cover"
              />
            ) : (
              <div className="flex size-full items-center justify-center">
                <ImageIcon className="size-6 text-muted" />
              </div>
            )}
            <button
              type="button"
              className="absolute right-1 top-1 inline-flex size-6 cursor-pointer items-center justify-center rounded-full bg-ink/70 text-white opacity-0 transition group-hover:opacity-100 disabled:cursor-default disabled:opacity-60"
              onClick={() => removeExisting(photo.id)}
              disabled={busy}
              aria-label="Retirer la photo"
            >
              <TrashIcon className="size-3.5" />
            </button>
          </div>
        ))}
        {pending.map((p) => (
          <div
            key={p.previewUrl}
            className="group relative size-20 shrink-0 overflow-hidden rounded-xl border border-border bg-background"
          >
            {/* Aperçu local (blob) — pas encore téléversé. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={p.previewUrl}
              alt="Photo en attente d'enregistrement"
              className="size-full object-cover"
            />
            <button
              type="button"
              className="absolute right-1 top-1 inline-flex size-6 cursor-pointer items-center justify-center rounded-full bg-ink/70 text-white opacity-0 transition group-hover:opacity-100"
              onClick={() => removePending(p.previewUrl)}
              aria-label="Retirer la photo"
            >
              <TrashIcon className="size-3.5" />
            </button>
          </div>
        ))}
        <button
          type="button"
          className="flex size-20 shrink-0 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border text-muted transition hover:border-accent/40 hover:text-accent disabled:cursor-default disabled:opacity-60"
          onClick={() => inputRef.current?.click()}
          disabled={busy || atLimit}
        >
          <PlusIcon className="size-5" />
          <span className="text-xs font-medium">{busy ? "…" : "Ajouter"}</span>
        </button>
      </div>
      <p className="text-xs text-muted">
        PNG, JPEG ou WEBP — {count}/{SERVICE_PHOTO_MAX_COUNT} photo{count > 1 ? "s" : ""}.
      </p>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFileSelected(file);
          if (inputRef.current) inputRef.current.value = "";
        }}
      />
      {error ? (
        <p
          className="flex items-center gap-1.5 rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          <XIcon className="shrink-0" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
