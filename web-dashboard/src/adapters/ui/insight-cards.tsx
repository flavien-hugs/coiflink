"use client";

// Cartes « À surveiller » — adapter UI (hexagonal, ADR-0008), réorganisation du
// tableau de bord gérant. Remplace l'ancien groupe d'onglets : 4 panneaux
// (Alertes importantes, Fréquentation & équipe, Chiffre d'affaires,
// Prestations les plus demandées) rejoignent la grille des indicateurs clés
// comme des **cartes cliquables**, chacune menant à son contenu complet
// **ancré** juste en dessous — plutôt que caché derrière un clic d'onglet.
// Aucun panneau existant n'est réécrit : `AlertsPanel`/`AttendanceChart`/
// `HairdresserPerformancePanel`/`RevenueTiles`/`RevenueChart`/
// `ServiceDemandPanel` sont simplement sortis de `<Tabs>` et rendus tels quels
// dans la section ancrée.
//
// Distinction visuelle KPI vs. carte « insight » (à la différence des 4
// `CardShell` de `DashboardKpiCards`, statiques, sans icône ni hover) : chaque
// carte ici porte une icône-badge teintée + un chevron, et un hover
// `-translate-y-0.5 hover:shadow-elevated` — geste visuel de lien, pas de
// métrique figée. La carte « Alertes » est la seule teintée par sévérité, même
// à vide (`palm` = signal positif volontaire). La carte « Chiffre d'affaires »
// n'affiche jamais le total du jour (déjà visible dans les indicateurs clés
// juste au-dessus) — elle headline la tendance de la **semaine**.

import { useState } from "react";

import { AlertsPanel } from "@/src/adapters/ui/alerts-panel";
import { AttendanceChart } from "@/src/adapters/ui/attendance-chart";
import { HairdresserPerformancePanel } from "@/src/adapters/ui/hairdresser-performance-panel";
import { RevenueChart } from "@/src/adapters/ui/revenue-chart";
import { RevenueTiles } from "@/src/adapters/ui/revenue-tiles";
import { ServiceDemandPanel } from "@/src/adapters/ui/service-demand-panel";
import { XIcon } from "@/src/adapters/ui/action-icons";
import {
  ALERT_LABELS_FR,
  formatAlertCount,
  mostSevereAlert,
  type AlertList,
} from "@/src/domain/dashboard/alerts";
import type { AttendanceSeries } from "@/src/domain/dashboard/series";
import {
  formatCountDelta,
  formatMoneyDelta,
  type CountEvolution,
  type MoneyEvolution,
} from "@/src/domain/dashboard/kpi";
import { formatOccurrences, type ServiceDemandRanking } from "@/src/domain/payments/service-demand";
import { formatRevenueTotal, type RevenueSummary } from "@/src/domain/payments/revenue";
import type { RevenueSeries } from "@/src/domain/dashboard/series";
import type { HairdresserPerformanceReport } from "@/src/domain/stats/hairdresser-performance";

type CardKey = "alertes" | "analyse" | "chiffre-affaires" | "prestations";

export interface InsightCardsProps {
  alerts: AlertList | null;
  // `null` si la lecture `dashboard/kpis` a échoué (patron « dégradation
  // locale » #41) : la carte « Fréquentation & équipe » dégrade seule, sans
  // faire disparaître les 3 autres cartes qui ne dépendent pas de ce KPI.
  attendanceToday: CountEvolution | null;
  attendanceSeries: AttendanceSeries | null;
  hairdresserReport: HairdresserPerformanceReport | null;
  // `null` si la lecture `dashboard/kpis` a échoué — même dégradation locale
  // que `attendanceToday`, isolée à la carte « Chiffre d'affaires ».
  revenueThisWeek: MoneyEvolution | null;
  revenueSummary: RevenueSummary;
  revenueSeries: RevenueSeries | null;
  // `null` si la lecture `service-demand` (bornée à la semaine civile en cours)
  // a échoué — distinct d'une lecture réussie sans aucune prestation réalisée
  // cette semaine (`byVolume: []`). Confondre les deux masquerait une panne
  // derrière « Aucune donnée », la même dégradation-honnêteté que pour `alerts`.
  serviceDemandThisWeek: ServiceDemandRanking | null;
  serviceDemandRanking: ServiceDemandRanking | null;
}

