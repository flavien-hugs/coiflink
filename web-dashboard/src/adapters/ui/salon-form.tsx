"use client";

// Formulaire de salon (création **ou** modification) — adapter UI (hexagonal,
// ADR-0008). Poste vers le Route Handler BFF `POST /api/salons` (création) ou
// `PUT /api/salons/{id}` (modification, journalisée §11.4 côté backend). En
// cas de succès, rafraîchit la page. Messages génériques ; aucune PII journalisée.

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FieldLabel } from "@/src/adapters/ui/field-label";
import type { Salon } from "@/src/domain/salon/salon";

const INPUT_CLASS =
  "rounded-lg border border-border bg-surface px-3 py-2.5 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface SalonFormProps {
  // Salon à modifier ; absent pour une création.
  salon?: Salon;
  // Fermer le panneau après un enregistrement réussi.
  onSaved?: () => void;
  // Fermer le formulaire (mode édition) sans enregistrer.
  onCancel?: () => void;
}

function parseCoordinate(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

export function SalonForm({ salon, onCancel, onSaved }: SalonFormProps) {
  const router = useRouter();
  const editing = salon != null;
  const [name, setName] = useState(salon?.name ?? "");
  const [description, setDescription] = useState(salon?.description ?? "");
  const [phone, setPhone] = useState(salon?.phone ?? "");
  const [address, setAddress] = useState(salon?.address ?? "");
  const [city, setCity] = useState(salon?.city ?? "");
  const [commune, setCommune] = useState(salon?.commune ?? "");
  const [latitude, setLatitude] = useState(
    salon?.latitude != null ? String(salon.latitude) : "",
  );
  const [longitude, setLongitude] = useState(
    salon?.longitude != null ? String(salon.longitude) : "",
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (name.trim().length === 0) {
      setError("Le nom du salon est requis.");
      return;
    }
    const lat = parseCoordinate(latitude);
    const lon = parseCoordinate(longitude);
    if (Number.isNaN(lat) || Number.isNaN(lon) || (lat == null) !== (lon == null)) {
      setError("Latitude et longitude doivent être fournies ensemble et valides.");
      return;
    }

    setPending(true);
    try {
      const url = editing ? `/api/salons/${encodeURIComponent(salon.id)}` : "/api/salons";
      const response = await fetch(url, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description,
          phone,
          address,
          city,
          commune,
          latitude: lat,
          longitude: lon,
        }),
      });

      if (response.ok) {
        router.refresh();
        onSaved?.();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Salon introuvable.");
      } else if (response.status === 422 || response.status === 400) {
        setError("Informations du salon invalides.");
      } else if (response.status === 401) {
        setError("Votre session a expiré. Veuillez vous reconnecter.");
      } else {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel required>Nom du salon</FieldLabel>
        <input
          type="text"
          name="name"
          className={INPUT_CLASS}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={255}
          required
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel optional>Description</FieldLabel>
        <textarea
          name="description"
          className={INPUT_CLASS}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel optional>Téléphone</FieldLabel>
        <input
          type="tel"
          name="phone"
          className={INPUT_CLASS}
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel optional>Adresse</FieldLabel>
        <input
          type="text"
          name="address"
          className={INPUT_CLASS}
          value={address}
          onChange={(e) => setAddress(e.target.value)}
        />
      </label>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Ville</FieldLabel>
          <input
            type="text"
            name="city"
            className={INPUT_CLASS}
            value={city}
            onChange={(e) => setCity(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Commune</FieldLabel>
          <input
            type="text"
            name="commune"
            className={INPUT_CLASS}
            value={commune}
            onChange={(e) => setCommune(e.target.value)}
          />
        </label>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Latitude</FieldLabel>
          <input
            type="text"
            inputMode="decimal"
            name="latitude"
            className={INPUT_CLASS}
            value={latitude}
            onChange={(e) => setLatitude(e.target.value)}
            placeholder="5.359952"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Longitude</FieldLabel>
          <input
            type="text"
            inputMode="decimal"
            name="longitude"
            className={INPUT_CLASS}
            value={longitude}
            onChange={(e) => setLongitude(e.target.value)}
            placeholder="-3.996643"
          />
        </label>
      </div>
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="mt-1 inline-flex cursor-pointer items-center justify-center rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          disabled={pending}
        >
          {pending
            ? "Enregistrement…"
            : editing
              ? "Enregistrer les modifications"
              : "Créer le salon"}
        </button>
        {onCancel ? (
          <button
            type="button"
            className="text-sm font-medium text-muted hover:text-foreground"
            onClick={onCancel}
            disabled={pending}
          >
            Annuler
          </button>
        ) : null}
      </div>
    </form>
  );
}
