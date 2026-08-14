// Séquence partagée de téléversement direct d'une photo de prestation
// (ADR-0005) : (1) URL signée via le BFF, (2) `PUT` direct navigateur →
// stockage objet, (3) attachement à la galerie via le BFF. Utilisé par
// `ServicePhotoGallery` (ajout immédiat, édition) et `ServiceForm` (ajout
// différé après création — la clé n'existe qu'une fois la prestation créée).
// Aucun secret journalisé ; le binaire ne transite jamais par l'API/BFF.

import type { ServicePhoto } from "@/src/domain/service/service";

interface UploadUrlPayload {
  upload?: {
    url: string;
    method: string;
    headers: Record<string, string>;
    objectKey: string;
  };
}

interface AddPhotoPayload {
  service?: { photos: ServicePhoto[] };
}

export type UploadServicePhotoResult =
  | { ok: true; photos: ServicePhoto[] }
  | { ok: false; reason: "invalid" | "conflict" | "network" };

export async function uploadServicePhoto(
  salonId: string,
  serviceId: string,
  file: File,
): Promise<UploadServicePhotoResult> {
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
      return { ok: false, reason: "invalid" };
    }

    const { upload } = uploadUrlBody;
    const putResponse = await fetch(upload.url, {
      method: upload.method,
      headers: upload.headers,
      body: file,
    });
    if (!putResponse.ok) {
      return { ok: false, reason: "network" };
    }

    const addResponse = await fetch(
      `/api/salons/${encodeURIComponent(salonId)}/services/${encodeURIComponent(serviceId)}/photos`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objectKey: upload.objectKey }),
      },
    );
    const addBody = (await addResponse.json().catch(() => ({}))) as AddPhotoPayload;
    if (!addResponse.ok || !addBody.service) {
      return { ok: false, reason: addResponse.status === 409 ? "conflict" : "invalid" };
    }
    return { ok: true, photos: addBody.service.photos };
  } catch {
    return { ok: false, reason: "network" };
  }
}
