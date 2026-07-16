"use client";

// Liste éditable des prestations d'un salon — adapter UI (hexagonal, ADR-0008).
// Affiche actives **et** désactivées (badge « Désactivée », vue gérant #17),
// permet l'édition en ligne (réutilise `ServiceForm`) et la « désactivation »
// (soft-delete via `DELETE …/services/{id}`). Poste vers les Route Handlers BFF
// (jeton du cookie httpOnly). Messages génériques ; le backend reste l'autorité.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ServiceForm } from "@/src/adapters/ui/service-form";
import type { Service } from "@/src/domain/service/service";

function formatPrice(price: string): string {
  const value = Number(price);
  return Number.isFinite(value)
    ? `${value.toLocaleString("fr-FR")} FCFA`
    : `${price} FCFA`;
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export function ServiceList({
  salonId,
  services,
}: {
  salonId: string;
  services: Service[];
}) {
  const router = useRouter();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onDeactivate(service: Service) {
    setError(null);
    setPendingId(service.id);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/services/${encodeURIComponent(service.id)}`,
        { method: "DELETE" },
      );
      if (response.ok || response.status === 204) {
        router.refresh();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Prestation introuvable.");
      } else if (response.status === 401) {
        setError("Votre session a expiré. Veuillez vous reconnecter.");
      } else {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPendingId(null);
    }
  }

  if (services.length === 0) {
    return (
      <p className="text-sm text-muted">
        Aucune prestation pour le moment. Ajoutez-en une pour composer votre catalogue.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      {services.map((service) =>
        editingId === service.id ? (
          <div
            key={service.id}
            className="rounded-xl border border-border bg-surface p-4 shadow-soft"
          >
            <ServiceForm
              salonId={salonId}
              service={service}
              onCancel={() => setEditingId(null)}
            />
          </div>
        ) : (
          <div
            key={service.id}
            className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4 sm:flex-row sm:items-start sm:justify-between"
          >
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{service.name}</span>
                {service.category ? (
                  <span className="rounded-full bg-foreground/5 px-2 py-0.5 text-xs font-medium text-muted">
                    {service.category}
                  </span>
                ) : null}
                {!service.isActive ? (
                  <span className="rounded-full bg-danger/10 px-2 py-0.5 text-xs font-medium text-danger">
                    Désactivée
                  </span>
                ) : null}
              </div>
              <div className="text-sm text-muted">
                {formatPrice(service.price)} · {formatDuration(service.durationMinutes)}
              </div>
              {service.description ? (
                <p className="max-w-prose text-sm text-muted">{service.description}</p>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <button
                type="button"
                className="text-sm font-medium text-accent hover:underline"
                onClick={() => setEditingId(service.id)}
              >
                Modifier
              </button>
              {service.isActive ? (
                <button
                  type="button"
                  className="text-sm font-medium text-muted hover:text-danger disabled:opacity-60"
                  onClick={() => onDeactivate(service)}
                  disabled={pendingId === service.id}
                >
                  {pendingId === service.id ? "…" : "Désactiver"}
                </button>
              ) : null}
            </div>
          </div>
        ),
      )}
    </div>
  );
}
