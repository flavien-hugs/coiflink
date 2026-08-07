"use client";

// Icône « Modifier » + panneau latéral droit portant `CustomerProfileForm` —
// adapter UI (hexagonal, ADR-0008, US-4.6 #144). Même patron que
// `SalonDetails`/`PaymentPanel` : un bouton déclencheur ouvre un drawer
// droit ; `Échap` ou le fond assombri le referment. Le formulaire referme
// lui-même le panneau après un enregistrement réussi (`onSaved`).

import { useEffect, useState } from "react";

import { PencilIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { CustomerProfileForm } from "@/src/adapters/ui/customer-profile-form";
import type { Customer } from "@/src/domain/customer/customer";

export function CustomerProfilePanel({
  salonId,
  customer,
}: {
  salonId: string;
  customer: Customer;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
        onClick={() => setOpen(true)}
        aria-label="Modifier les informations du client"
      >
        <PencilIcon className="shrink-0" />
        Modifier
      </button>

      <ProfileDrawer
        salonId={salonId}
        customer={customer}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

function ProfileDrawer({
  salonId,
  customer,
  open,
  onClose,
}: {
  salonId: string;
  customer: Customer;
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
        aria-labelledby="customer-profile-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2
              id="customer-profile-drawer-title"
              className="font-serif text-xl font-semibold text-ink"
            >
              Modifier les informations
            </h2>
            <p className="mt-1 text-sm text-muted">
              Le nom du client est obligatoire.
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
          <CustomerProfileForm
            salonId={salonId}
            customerId={customer.id}
            initialFullName={customer.fullName}
            initialPhone={customer.phone}
            initialGender={customer.gender}
            onCancel={onClose}
            onSaved={onClose}
          />
        </div>
      </aside>
    </div>
  );
}
