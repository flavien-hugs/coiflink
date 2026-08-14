// Mes tickets — zone coiffeur (adapter entrant + composition root, Server
// Component). Remplace « Mon planning » : le modèle RDV a été retiré côté
// backend au profit d'un modèle walk-in exclusif (`QueueTicket`) et la route
// qu'appelait l'ancienne page (`GET /appointments/assigned`) n'existe plus.
//
// Il n'existe pas de route backend « mes tickets » dédiée équivalente : on
// réutilise `GET /salons/{id}/queue/tickets` — **la même route que le gérant**
// (permission `QUEUE_TICKET_READ_SALON`, déjà accordée au rôle HAIRDRESSER
// côté backend, comme confirmé pour ce chantier) — et on filtre **côté page**
// sur le principal courant :
//   - le ticket `in_progress` déjà assigné à ce coiffeur (à terminer) ;
//   - tous les tickets `waiting`/`called` du salon, assignés ou non — un
//     coiffeur doit pouvoir prendre en charge n'importe quel ticket en
//     attente, pas seulement ceux qui lui seraient pré-assignés (US-8.3, #157).
// Si le backend refuse (403), l'écran d'erreur générique s'affiche — aucune
// divulgation du motif précis, comme partout ailleurs dans l'app.
//
// Résout d'abord le salon d'appartenance du coiffeur via `SalonGateway.list()`
// (salons rattachés au principal authentifié, même mécanisme que la zone
// gérant) : un coiffeur salarié n'a qu'un seul salon, on prend le premier.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAuthGateway } from "@/src/adapters/api/http-auth-gateway";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { AutoRefresh } from "@/src/adapters/ui/auto-refresh";
import { CoiffeurTicketBoard } from "@/src/adapters/ui/coiffeur-ticket-board";

export default async function CoiffeurTicketsPage() {
  const { accessToken } = await createCookieSessionStore().read();

  const [userResult, salonsResult] = await Promise.all([
    createHttpAuthGateway({ accessToken }).getCurrentUser(),
    createHttpSalonGateway({ accessToken }).list(),
  ]);

  if (userResult.status !== "authenticated" || !salonsResult.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }

  const salon = salonsResult.salons[0];
  if (!salon) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <NoSalonPanel />
      </section>
    );
  }

  const queueResult = await createHttpQueueGateway({ accessToken }).listQueue(salon.id);
  if (!queueResult.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }

  const hairdresserId = userResult.user.id;
  const currentTicket =
    queueResult.items.find(
      (ticket) => ticket.status === "in_progress" && ticket.hairdresserId === hairdresserId,
    ) ?? null;
  const waitingTickets = queueResult.items.filter(
    (ticket) => ticket.status === "waiting" || ticket.status === "called",
  );

  // Nom complet de la cliente prise en charge — exposition étroite (jamais
  // pour la file d'attente, jamais le téléphone) : une seule résolution
  // serveur, ticket anonyme ou absence de ticket en cours → `null`, la carte
  // retombe alors sur le prénom seul déjà porté par `currentTicket`.
  const currentTicketCustomerFullName =
    currentTicket?.customerProfileId != null
      ? await resolveCustomerFullName(accessToken, salon.id, currentTicket.ticketId)
      : null;

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Header />
        <AutoRefresh />
      </div>
      <CoiffeurTicketBoard
        salonId={salon.id}
        hairdresserId={hairdresserId}
        currentTicket={currentTicket}
        currentTicketCustomerFullName={currentTicketCustomerFullName}
        waitingTickets={waitingTickets}
      />
    </section>
  );
}

async function resolveCustomerFullName(
  accessToken: string | null | undefined,
  salonId: string,
  ticketId: string,
): Promise<string | null> {
  const result = await createHttpQueueGateway({ accessToken }).getAssignedTicketCustomer(
    salonId,
    ticketId,
  );
  return result.ok ? result.fullName : null;
}

function Header() {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">Mes tickets</h1>
      <p className="mt-1 text-sm text-muted">
        Le ticket que vous avez en cours, et les clientes en attente que vous pouvez prendre en
        charge.
      </p>
    </div>
  );
}

function ErrorPanel() {
  return (
    <div
      className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
      role="alert"
    >
      Impossible de charger vos tickets pour le moment. Veuillez réessayer plus tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Aucun salon rattaché à votre compte</h2>
      <p className="mt-1 text-sm text-muted">
        Contactez votre gérant : votre compte doit être rattaché à un salon pour voir la file
        d&apos;attente.
      </p>
      <Link
        href="/coiffeur/tickets"
        className="mt-4 inline-flex items-center justify-center rounded-lg border border-border px-4 py-2.5 font-semibold text-foreground shadow-soft transition hover:-translate-y-0.5"
      >
        Réessayer
      </Link>
    </div>
  );
}
