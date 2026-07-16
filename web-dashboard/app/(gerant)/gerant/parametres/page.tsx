// Paramètres du salon — adapter entrant + composition root (Server Component,
// #15). Charge les salons du gérant **côté serveur** (jeton du cookie httpOnly,
// jamais exposé au navigateur, invariant #14) :
//   - aucun salon → formulaire de création (`SalonForm`) ;
//   - un salon    → fiche « Informations générales / Localisation ».
// Tant que `isBookable === false` (§8.3 : pas d'horaire ⇒ non réservable), un
// bandeau explicite invite à configurer les horaires (l'objet de #16).
//
// PRD §7.2 range « Informations générales · Horaires · Photos · Localisation »
// dans **Paramètres** : cette page occupe cette section (pas de 8ᵉ entrée de nav).

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { OpeningHoursForm } from "@/src/adapters/ui/opening-hours-form";
import { SalonForm } from "@/src/adapters/ui/salon-form";
import { isBookable, type Salon } from "@/src/domain/salon/salon";

export default async function ParametresPage() {
  const { accessToken } = await createCookieSessionStore().read();
  const result = await createHttpSalonGateway({ accessToken }).list();

  if (!result.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <div
          className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
          role="alert"
        >
          Impossible de charger votre salon pour le moment. Veuillez réessayer plus tard.
        </div>
      </section>
    );
  }

  const salon = result.salons[0];

  return (
    <section className="flex flex-col gap-6">
      <Header />
      {salon ? <SalonDetails salon={salon} /> : <CreatePanel />}
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Paramètres du salon</h1>
      <p className="mt-1 text-sm text-muted">
        Informations générales, localisation et photos de votre salon.
      </p>
    </div>
  );
}

function CreatePanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créer votre salon</h2>
      <p className="mt-1 mb-5 max-w-prose text-sm text-muted">
        Renseignez les informations de votre salon. Vous pourrez ajouter votre logo, vos
        photos et vos horaires d&apos;ouverture ensuite.
      </p>
      <SalonForm />
    </div>
  );
}

function SalonDetails({ salon }: { salon: Salon }) {
  const bookable = isBookable(salon);

  return (
    <div className="flex flex-col gap-6">
      {!bookable ? (
        <div
          className="rounded-2xl border border-accent/30 bg-accent/10 p-4 text-sm text-foreground"
          role="status"
        >
          <p className="font-semibold text-accent">
            Ce salon n&apos;est pas encore réservable.
          </p>
          <p className="mt-1 text-muted">
            Configurez vos horaires d&apos;ouverture pour rendre votre salon réservable par
            les clients.
          </p>
        </div>
      ) : null}

      <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{salon.name}</h2>
            {salon.description ? (
              <p className="mt-1 max-w-prose text-sm text-muted">{salon.description}</p>
            ) : null}
          </div>
          <span className="rounded-full bg-foreground/5 px-2.5 py-1 text-xs font-medium tracking-wide uppercase">
            {salon.status}
          </span>
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
      </div>

      <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
        <h2 className="text-lg font-semibold">Horaires d&apos;ouverture</h2>
        <p className="mt-1 mb-5 max-w-prose text-sm text-muted">
          Définissez vos horaires par jour (avec pauses éventuelles), vos jours fermés
          et vos jours exceptionnels. Enregistrer des horaires rend votre salon
          réservable par les clients.
        </p>
        <OpeningHoursForm salonId={salon.id} openingHours={salon.openingHours} />
      </div>
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
