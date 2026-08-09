"use client";

// Tableau de la file d'attente du salon — adapter UI (hexagonal, ADR-0008,
// #150). Une ligne par RDV `CONFIRMED`/`COMPLETED` du jour, statut de file
// dérivé (badge), actions clairement visibles : marquer l'arrivée, assigner
// une coiffeuse disponible, démarrer la prestation, terminer, marquer payée
// (ouvre le formulaire d'encaissement existant, #33). Les mutations passent
// par les Route Handlers BFF ; le backend reste l'arbitre (préconditions
// ré-affirmées à l'écriture, `409` sinon). Auto-refresh visibility-aware
// réutilisé du Dashboard Manager (#148).

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { CheckIcon, ClockIcon, CoinsIcon, PersonIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { EmptyState } from "@/src/adapters/ui/empty-state";
import { RecordPaymentForm } from "@/src/adapters/ui/record-payment-form";
import type { Employee } from "@/src/domain/employee/employee";
import {
  QUEUE_STATUS_LABELS_FR,
  QUEUE_STATUS_STYLES,
  canComplete,
  canMarkArrived,
  canMarkPaid,
  canStartService,
  type QueueEntry,
} from "@/src/domain/queue/queue";

function formatTime(value: string): string {
  return value.slice(0, 5);
}

type ActionKey = "arrival" | "start" | "complete" | `assign:${string}`;

export interface QueueBoardProps {
  salonId: string;
  entries: QueueEntry[];
  // Coiffeuses **disponibles** (déjà filtrées `ACTIVE`, #150) — options du
  // sélecteur d'assignation.
  availableHairdressers: Employee[];
}

export function QueueBoard({ salonId, entries, availableHairdressers }: QueueBoardProps) {
  const router = useRouter();
  const [pending, setPending] = useState<{ id: string; action: ActionKey } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paymentAppointmentId, setPaymentAppointmentId] = useState<string | null>(null);

  async function runAction(
    appointmentId: string,
    action: ActionKey,
    request: () => Promise<Response>,
  ) {
    setError(null);
    setPending({ id: appointmentId, action });
    try {
      const response = await request();
      if (response.ok) {
        router.refresh();
        return;
      }
      if (response.status === 401) {
        setError("Votre session a expiré. Veuillez vous reconnecter.");
      } else if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Rendez-vous introuvable.");
      } else if (response.status === 409) {
        let detail = "Action impossible dans l'état actuel du rendez-vous.";
        try {
          const parsed = (await response.json()) as { error?: unknown };
          if (typeof parsed.error === "string") detail = parsed.error;
        } catch {
          // corps illisible : message générique conservé.
        }
        setError(detail);
      } else {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPending(null);
    }
  }

  function onMarkArrived(entry: QueueEntry) {
    void runAction(entry.appointmentId, "arrival", () =>
      fetch(
        `/api/salons/${encodeURIComponent(salonId)}/appointments/${encodeURIComponent(entry.appointmentId)}/arrival`,
        { method: "POST" },
      ),
    );
  }

  function onStart(entry: QueueEntry) {
    void runAction(entry.appointmentId, "start", () =>
      fetch(
        `/api/salons/${encodeURIComponent(salonId)}/appointments/${encodeURIComponent(entry.appointmentId)}/start`,
        { method: "POST" },
      ),
    );
  }

  function onComplete(entry: QueueEntry) {
    void runAction(entry.appointmentId, "complete", () =>
      fetch(
        `/api/salons/${encodeURIComponent(salonId)}/appointments/${encodeURIComponent(entry.appointmentId)}/status`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "COMPLETED" }),
        },
      ),
    );
  }

  function onAssign(entry: QueueEntry, hairdresserId: string) {
    void runAction(entry.appointmentId, `assign:${hairdresserId}`, () =>
      fetch(
        `/api/salons/${encodeURIComponent(salonId)}/appointments/${encodeURIComponent(entry.appointmentId)}/hairdresser`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hairdresserId: hairdresserId || null }),
        },
      ),
    );
  }

  const isPending = (appointmentId: string) => pending?.id === appointmentId;

  return (
    <div className="flex flex-col gap-4">
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="overflow-x-auto">
          <table className="w-full min-w-260 text-left text-sm">
            <thead className="bg-background/70 text-xs font-semibold text-muted">
              <tr>
                <th className="px-4 py-3">Heure</th>
                <th className="px-4 py-3">Cliente</th>
                <th className="px-4 py-3">Prestation(s)</th>
                <th className="px-4 py-3">Coiffeuse</th>
                <th className="px-4 py-3">Statut</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {entries.map((entry) => {
                const busy = isPending(entry.appointmentId);
                const style = QUEUE_STATUS_STYLES[entry.queueStatus];
                return (
                  <tr key={entry.appointmentId} className="align-top">
                    <td className="px-4 py-3 font-medium">
                      {formatTime(entry.startTime)}–{formatTime(entry.endTime)}
                    </td>
                    <td className="px-4 py-3 font-semibold">{entry.clientName ?? "—"}</td>
                    <td className="max-w-[220px] px-4 py-3 text-muted">
                      {entry.serviceNames.length > 0 ? entry.serviceNames.join(", ") : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <select
                        aria-label={`Assigner une coiffeuse — ${entry.clientName ?? "cliente"}`}
                        className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25 disabled:cursor-default disabled:opacity-60"
                        value={entry.hairdresserId ?? ""}
                        disabled={busy || entry.status !== "CONFIRMED"}
                        onChange={(event) => onAssign(entry, event.target.value)}
                      >
                        <option value="">Non assignée</option>
                        {availableHairdressers.map((hairdresser) => (
                          <option key={hairdresser.id} value={hairdresser.id}>
                            {hairdresser.fullName}
                          </option>
                        ))}
                        {entry.hairdresserId &&
                        !availableHairdressers.some((h) => h.id === entry.hairdresserId) ? (
                          <option value={entry.hairdresserId}>
                            {entry.hairdresserName ?? "Coiffeuse désactivée"}
                          </option>
                        ) : null}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs font-medium ${style.badge}`}
                      >
                        {QUEUE_STATUS_LABELS_FR[entry.queueStatus]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap justify-end gap-2">
                        {canMarkArrived(entry) && entry.arrivedAt === null ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium transition hover:border-accent/40 disabled:cursor-default disabled:opacity-60"
                            onClick={() => onMarkArrived(entry)}
                            disabled={busy}
                          >
                            <ClockIcon className="shrink-0" />
                            Marquer l&apos;arrivée
                          </button>
                        ) : null}
                        {canStartService(entry) ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0"
                            onClick={() => onStart(entry)}
                            disabled={busy}
                          >
                            <CheckIcon className="shrink-0" />
                            Démarrer
                          </button>
                        ) : null}
                        {canComplete(entry) && entry.queueStatus === "in_progress" ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0"
                            onClick={() => onComplete(entry)}
                            disabled={busy}
                          >
                            <CheckIcon className="shrink-0" />
                            Terminer
                          </button>
                        ) : null}
                        {canMarkPaid(entry) ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-palm/30 bg-palm/10 px-2.5 py-1.5 text-xs font-medium text-palm transition hover:bg-palm/20 disabled:cursor-default disabled:opacity-60"
                            onClick={() => setPaymentAppointmentId(entry.appointmentId)}
                            disabled={busy}
                          >
                            <CoinsIcon className="shrink-0" />
                            Marquer payée
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {entries.length === 0 ? (
                <tr>
                  <td colSpan={6}>
                    <EmptyState
                      icon={<PersonIcon className="size-6" />}
                      title="Aucun rendez-vous en file pour ce jour."
                      description="Les rendez-vous confirmés du jour apparaîtront ici."
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <PaymentDrawer
        salonId={salonId}
        appointmentId={paymentAppointmentId}
        onClose={() => setPaymentAppointmentId(null)}
      />
    </div>
  );
}

function PaymentDrawer({
  salonId,
  appointmentId,
  onClose,
}: {
  salonId: string;
  appointmentId: string | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!appointmentId) return undefined;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [appointmentId, onClose]);

  if (!appointmentId) return null;

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
        aria-labelledby="queue-payment-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2
              id="queue-payment-drawer-title"
              className="font-serif text-xl font-semibold text-ink"
            >
              Marquer comme payée
            </h2>
            <p className="mt-1 text-sm text-muted">
              Enregistre le paiement du rendez-vous.
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
            services={[]}
            appointmentId={appointmentId}
            onCancel={onClose}
            onSaved={onClose}
          />
        </div>
      </aside>
    </div>
  );
}
