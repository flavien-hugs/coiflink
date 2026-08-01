"use client";

// Panneau « Enregistrer un paiement » — adapter UI (hexagonal, ADR-0008),
// US-5.1 #33. Bouton déclencheur + drawer droit portant `RecordPaymentForm`
// (même patron que `CustomerList`/`ServiceList`/`SalonDetails`). Le
// Server Component de la page (`page.tsx`) reste responsable du chargement
// des données ; ce composant ne gère que l'état d'ouverture du panneau.

import { useEffect, useState } from "react";

import { PlusIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { RecordPaymentForm } from "@/src/adapters/ui/record-payment-form";
import type { Service } from "@/src/domain/service/service";

export function PaymentPanel({
  salonId,
  services,
}: {
  salonId: string;
  services: Service[];
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="inline-flex h-10 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
        onClick={() => setOpen(true)}
      >
        <PlusIcon className="shrink-0" />
        Nouvel encaissement
      </button>

      <PaymentDrawer
        salonId={salonId}
        services={services}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

function PaymentDrawer({
  salonId,
  services,
  open,
  onClose,
}: {
  salonId: string;
  services: Service[];
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
        aria-labelledby="payment-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2 id="payment-drawer-title" className="font-serif text-xl font-semibold text-ink">
              Enregistrer un paiement
            </h2>
            <p className="mt-1 text-sm text-muted">
              Montant et prestation sont obligatoires.
            </p>
          </div>
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
            onClick={onClose}
          >
            <XIcon className="shrink-0" />
            Fermer
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <RecordPaymentForm
            salonId={salonId}
            services={services}
            onCancel={onClose}
            onSaved={onClose}
          />
        </div>
      </aside>
    </div>
  );
}
