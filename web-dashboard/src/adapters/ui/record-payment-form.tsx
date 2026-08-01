"use client";

// Formulaire d'enregistrement d'un paiement — adapter UI (hexagonal, ADR-0008).
// Le gérant choisit la **prestation à encaisser** ; le montant est **pré-rempli**
// avec son prix (guidage de la cohérence, US-5.1 #33), le gérant peut l'ajuster
// mais la **source de vérité reste le backend** qui rejette tout écart
// (§5.3/§8.2). Valide **côté client** (parité domaine, retour immédiat) puis
// poste vers le Route Handler BFF `/api/salons/{id}/payments`, qui proxifie le
// backend avec le jeton du cookie httpOnly. En cas de succès, rafraîchit la page.
//
// Messages génériques ; aucun montant/PII journalisé. Le backend reste l'autorité
// (permission `PAYMENT_RECORD`, portée §11.2).

import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { CheckIcon, CoinsIcon, HashIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { FieldLabel } from "@/src/adapters/ui/field-label";
import { SearchableSelect } from "@/src/adapters/ui/searchable-select";
import {
  PAYMENT_METHOD_OPTIONS,
  REFERENCE_MAX_LENGTH,
  formatXof,
  validatePayment,
  type PaymentMethod,
} from "@/src/domain/payments/payment";
import type { Service } from "@/src/domain/service/service";

const INPUT_WITH_ICON_CLASS =
  "rounded-lg border border-border bg-surface py-2.5 pl-9 pr-3 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface RecordPaymentFormProps {
  salonId: string;
  // Prestations **actives** encaissables (nom + prix attendu). Une liste vide
  // empêche l'encaissement : le gérant doit d'abord créer une prestation.
  services: Service[];
  onSaved?: () => void;
  onCancel?: () => void;
}

export function RecordPaymentForm({
  salonId,
  services,
  onSaved,
  onCancel,
}: RecordPaymentFormProps) {
  const router = useRouter();
  const [serviceId, setServiceId] = useState(services[0]?.id ?? "");
  const selectedService = useMemo(
    () => services.find((service) => service.id === serviceId) ?? null,
    [services, serviceId],
  );
  const serviceOptions = useMemo(
    () => services.map((service) => ({ value: service.id, label: `${service.name} — ${formatXof(service.price)}` })),
    [services],
  );
  const [amount, setAmount] = useState(services[0]?.price ?? "");
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("CASH");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [pending, setPending] = useState(false);

  // Sélectionner une prestation **pré-remplit** son prix attendu (le gérant peut
  // le corriger, mais le backend vérifie la cohérence).
  function onSelectService(nextId: string) {
    setServiceId(nextId);
    const next = services.find((service) => service.id === nextId);
    if (next) setAmount(next.price);
    setError(null);
    setSuccess(false);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(false);

    const validated = validatePayment({
      amount,
      paymentMethod,
      serviceId: serviceId || null,
      reference,
    });
    if (!validated.ok) {
      switch (validated.reason) {
        case "invalid-amount":
          setError("Le montant saisi n'est pas exploitable.");
          break;
        case "invalid-method":
          setError("Le mode de paiement sélectionné est invalide.");
          break;
        case "invalid-reference":
          setError(
            `La référence ne doit pas dépasser ${REFERENCE_MAX_LENGTH} caractères.`,
          );
          break;
        default:
          setError("Sélectionnez la prestation à encaisser.");
      }
      return;
    }

    setPending(true);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/payments`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(validated.value),
        },
      );

      if (response.ok) {
        setReference("");
        setSuccess(true);
        router.refresh();
        onSaved?.();
        return;
      }
      if (response.status === 422) {
        // Message neutre du BFF : incohérence de montant, référence introuvable
        // ou validation générique. On l'affiche tel quel (déjà sans valeur).
        let detail = "Paiement invalide.";
        try {
          const parsed = (await response.json()) as { error?: unknown };
          if (typeof parsed.error === "string") detail = parsed.error;
        } catch {
          // corps illisible : on garde le message générique.
        }
        setError(detail);
      } else if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
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

  if (services.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-muted">
        Ajoutez d&apos;abord une prestation active pour pouvoir encaisser.
      </p>
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
      <div className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel required>Prestation à encaisser</FieldLabel>
        <SearchableSelect
          ariaLabel="Prestation à encaisser"
          value={serviceId}
          options={serviceOptions}
          onChange={onSelectService}
          placeholder="Sélectionner une prestation"
          searchPlaceholder="Rechercher une prestation"
          emptyLabel="Aucune prestation trouvée"
        />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel required>Montant (FCFA)</FieldLabel>
          <div className="relative">
            <CoinsIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              inputMode="decimal"
              name="amount"
              className={INPUT_WITH_ICON_CLASS}
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                setError(null);
                setSuccess(false);
              }}
              required
            />
          </div>
          {selectedService ? (
            <span className="text-xs font-normal text-muted">
              Prix attendu : {formatXof(selectedService.price)} — le montant doit
              correspondre.
            </span>
          ) : null}
        </label>
        <div className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel required>Mode de paiement</FieldLabel>
          <SearchableSelect
            ariaLabel="Mode de paiement"
            value={paymentMethod}
            options={PAYMENT_METHOD_OPTIONS}
            onChange={(next) => setPaymentMethod(next as PaymentMethod)}
            placeholder="Sélectionner un mode"
            searchPlaceholder="Rechercher un mode"
            emptyLabel="Aucun mode trouvé"
          />
        </div>
      </div>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel optional>Référence</FieldLabel>
        <div className="relative">
          <HashIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="text"
            name="reference"
            className={INPUT_WITH_ICON_CLASS}
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            maxLength={REFERENCE_MAX_LENGTH}
            placeholder="Numéro de reçu, transaction Mobile Money…"
          />
        </div>
      </label>
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      {success ? (
        <p
          className="rounded-lg border border-accent/25 bg-accent/10 px-3 py-2 text-sm text-accent"
          role="status"
        >
          Paiement enregistré et inscrit au journal de caisse.
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          disabled={pending}
        >
          {pending ? null : <CheckIcon className="shrink-0" />}
          {pending ? "Enregistrement…" : "Enregistrer le paiement"}
        </button>
        {onCancel ? (
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-muted hover:text-foreground"
            onClick={onCancel}
            disabled={pending}
          >
            <XIcon className="shrink-0" />
            Annuler
          </button>
        ) : null}
      </div>
    </form>
  );
}
