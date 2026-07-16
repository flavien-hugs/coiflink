"use client";

// Formulaire de prestation (ajout **ou** édition) — adapter UI (hexagonal,
// ADR-0008). Valide **côté client** (parité domaine, retour immédiat) puis poste
// vers le Route Handler BFF `/api/salons/{id}/services` (POST) ou
// `/api/salons/{id}/services/{serviceId}` (PUT), qui proxifie le backend avec le
// jeton du cookie httpOnly. En cas de succès, rafraîchit la page. Messages
// génériques ; aucune PII journalisée. Le backend reste l'autorité (#17).

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { validateService, type Service } from "@/src/domain/service/service";

const INPUT_CLASS =
  "rounded-lg border border-border bg-transparent px-3 py-2.5 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface ServiceFormProps {
  salonId: string;
  // Prestation à éditer ; absente pour une création.
  service?: Service;
  // Fermer le formulaire (mode édition) sans enregistrer.
  onCancel?: () => void;
}

export function ServiceForm({ salonId, service, onCancel }: ServiceFormProps) {
  const router = useRouter();
  const editing = service != null;
  const [name, setName] = useState(service?.name ?? "");
  const [price, setPrice] = useState(service?.price ?? "");
  const [durationMinutes, setDurationMinutes] = useState(
    service ? String(service.durationMinutes) : "",
  );
  const [description, setDescription] = useState(service?.description ?? "");
  const [category, setCategory] = useState(service?.category ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const validated = validateService({
      name,
      price,
      durationMinutes,
      description,
      category,
    });
    if (!validated.ok) {
      switch (validated.reason) {
        case "invalid-name":
          setError("Le nom de la prestation est requis (255 caractères max).");
          break;
        case "invalid-price":
          setError("Le prix est requis : un montant positif, au plus deux décimales.");
          break;
        case "invalid-duration":
          setError("La durée est requise : un nombre entier de minutes, au plus 24 h.");
          break;
        default:
          setError("La catégorie ne doit pas dépasser 128 caractères.");
      }
      return;
    }

    setPending(true);
    try {
      const url = editing
        ? `/api/salons/${encodeURIComponent(salonId)}/services/${encodeURIComponent(service.id)}`
        : `/api/salons/${encodeURIComponent(salonId)}/services`;
      const response = await fetch(url, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(validated.value),
      });

      if (response.ok) {
        if (!editing) {
          setName("");
          setPrice("");
          setDurationMinutes("");
          setDescription("");
          setCategory("");
        }
        onCancel?.();
        router.refresh();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Prestation introuvable.");
      } else if (response.status === 422 || response.status === 400) {
        setError("Prestation invalide.");
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
        <span>Nom de la prestation *</span>
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
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <span>Prix (FCFA) *</span>
          <input
            type="text"
            inputMode="decimal"
            name="price"
            className={INPUT_CLASS}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="5000.00"
            required
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <span>Durée (minutes) *</span>
          <input
            type="number"
            inputMode="numeric"
            name="durationMinutes"
            className={INPUT_CLASS}
            value={durationMinutes}
            onChange={(e) => setDurationMinutes(e.target.value)}
            min={1}
            max={1440}
            placeholder="30"
            required
          />
        </label>
      </div>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <span>Catégorie</span>
        <input
          type="text"
          name="category"
          className={INPUT_CLASS}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          maxLength={128}
          placeholder="Coupe"
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <span>Description</span>
        <textarea
          name="description"
          className={INPUT_CLASS}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
      </label>
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
          className="inline-flex cursor-pointer items-center justify-center rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          disabled={pending}
        >
          {pending
            ? "Enregistrement…"
            : editing
              ? "Enregistrer les modifications"
              : "Ajouter la prestation"}
        </button>
        {editing && onCancel ? (
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