export function InsightCards({
  alerts,
  attendanceToday,
  attendanceSeries,
  hairdresserReport,
  revenueThisWeek,
  revenueSummary,
  revenueSeries,
  serviceDemandThisWeek,
  serviceDemandRanking,
}: InsightCardsProps) {
  const [expanded, setExpanded] = useState<CardKey | null>(null);

  // `serviceDemandThisWeek === null` signifie un **échec de lecture** (même
  // dégradation locale que `alerts`) — distinct d'un classement chargé avec
  // succès mais vide (`byVolume: []`, réellement aucune prestation cette
  // semaine).
  const demandFailed = serviceDemandThisWeek === null;
  const topServiceThisWeek = serviceDemandThisWeek?.byVolume[0] ?? null;

  function toggle(key: CardKey) {
    setExpanded((current) => (current === key ? null : key));
  }

  // `alerts === null` signifie un **échec de lecture** (dégradation locale
  // #41) — distinct d'une lecture réussie sans alerte active (`items: []`).
  // Confondre les deux afficherait « Tout va bien » alors que l'état réel est
  // inconnu : une fausse réassurance, pire qu'une absence d'information.
  const alertsFailed = alerts === null;
  const severe = alerts ? mostSevereAlert(alerts.items) : null;
  const alertsCount = alerts?.items.length ?? 0;
  const alertTone: "danger" | "gold" | "palm" = alertsFailed
    ? "gold"
    : severe === null
      ? "palm"
      : severe.severity === "info"
        ? "gold"
        : "danger";

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        À surveiller
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <InsightCardButton
          tone={alertTone}
          icon={<BellIcon />}
          label="Alertes"
          headline={
            alertsFailed
              ? "Indisponible"
              : severe
                ? `${formatAlertCount(severe.count)} — ${ALERT_LABELS_FR[severe.kind]}`
                : "Aucune alerte"
          }
          sub={
            alertsFailed
              ? "Réessayez plus tard"
              : alertsCount > 0
                ? `${alertsCount} alerte${alertsCount > 1 ? "s" : ""} active${alertsCount > 1 ? "s" : ""} au total`
                : "Tout va bien"
          }
          expanded={expanded === "alertes"}
          onClick={() => toggle("alertes")}
        />

        <InsightCardButton
          tone="gold"
          icon={<ChartIcon />}
          label="Fréquentation & équipe"
          headline={
            attendanceToday
              ? `${formatCountDelta(attendanceToday)} vs hier`
              : "Indisponible"
          }
          sub={
            attendanceToday
              ? `${attendanceToday.current} client${attendanceToday.current > 1 ? "s" : ""} aujourd'hui`
              : "Réessayez plus tard"
          }
          expanded={expanded === "analyse"}
          onClick={() => toggle("analyse")}
        />

        <InsightCardButton
          tone="accent"
          icon={<CoinIcon />}
          label="Chiffre d'affaires"
          headline={
            revenueThisWeek
              ? `${formatMoneyDelta(revenueThisWeek)} vs semaine dernière`
              : formatRevenueTotal(revenueSummary.week)
          }
          sub={
            revenueThisWeek
              ? `${formatRevenueTotal(revenueSummary.week)} cette semaine`
              : "Tendance indisponible"
          }
          expanded={expanded === "chiffre-affaires"}
          onClick={() => toggle("chiffre-affaires")}
        />

        <InsightCardButton
          tone={demandFailed ? "gold" : "palm"}
          icon={<ScissorsIcon />}
          label="Prestations les plus demandées"
          headline={
            demandFailed
              ? "Indisponible"
              : topServiceThisWeek
                ? topServiceThisWeek.name
                : "Aucune donnée"
          }
          sub={
            demandFailed
              ? "Réessayez plus tard"
              : topServiceThisWeek
                ? `${formatOccurrences(topServiceThisWeek.volume)} cette semaine`
                : "Pas encore de prestation réalisée"
          }
          expanded={expanded === "prestations"}
          onClick={() => toggle("prestations")}
        />
      </div>

      {expanded === "alertes" ? (
        <DetailPanel title="Alertes importantes" onClose={() => setExpanded(null)}>
          <AlertsPanel alerts={alerts} />
        </DetailPanel>
      ) : null}

      {expanded === "analyse" ? (
        <DetailPanel title="Fréquentation & équipe" onClose={() => setExpanded(null)}>
          <div className="flex flex-col gap-4">
            <AttendanceChart series={attendanceSeries} />
            <HairdresserPerformancePanel report={hairdresserReport} />
          </div>
        </DetailPanel>
      ) : null}

      {expanded === "chiffre-affaires" ? (
        <DetailPanel title="Chiffre d'affaires" onClose={() => setExpanded(null)}>
          <div className="flex flex-col gap-4">
            <RevenueTiles summary={revenueSummary} />
            <p className="-mt-2 text-xs text-muted">
              Ces totaux restent toujours à jour, quelle que soit la période
              sélectionnée ci-dessus — seule l&apos;évolution ci-dessous en
              tient compte.
            </p>
            <RevenueChart series={revenueSeries} />
          </div>
        </DetailPanel>
      ) : null}

      {expanded === "prestations" ? (
        <DetailPanel title="Prestations les plus demandées" onClose={() => setExpanded(null)}>
          <ServiceDemandPanel ranking={serviceDemandRanking} />
        </DetailPanel>
      ) : null}
    </div>
  );
}

