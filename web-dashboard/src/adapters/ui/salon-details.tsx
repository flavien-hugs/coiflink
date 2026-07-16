"use client";

// Fiche « Informations générales » d'un salon — adapter UI (hexagonal,
// ADR-0008). Lecture seule + bouton « Modifier » qui ouvre un drawer droit
// portant `SalonForm` en mode édition (même patron que `ServiceList`/
// `ServiceForm`, #17). La modification est journalisée §11.4 côté backend.

import { useEffect, useState } from "react";

import { SalonForm } from "@/src/adapters/ui/salon-form";
import type { Salon } from "@/src/domain/salon/salon";

export function SalonDetails({ salon }: { salon: Salon }) {
  const [editing, setEditing] = useState(false);

  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">{salon.name}</h2>
          {salon.description ? (
            <p className="mt-1 max-w-prose text-sm text-muted">{salon.description}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-full bg-foreground/5 px-2.5 py-1 text-xs font-medium tracking-wide uppercase">
            {salon.status}
          </span>
          <button
            type="button"
            className="cursor-pointer rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
            onClick={() => setEditing(true)}
          >
            Modifier
          </button>
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
        <Field label="Téléphone" value={salon.phone} />
        <Field label="Adresse" value={salon.address} />
        <Field label="Ville" value={salon.city} />
        <Field label="Commune" value={salon.commune} />
        <Field
          label="Coordonnées"
          value={
            salon.latitude != null && salon.longitude != null
              ? `${salon.latitude}, ${salon.longitude}`
              : null
          }
        />
      </dl>

      <EditDrawer salon={salon} open={editing} onClose={() => setEditing(false)} />
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium tracking-wide text-muted uppercase">{label}</dt>
      <dd>{value ?? <span className="text-muted">—</span>}</dd>
    </div>
  );
}

function EditDrawer({
  salon,
  open,
  onClose,
}: {
  salon: Salon;
  open: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return undefined;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-foreground/35"
        aria-label="Fermer le panneau"
        onClick={onClose}
      />
      <aside
        className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-border bg-surface shadow-elevated"
        role="dialog"
        aria-modal="true"
        aria-labelledby="salon-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2 id="salon-drawer-title" className="text-xl font-semibold">
              Modifier le salon
            </h2>
            <p className="mt-1 text-sm text-muted">Le nom du salon est obligatoire.</p>
          </div>
          <button
            type="button"
            className="cursor-pointer rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
            onClick={onClose}
          >
            Fermer
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <SalonForm salon={salon} onCancel={onClose} onSaved={onClose} />
        </div>
      </aside>
    </div>
  );
}
