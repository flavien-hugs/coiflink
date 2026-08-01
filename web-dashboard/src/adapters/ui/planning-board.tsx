"use client";

// Tableau du planning — adapter UI (hexagonal, ADR-0008), **réutilisable**. Trois
// échelles (jour / semaine / mois), RDV **groupés/colorés par statut** avec légende
// + filtre. La navigation (vue, période, filtre) pilote les `searchParams` via
// `<Link>` (base `basePath`) → un nouveau rendu serveur relit la source de vérité
// backend. Deux variantes :
//   - **gérant** (#26, défaut) : le **pilotage de statut** (confirmer/refuser/
//     terminer/absent) passe par le Route Handler BFF puis `router.refresh()` ; le
//     backend reste l'arbitre (transition interdite → `409` en message **neutre**).
//     L'UI ne propose que les actions autorisées par l'état courant (prédicats
//     miroir de la machine à états #25) — sans en inventer.
//   - **coiffeur** (#27, `readOnly`) : **consultation seule** de son planning
//     assigné ; aucune action de statut n'est exposée (frontière écriture #25 non
//     franchie — voir Non-Goals de la spec). Aucun `salonId` n'est requis.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ComponentType } from "react";

import { CheckIcon, ClockIcon, RefreshIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { EmptyState } from "@/src/adapters/ui/empty-state";
import { SalonToolIcon } from "@/src/adapters/ui/salon-tool-icons";
import {
  APPOINTMENT_STATUSES,
  availableActions,
  STATUS_LABELS_FR,
  STATUS_STYLES,
  type ActionTone,
  type Appointment,
  type AppointmentStatus,
} from "@/src/domain/appointment/appointment";
import {
  appointmentsOn,
  countByStatus,
  groupByStatus,
  shiftDate,
  weekDays,
  type PlanningView,
} from "@/src/domain/appointment/planning-view";
import {
  buildMonthGrid,
  monthKeyFromIso,
  monthLabel,
  WEEKDAY_LABELS_FR,
} from "@/src/domain/salon/month-calendar";

const VIEW_LABELS: Record<PlanningView, string> = {
  day: "Jour",
  week: "Semaine",
  month: "Mois",
};

const ACTION_TONE_CLASSES: Record<ActionTone, string> = {
  primary:
    "bg-accent text-accent-foreground shadow-soft hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0",
  neutral:
    "border border-border bg-surface text-foreground hover:border-accent/40",
  danger:
    "border border-danger/30 bg-surface text-danger hover:border-danger/50 hover:bg-danger/10",
};

// Icône par statut cible — miroir visuel de la machine à états #25 : confirmer/
// terminer (coche), refuser/annuler (croix), absent (horloge, RDV non honoré).
const ACTION_TARGET_ICONS: Partial<Record<AppointmentStatus, ComponentType<{ className?: string }>>> = {
  CONFIRMED: CheckIcon,
  COMPLETED: CheckIcon,
  CANCELLED: XIcon,
  NO_SHOW: ClockIcon,
};

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function formatTime(time: string): string {
  const [hours, minutes] = time.split(":");
  return `${pad2(Number(hours))}:${pad2(Number(minutes))}`;
}

function isoToUtcDate(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

function formatDayLabel(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(isoToUtcDate(iso));
}

function formatShortDay(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(isoToUtcDate(iso));
}

function formatPeriodLabel(view: PlanningView, date: string): string {
  if (view === "day") return formatDayLabel(date);
  if (view === "month") return monthLabel(monthKeyFromIso(date));
  const days = weekDays(date);
  return `${formatShortDay(days[0])} – ${formatShortDay(days[6])}`;
}

// Identifiant client **neutre** (§11.3) : au MVP, pas d'enrichissement nom/téléphone
// (jointure `users` hors périmètre #26) — on affiche un libellé court et opaque.
function clientLabel(clientId: string): string {
  return `Client ${clientId.slice(0, 8)}`;
}

function serviceLabel(count: number): string {
  return `${count} prestation${count > 1 ? "s" : ""}`;
}

export interface PlanningBoardProps {
  view: PlanningView;
  date: string;
  statuses: AppointmentStatus[];
  appointments: Appointment[];
  today: string;
  // Base des liens de navigation (vue/période/filtre). Défaut : zone gérant (#26).
  basePath?: string;
  // Salon ciblé — requis pour le **pilotage de statut** (gérant). Absent en lecture
  // seule (coiffeur #27, route d'appartenance sans `salon_id`).
  salonId?: string;
  // Variante **lecture seule** (coiffeur #27) : aucune action de statut n'est exposée
  // (frontière écriture #25 non franchie — voir Non-Goals). Défaut : false (gérant).
  readOnly?: boolean;
}

export function PlanningBoard({
  view,
  date,
  statuses,
  appointments,
  today,
  basePath = "/gerant/planning",
  salonId,
  readOnly = false,
}: PlanningBoardProps) {
  const router = useRouter();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Filtre par statut : ensemble « affiché ». Vide dans l'URL = **tous** affichés.
  const activeSet = new Set<AppointmentStatus>(
    statuses.length ? statuses : APPOINTMENT_STATUSES,
  );

  function planningHref(next: {
    view?: PlanningView;
    date?: string;
    statuses?: AppointmentStatus[];
  }): string {
    const params = new URLSearchParams();
    params.set("view", next.view ?? view);
    params.set("date", next.date ?? date);
    for (const status of next.statuses ?? statuses) params.append("status", status);
    return `${basePath}?${params.toString()}`;
  }

  function toggleStatusHref(status: AppointmentStatus): string {
    const next = new Set(activeSet);
    if (next.has(status)) next.delete(status);
    else next.add(status);
    let selected = APPOINTMENT_STATUSES.filter((item) => next.has(item));
    // Tous cochés → URL propre sans filtre (équivalent « tous »).
    if (selected.length === APPOINTMENT_STATUSES.length) selected = [];
    return planningHref({ statuses: selected });
  }

  async function onAction(appointmentId: string, status: AppointmentStatus) {
    // Variante lecture seule (coiffeur #27) ou salon absent : aucune écriture de
    // statut n'est exposée (frontière écriture #25 non franchie).
    if (readOnly || !salonId) return;
    setError(null);
    setPendingId(appointmentId);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/appointments/${encodeURIComponent(appointmentId)}/status`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        },
      );
      if (response.ok) {
        router.refresh();
        return;
      }
      if (response.status === 409) {
        setError("Action impossible dans l'état actuel du rendez-vous.");
      } else if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Rendez-vous introuvable.");
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

  const counts = countByStatus(appointments);

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        view={view}
        date={date}
        today={today}
        planningHref={planningHref}
        shiftedHref={(delta) => planningHref({ date: shiftDate(view, date, delta) })}
      />

      <Legend
        counts={counts}
        activeSet={activeSet}
        filtered={statuses.length > 0}
        toggleStatusHref={toggleStatusHref}
        resetHref={planningHref({ statuses: [] })}
      />

      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      {view === "day" ? (
        <DayView
          appointments={appointments}
          pendingId={pendingId}
          onAction={onAction}
          readOnly={readOnly}
        />
      ) : null}
      {view === "week" ? (
        <WeekView
          date={date}
          today={today}
          appointments={appointments}
          dayHref={(iso) => planningHref({ view: "day", date: iso })}
        />
      ) : null}
      {view === "month" ? (
        <MonthView
          date={date}
          today={today}
          appointments={appointments}
          dayHref={(iso) => planningHref({ view: "day", date: iso })}
        />
      ) : null}
    </div>
  );
}

function Toolbar({
  view,
  date,
  today,
  planningHref,
  shiftedHref,
}: {
  view: PlanningView;
  date: string;
  today: string;
  planningHref: (next: { view?: PlanningView; date?: string }) => string;
  shiftedHref: (delta: number) => string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div
        className="inline-flex rounded-lg border border-border bg-surface p-1"
        role="group"
        aria-label="Échelle du planning"
      >
        {(Object.keys(VIEW_LABELS) as PlanningView[]).map((candidate) => {
          const active = candidate === view;
          return (
            <Link
              key={candidate}
              href={planningHref({ view: candidate })}
              aria-current={active ? "page" : undefined}
              className={
                active
                  ? "rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-foreground"
                  : "rounded-md px-3 py-1.5 text-sm font-medium text-muted transition hover:text-foreground"
              }
            >
              {VIEW_LABELS[candidate]}
            </Link>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium capitalize">
          {formatPeriodLabel(view, date)}
        </span>
        <div className="inline-flex items-center gap-1">
          <Link
            href={shiftedHref(-1)}
            aria-label="Période précédente"
            className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground"
          >
            ‹
          </Link>
          <Link
            href={planningHref({ date: today })}
            className="inline-flex h-9 items-center justify-center rounded-lg border border-border bg-surface px-3 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
          >
            Aujourd&apos;hui
          </Link>
          <Link
            href={shiftedHref(1)}
            aria-label="Période suivante"
            className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground"
          >
            ›
          </Link>
        </div>
      </div>
    </div>
  );
}

function Legend({
  counts,
  activeSet,
  filtered,
  toggleStatusHref,
  resetHref,
}: {
  counts: Record<AppointmentStatus, number>;
  activeSet: Set<AppointmentStatus>;
  filtered: boolean;
  toggleStatusHref: (status: AppointmentStatus) => string;
  resetHref: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-surface p-2.5 shadow-soft">
      {APPOINTMENT_STATUSES.map((status) => {
        const active = activeSet.has(status);
        return (
          <Link
            key={status}
            href={toggleStatusHref(status)}
            aria-pressed={active}
            className={
              active
                ? `inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition hover:-translate-y-0.5 ${STATUS_STYLES[status].badge}`
                : "inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-xs font-medium text-muted opacity-60 transition hover:opacity-100"
            }
            title={
              active ? "Masquer ce statut" : "Afficher ce statut"
            }
          >
            <span
              className={`size-2 rounded-full ${STATUS_STYLES[status].dot}`}
              aria-hidden="true"
            />
            {STATUS_LABELS_FR[status]}
            <span
              className={`inline-flex min-w-5 items-center justify-center rounded-full px-1 text-[0.7rem] font-bold tabular-nums ${
                active ? "bg-foreground/10" : ""
              }`}
            >
              {counts[status]}
            </span>
          </Link>
        );
      })}
      {filtered ? (
        <Link
          href={resetHref}
          className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-accent hover:underline"
        >
          <RefreshIcon className="shrink-0" />
          Réinitialiser
        </Link>
      ) : null}
    </div>
  );
}

function DayView({
  appointments,
  pendingId,
  onAction,
  readOnly,
}: {
  appointments: Appointment[];
  pendingId: string | null;
  onAction: (appointmentId: string, status: AppointmentStatus) => void;
  readOnly: boolean;
}) {
  if (appointments.length === 0) {
    return <PlanningEmptyState />;
  }

  const groups = groupByStatus(appointments).filter((group) => group.count > 0);

  return (
    <div className="flex flex-col gap-5">
      {groups.map((group) => (
        <div key={group.status} className="flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-border pb-2">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${STATUS_STYLES[group.status].badge}`}
            >
              <span
                className={`size-1.5 rounded-full ${STATUS_STYLES[group.status].dot}`}
                aria-hidden="true"
              />
              {STATUS_LABELS_FR[group.status]}
            </span>
            <span className="text-xs font-medium text-muted tabular-nums">
              {group.count} rendez-vous
            </span>
          </div>
          <ul className="flex flex-col gap-2.5">
            {group.appointments.map((appointment) => (
              <AppointmentCard
                key={appointment.id}
                appointment={appointment}
                pending={pendingId === appointment.id}
                onAction={onAction}
                readOnly={readOnly}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function AppointmentCard({
  appointment,
  pending,
  onAction,
  readOnly,
}: {
  appointment: Appointment;
  pending: boolean;
  onAction: (appointmentId: string, status: AppointmentStatus) => void;
  readOnly: boolean;
}) {
  // Lecture seule (coiffeur #27) : aucune action de statut n'est proposée.
  const actions = readOnly ? [] : availableActions(appointment.status);
  return (
    <li className="flex flex-col gap-4 rounded-2xl border border-border bg-surface p-5 shadow-soft transition hover:shadow-elevated sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-stretch gap-3.5">
        <span
          className={`w-1 shrink-0 rounded-full ${STATUS_STYLES[appointment.status].dot}`}
          aria-hidden="true"
        />
        <div>
          <div className="flex items-center gap-1.5 font-semibold tabular-nums">
            <ClockIcon className="shrink-0 text-muted" />
            {formatTime(appointment.startTime)} – {formatTime(appointment.endTime)}
          </div>
          <p className="mt-1 text-sm text-muted">
            {clientLabel(appointment.clientId)} · {serviceLabel(appointment.services.length)}
          </p>
          {appointment.clientNote ? (
            <p className="mt-2 line-clamp-2 rounded-lg bg-background/60 px-2.5 py-1.5 text-sm text-muted">
              « {appointment.clientNote} »
            </p>
          ) : null}
        </div>
      </div>

      {actions.length > 0 ? (
        <div className="flex flex-wrap gap-2 sm:shrink-0">
          {actions.map((action) => {
            const ActionIcon = ACTION_TARGET_ICONS[action.target];
            return (
              <button
                key={action.target}
                type="button"
                disabled={pending}
                onClick={() => onAction(appointment.id, action.target)}
                className={`inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 rounded-lg px-3.5 text-sm font-semibold transition disabled:cursor-default disabled:opacity-60 ${ACTION_TONE_CLASSES[action.tone]}`}
              >
                {pending ? null : ActionIcon ? <ActionIcon className="shrink-0" /> : null}
                {pending ? "…" : action.label}
              </button>
            );
          })}
        </div>
      ) : null}
    </li>
  );
}

function WeekView({
  date,
  today,
  appointments,
  dayHref,
}: {
  date: string;
  today: string;
  appointments: Appointment[];
  dayHref: (iso: string) => string;
}) {
  const days = weekDays(date);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {days.map((iso) => {
        const dayAppointments = appointmentsOn(appointments, iso);
        const isToday = iso === today;
        return (
          <div
            key={iso}
            className={`flex min-h-40 flex-col rounded-2xl border bg-surface p-3 ${isToday ? "border-accent/50" : "border-border"}`}
          >
            <Link
              href={dayHref(iso)}
              className="mb-2 text-xs font-semibold capitalize text-muted transition hover:text-foreground"
            >
              {new Intl.DateTimeFormat("fr-FR", {
                weekday: "short",
                day: "numeric",
                timeZone: "UTC",
              }).format(isoToUtcDate(iso))}
            </Link>
            <ul className="flex flex-col gap-1">
              {dayAppointments.map((appointment) => (
                <li
                  key={appointment.id}
                  className="flex items-center gap-1.5 rounded-md bg-background/60 px-2 py-1 text-xs"
                >
                  <span
                    className={`size-2 shrink-0 rounded-full ${STATUS_STYLES[appointment.status].dot}`}
                    aria-hidden="true"
                  />
                  <span className="tabular-nums">
                    {formatTime(appointment.startTime)}
                  </span>
                  <span className="truncate text-muted">
                    {STATUS_LABELS_FR[appointment.status]}
                  </span>
                </li>
              ))}
              {dayAppointments.length === 0 ? (
                <li className="text-xs text-muted">—</li>
              ) : null}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function MonthView({
  date,
  today,
  appointments,
  dayHref,
}: {
  date: string;
  today: string;
  appointments: Appointment[];
  dayHref: (iso: string) => string;
}) {
  const weeks = buildMonthGrid(monthKeyFromIso(date), today);
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
      <div className="grid grid-cols-7 border-b border-border bg-background/70 text-xs font-semibold text-muted">
        {WEEKDAY_LABELS_FR.map((label) => (
          <div key={label} className="px-2 py-2 text-center">
            {label}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {weeks.flat().map((cell) => {
          const counts = countByStatus(appointmentsOn(appointments, cell.date));
          const dayNumber = Number(cell.date.split("-")[2]);
          return (
            <Link
              key={cell.date}
              href={dayHref(cell.date)}
              className={`flex min-h-24 flex-col gap-1 border-b border-r border-border p-2 text-left transition hover:bg-background/60 ${cell.inCurrentMonth ? "" : "bg-background/40"}`}
            >
              <span
                className={
                  cell.isToday
                    ? "inline-flex size-6 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground"
                    : `text-xs font-medium ${cell.inCurrentMonth ? "text-foreground" : "text-muted"}`
                }
              >
                {dayNumber}
              </span>
              <div className="flex flex-wrap gap-1">
                {APPOINTMENT_STATUSES.filter((status) => counts[status] > 0).map(
                  (status) => (
                    <span
                      key={status}
                      className={`inline-flex items-center gap-0.5 rounded-full border px-1.5 text-[0.65rem] font-medium tabular-nums ${STATUS_STYLES[status].badge}`}
                      title={STATUS_LABELS_FR[status]}
                    >
                      <span
                        className={`size-1.5 rounded-full ${STATUS_STYLES[status].dot}`}
                        aria-hidden="true"
                      />
                      {counts[status]}
                    </span>
                  ),
                )}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function PlanningEmptyState() {
  return (
    <div className="rounded-2xl border border-border bg-surface shadow-soft">
      <EmptyState
        icon={<SalonToolIcon tool="scissors" className="size-7" />}
        title="Aucun rendez-vous pour cette période."
      />
    </div>
  );
}