const TONE_CLASSES: Record<
  "danger" | "gold" | "palm" | "accent",
  { border: string; iconBg: string; iconText: string }
> = {
  danger: {
    border: "border-danger/25 bg-danger/[0.04]",
    iconBg: "bg-danger/10",
    iconText: "text-danger",
  },
  gold: {
    border: "border-gold/25",
    iconBg: "bg-gold/10",
    iconText: "text-gold",
  },
  accent: {
    border: "border-accent/25",
    iconBg: "bg-accent/10",
    iconText: "text-accent",
  },
  palm: {
    border: "border-palm/25",
    iconBg: "bg-palm/10",
    iconText: "text-palm",
  },
};

function InsightCardButton({
  tone,
  icon,
  label,
  headline,
  sub,
  expanded,
  onClick,
}: {
  tone: "danger" | "gold" | "palm" | "accent";
  icon: React.ReactNode;
  label: string;
  headline: string;
  sub: string;
  expanded: boolean;
  onClick: () => void;
}) {
  const toneClasses = TONE_CLASSES[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      className={`flex cursor-pointer flex-col gap-2 rounded-2xl border p-5 text-left shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated ${
        expanded ? "ring-2 ring-accent/40" : ""
      } ${toneClasses.border} bg-surface`}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className={`flex size-8 shrink-0 items-center justify-center rounded-lg ${toneClasses.iconBg} ${toneClasses.iconText}`}
        >
          {icon}
        </span>
        <ChevronIcon
          className={`text-muted transition-transform ${expanded ? "rotate-90" : ""}`}
        />
      </div>
      <span className="text-xs font-semibold tracking-[0.1em] text-muted uppercase">
        {label}
      </span>
      <span className="text-lg font-semibold text-foreground">{headline}</span>
      <span className="text-xs text-muted">{sub}</span>
    </button>
  );
}

function DetailPanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-soft">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="font-serif text-lg font-semibold text-ink">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
        >
          <XIcon className="shrink-0" />
          Fermer
        </button>
      </div>
      {children}
    </div>
  );
}

function BellIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className="size-4" aria-hidden>
      <path d="M10 3.5c-2.5 0-4 2-4 4.5v2.5L4.5 13h11L14 10.5V8c0-2.5-1.5-4.5-4-4.5Z" />
      <path d="M8.3 15.5a1.8 1.8 0 0 0 3.4 0" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className="size-4" aria-hidden>
      <path d="M3.5 16.5V9M8 16.5V5.5M12.5 16.5v-7M17 16.5V3.5" />
    </svg>
  );
}

function CoinIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className="size-4" aria-hidden>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v8M7.5 8.2c0-1.1 1-1.7 2.5-1.7s2.5.7 2.5 1.7c0 2.3-5 1.3-5 3.6 0 1 1 1.7 2.5 1.7s2.5-.6 2.5-1.7" />
    </svg>
  );
}

function ScissorsIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className="size-4" aria-hidden>
      <circle cx="5.3" cy="5.3" r="2.1" />
      <circle cx="5.3" cy="14.7" r="2.1" />
      <path d="M16.5 3.5 6.9 9.2M6.9 10.8l9.6 5.7" />
    </svg>
  );
}

function ChevronIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className={`size-4 shrink-0 ${className}`} aria-hidden>
      <path d="M7.5 4.5 13 10l-5.5 5.5" />
    </svg>
  );
}
