"use client";

// Sélecteur + téléverseur d'illustration de prestation — adapter UI (hexagonal,
// ADR-0008). Le binaire ne transite **jamais** par l'API/BFF (ADR-0005) : ce
// composant (1) demande une URL signée au Route Handler BFF
// `/api/salons/{id}/services/media/upload-url`, (2) téléverse le fichier
// **directement** navigateur → stockage objet avec cette URL, puis (3) prévient
// le parent (`onChange`) de la clé d'objet obtenue — le parent l'attache à la
// prestation (création **ou** modification) via `ServiceGateway.attachImage`
// une fois le formulaire général soumis. Ce composant ne mute jamais la
// prestation lui-même : il ne connaît que « choisir → téléverser → prévisualiser ».
//
// Le téléversement direct exige que le bucket autorise l'origine du dashboard
// (CORS, configuration d'infrastructure — voir web-dashboard/README.md).

import { useEffect, useRef, useState } from "react";

import { ImageIcon, TrashIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { isAllowedServiceImageType } from "@/src/domain/service/service";

interface UploadUrlPayload {
  upload?: {
    url: string;
    method: string;
    headers: Record<string, string>;
    objectKey: string;
  };
  error?: string;
}

export interface ServiceImageUploadProps {
  salonId: string;
  // URL signée de l'illustration déjà attachée (mode édition), ou `null`.
  initialImageUrl?: string | null;
  // Prévient le parent de la clé obtenue après téléversement réussi, ou `null`
  // si l'illustration est retirée. Le parent l'attache à la soumission.
  onChange: (objectKey: string | null) => void;
}

export function ServiceImageUpload({
  salonId,
  initialImageUrl = null,
  onChange,
}: ServiceImageUploadProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(initialImageUrl);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const localBlobUrlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (localBlobUrlRef.current) {
        URL.revokeObjectURL(localBlobUrlRef.current);
      }
    };
  }, []);

  async function onFileSelected(file: File) {
    setError(null);

    if (!isAllowedServiceImageType(file.type)) {
      setError("Format d'image non pris en charge (PNG, JPEG ou WEBP uniquement).");
      return;
    }

    setPending(true);
    try {
      const uploadUrlResponse = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/services/media/upload-url`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ contentType: file.type }),
        },
      );
      const uploadUrlBody = (await uploadUrlResponse
        .json()
        .catch(() => ({}))) as UploadUrlPayload;
      if (!uploadUrlResponse.ok || !uploadUrlBody.upload) {
        setError("Impossible de préparer le téléversement. Veuillez réessayer.");
        return;
      }

      const { upload } = uploadUrlBody;
      const putResponse = await fetch(upload.url, {
        method: upload.method,
        headers: upload.headers,
        body: file,
      });
      if (!putResponse.ok) {
        setError("Le téléversement de l'image a échoué. Veuillez réessayer.");
        return;
      }

      if (localBlobUrlRef.current) {
        URL.revokeObjectURL(localBlobUrlRef.current);
      }
      const localUrl = URL.createObjectURL(file);
      localBlobUrlRef.current = localUrl;
      setPreviewUrl(localUrl);
      onChange(upload.objectKey);
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPending(false);
    }
  }

  function onRemove() {
    if (localBlobUrlRef.current) {
      URL.revokeObjectURL(localBlobUrlRef.current);
      localBlobUrlRef.current = null;
    }
    setPreviewUrl(null);
    setError(null);
    onChange(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-4">
        <div className="flex size-20 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border bg-background">
          {previewUrl ? (
            // Aperçu d'un blob local ou d'une URL signée à durée limitée : jamais optimisable par next/image.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={previewUrl}
              alt="Illustration de la prestation"
              className="size-full object-cover"
            />
          ) : (
            <ImageIcon className="size-6 text-muted" />
          )}
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-foreground transition hover:border-accent/40 disabled:cursor-default disabled:opacity-60"
              onClick={() => inputRef.current?.click()}
              disabled={pending}
            >
              <ImageIcon className="shrink-0" />
              {pending
                ? "Téléversement…"
                : previewUrl
                  ? "Changer l'image"
                  : "Choisir une image"}
            </button>
            {previewUrl ? (
              <button
                type="button"
                className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-muted hover:text-danger disabled:opacity-60"
                onClick={onRemove}
                disabled={pending}
              >
                <TrashIcon className="shrink-0" />
                Retirer
              </button>
            ) : null}
          </div>
          <p className="text-xs text-muted">PNG, JPEG ou WEBP.</p>
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void onFileSelected(file);
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
