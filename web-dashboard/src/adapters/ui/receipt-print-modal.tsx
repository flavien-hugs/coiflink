"use client";

// Modale « Reçu » — aperçu avant impression d'un paiement (gérant, ADR-0040).
// Centrée via `createPortal` (même patron que `exceptions-calendar.tsx` — une
// prévisualisation de reçu se lit mieux centrée, à largeur fixe, qu'un tiroir
// latéral). Récupère le reçu via le BFF (`GET /api/salons/{id}/payments/{id}/receipt`)
// au montage ; états loading/erreur/prêt explicites (patron manuel `useState`,
// comme `RecordPaymentForm` — pas `useTransition`). Le chargement vit dans
// `ReceiptLoader`, **remonté** (`key`) à chaque « Réessayer » plutôt que remis à
// zéro par un `setState` synchrone dans l'effet (React ne recommande pas
// d'appeler `setState` directement dans le corps d'un effet).
//
// Impression : `window.print()` + CSS `@media print` scopée à `.receipt-print-area`
// (`app/globals.css`). L'état « imprimé » se déduit de l'évènement navigateur
// `afterprint` — un signal **best-effort** (dialogue fermé), pas une confirmation
// matérielle : le navigateur ne peut pas savoir si le ticket est réellement sorti
// de l'imprimante thermique (documenté, ADR-0040 §5).

import { createPortal } from "react-dom";
import { useEffect, useState } from "react";

import { PrinterIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { formatXof, paymentMethodLabel } from "@/src/domain/payments/payment";
import type { ManagerReceipt } from "@/src/domain/payments/receipt";
import { formatTransactionDateTime, paymentStatusLabel } from "@/src/domain/payments/transaction";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; receipt: ManagerReceipt };

export interface ReceiptPrintModalProps {
  salonId: string;
  paymentId: string;
  onClose: () => void;
}

export function ReceiptPrintModal({ salonId, paymentId, onClose }: ReceiptPrintModalProps) {
  const [printed, setPrinted] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    function onAfterPrint() {
      setPrinted(true);
    }
    window.addEventListener("afterprint", onAfterPrint);
    return () => window.removeEventListener("afterprint", onAfterPrint);
  }, []);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="receipt-print-no-print absolute inset-0 cursor-default bg-foreground/35"
        aria-label="Fermer"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="receipt-modal-title"
        className="relative flex max-h-[90vh] w-full max-w-sm flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-elevated"
      >
        <div className="receipt-print-no-print flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <h3 id="receipt-modal-title" className="font-serif text-base font-semibold text-ink">
            Reçu
          </h3>
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
            onClick={onClose}
          >
            <XIcon className="shrink-0" />
            Fermer
          </button>
        </div>

        <ReceiptLoader
          key={reloadToken}
          salonId={salonId}
          paymentId={paymentId}
          printed={printed}
          onRetry={() => setReloadToken((n) => n + 1)}
        />
      </div>
    </div>,
    document.body,
  );
}

function ReceiptLoader({
  salonId,
  paymentId,
  printed,
  onRetry,
}: {
  salonId: string;
  paymentId: string;
  printed: boolean;
  onRetry: () => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      let response: Response;
      try {
        response = await fetch(
          `/api/salons/${encodeURIComponent(salonId)}/payments/${encodeURIComponent(paymentId)}/receipt`,
          { cache: "no-store" },
        );
      } catch {
        if (!cancelled) {
          setState({ status: "error", message: "Service momentanément indisponible." });
        }
        return;
      }
      if (cancelled) return;

      if (response.status === 200) {
        const body = (await response.json()) as { receipt: ManagerReceipt };
        setState({ status: "ready", receipt: body.receipt });
        return;
      }
      if (response.status === 404) {
        setState({ status: "error", message: "Reçu introuvable." });
        return;
      }
      let message = "Service momentanément indisponible.";
      try {
        const body = (await response.json()) as { error?: string };
        if (body.error) message = body.error;
      } catch {
        // corps illisible : message générique conservé.
      }
      setState({ status: "error", message });
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [salonId, paymentId]);

  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {state.status === "loading" ? <ReceiptLoading /> : null}
        {state.status === "error" ? (
          <ReceiptError message={state.message} onRetry={onRetry} />
        ) : null}
        {state.status === "ready" ? <ReceiptBody receipt={state.receipt} /> : null}
      </div>

      {state.status === "ready" ? (
        <div className="receipt-print-no-print flex items-center justify-between gap-3 border-t border-border px-5 py-4">
          {printed ? (
            <p role="status" className="text-sm text-accent">
              Le reçu a été envoyé à l&apos;impression.
            </p>
          ) : (
            <span />
          )}
          <button
            type="button"
            className="inline-flex h-10 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
            onClick={() => window.print()}
          >
            <PrinterIcon className="shrink-0" />
            Imprimer
          </button>
        </div>
      ) : null}
    </>
  );
}

function ReceiptLoading() {
  return (
    <div className="flex items-center justify-center py-10">
      <RefreshSpinner />
    </div>
  );
}

function RefreshSpinner() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      className="size-6 animate-spin text-muted"
      aria-hidden
    >
      <path d="M16 10a6 6 0 1 1-1.8-4.3" />
      <path d="M16 3.5V7h-3.5" />
    </svg>
  );
}

function ReceiptError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <p role="alert" className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger">
        {message}
      </p>
      <button
        type="button"
        className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
        onClick={onRetry}
      >
        Réessayer
      </button>
    </div>
  );
}

function ReceiptBody({ receipt }: { receipt: ManagerReceipt }) {
  return (
    <div className="receipt-print-area font-mono text-xs text-foreground">
      <p className="text-center font-serif text-sm font-semibold text-ink">{receipt.salonName}</p>
      <p className="mt-1 text-center text-muted">{receipt.receiptNumber}</p>
      <p className="text-center text-muted">{formatTransactionDateTime(receipt.paidAt)}</p>

      <div className="my-3 border-t border-dashed border-border" />

      {receipt.clientName ? (
        <p>
          Cliente : {receipt.clientName}
          {receipt.clientPhone ? ` — ${receipt.clientPhone}` : ""}
        </p>
      ) : null}

      <div className="my-3 border-t border-dashed border-border" />

      <ul className="space-y-1">
        {receipt.lines.length > 0 ? (
          receipt.lines.map((line, index) => (
            <li key={`${line.serviceName}-${index}`} className="flex items-center justify-between gap-2">
              <span>{line.serviceName}</span>
              <span>{formatXof(line.amount)}</span>
            </li>
          ))
        ) : (
          <li className="text-muted">Prestation</li>
        )}
      </ul>

      <div className="my-3 border-t border-dashed border-border" />

      <div className="flex items-center justify-between gap-2 font-semibold">
        <span>Total</span>
        <span>{formatXof(receipt.amount)}</span>
      </div>
      <p className="mt-1 flex items-center justify-between gap-2 text-muted">
        <span>Mode de paiement</span>
        <span>{paymentMethodLabel(receipt.paymentMethod)}</span>
      </p>
      <p className="flex items-center justify-between gap-2 text-muted">
        <span>Statut</span>
        <span>{paymentStatusLabel(receipt.status)}</span>
      </p>
      {receipt.reference ? (
        <p className="mt-1 text-muted">Référence : {receipt.reference}</p>
      ) : null}

      <p className="mt-4 text-center text-muted">Merci de votre visite.</p>
    </div>
  );
}
