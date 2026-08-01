"use client";

// Formulaire de création d'une fiche client — adapter UI (hexagonal, ADR-0008).
// Valide **côté client** (parité domaine, retour immédiat) puis poste vers le
// Route Handler BFF `/api/salons/{id}/customers`, qui proxifie le backend avec
// le jeton du cookie httpOnly. En cas de succès, rafraîchit la page.
//
// Seul le nom est obligatoire (US-4.1) ; le téléphone est **recommandé** (il
// rattache les visites à venir, #29) mais reste optionnel pour ficher un client
// de passage. Les notes sont **internes au salon** — la mention l'indique
// explicitement à la saisie (PRD §11.3). Messages génériques ; aucune PII
// journalisée. Le backend reste l'autorité (#28).

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { CheckIcon, PersonIcon, PhoneIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { FieldLabel } from "@/src/adapters/ui/field-label";
import { SearchableSelect } from "@/src/adapters/ui/searchable-select";
import {
  CUSTOMER_NAME_MAX_LENGTH,
  GENDER_OPTIONS,
  NOTES_MAX_LENGTH,
  validateCustomer,
} from "@/src/domain/customer/customer";

const INPUT_CLASS =
  "rounded-lg border border-border bg-surface px-3 py-2.5 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";
const INPUT_WITH_ICON_CLASS =
  "rounded-lg border border-border bg-surface py-2.5 pl-9 pr-3 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface CustomerFormProps {
  salonId: string;
  // Fermer le panneau après un enregistrement réussi.
  onSaved?: () => void;
  // Fermer le formulaire sans enregistrer.
  onCancel?: () => void;
}

export function CustomerForm({ salonId, onCancel, onSaved }: CustomerFormProps) {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [gender, setGender] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const validated = validateCustomer({ fullName, phone, gender, notes });
    if (!validated.ok) {
      switch (validated.reason) {
        case "invalid-name":
          setError(
            `Le nom du client est requis (${CUSTOMER_NAME_MAX_LENGTH} caractères max).`,
          );
          break;
        case "invalid-phone":
          setError("Le numéro de téléphone saisi n'est pas exploitable.");
          break;
        case "invalid-gender":
          setError("Le genre sélectionné est invalide.");
          break;
        default:
          setError(
            `Les notes internes ne doivent pas dépasser ${NOTES_MAX_LENGTH} caractères.`,
          );
      }
      return;
    }

    setPending(true);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/customers`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(validated.value),
        },
      );

      if (response.ok) {
        setFullName("");
        setPhone("");
        setGender("");
        setNotes("");
        router.refresh();
        onSaved?.();
        return;
      }
      if (response.status === 409) {
        setError("Une fiche existe déjà pour ce numéro dans ce salon.");
      } else if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Salon introuvable.");
      } else if (response.status === 422 || response.status === 400) {
        setError("Fiche client invalide.");
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

  return (
    <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel required>Nom du client</FieldLabel>
        <div className="relative">
          <PersonIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="text"
            name="fullName"
            className={INPUT_WITH_ICON_CLASS}
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            maxLength={CUSTOMER_NAME_MAX_LENGTH}
            required
          />
        </div>
      </label>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Téléphone</FieldLabel>
          <div className="relative">
            <PhoneIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="tel"
              inputMode="tel"
              name="phone"
              className={INPUT_WITH_ICON_CLASS}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="07 00 00 00 00"
            />
          </div>
          <span className="text-xs font-normal text-muted">
            Recommandé : il permet de retrouver la fiche et d&apos;y rattacher les visites.
          </span>
        </label>
        <div className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Genre</FieldLabel>
          <SearchableSelect
            ariaLabel="Genre"
            value={gender}
            options={GENDER_OPTIONS}
            onChange={setGender}
            placeholder="Non renseigné"
            searchPlaceholder="Rechercher un genre"
            emptyLabel="Aucun genre trouvé"
          />
        </div>
      </div>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel optional>Notes internes</FieldLabel>
        <textarea
          name="notes"
          className={INPUT_CLASS}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={NOTES_MAX_LENGTH}
          rows={3}
          placeholder="Préférences, allergies, remarques…"
        />
        <span className="text-xs font-normal text-muted">
          Visible uniquement par le salon — jamais partagé avec le client.
        </span>
      </label>
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          disabled={pending}
        >
          {pending ? null : <CheckIcon className="shrink-0" />}
          {pending ? "Enregistrement…" : "Créer la fiche client"}
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
