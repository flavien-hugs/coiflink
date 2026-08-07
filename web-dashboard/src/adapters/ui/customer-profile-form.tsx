"use client";

// Éditeur de l'**identité** d'une fiche client — adapter UI (hexagonal,
// ADR-0008, US-4.6 #144). Pré-remplit les champs nom/téléphone/genre avec les
// valeurs courantes, valide **côté client** (parité domaine, retour immédiat)
// puis poste vers le Route Handler BFF `PATCH /api/salons/{id}/customers/{id}`,
// qui proxifie le backend avec le jeton du cookie httpOnly (invariant #14). En
// cas de succès, rafraîchit la page (`router.refresh()`) puis referme le
// panneau (`onSaved`, mode drawer — icône « Modifier » de chaque ligne du
// tableau, `CustomerList`).
//
// **Seule l'identité** est éditée ici : la note privée garde son éditeur dédié
// (#32). Le nom reste obligatoire ; vider le téléphone ou le genre efface le
// champ. Le téléphone est **unique au sein du salon** : un doublon renvoie un
// message neutre (`409`, sans rappeler le numéro, PRD §11.3). Messages
// génériques ; aucune PII journalisée. Le backend reste l'autorité (#144).

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { CheckIcon, PersonIcon, PhoneIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { FieldLabel } from "@/src/adapters/ui/field-label";
import { SearchableSelect } from "@/src/adapters/ui/searchable-select";
import {
  CUSTOMER_NAME_MAX_LENGTH,
  GENDER_OPTIONS,
  validateCustomer,
} from "@/src/domain/customer/customer";

const INPUT_WITH_ICON_CLASS =
  "rounded-lg border border-border bg-surface py-2.5 pl-9 pr-3 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface CustomerProfileFormProps {
  salonId: string;
  customerId: string;
  // Valeurs courantes de la fiche (pré-remplissage). `null` = non renseigné.
  initialFullName: string;
  initialPhone: string | null;
  initialGender: string | null;
  // Fermer le panneau après un enregistrement réussi (mode drawer).
  onSaved?: () => void;
  // Fermer le formulaire sans enregistrer (mode drawer).
  onCancel?: () => void;
}

export function CustomerProfileForm({
  salonId,
  customerId,
  initialFullName,
  initialPhone,
  initialGender,
  onCancel,
  onSaved,
}: CustomerProfileFormProps) {
  const router = useRouter();
  const [fullName, setFullName] = useState(initialFullName);
  const [phone, setPhone] = useState(initialPhone ?? "");
  const [gender, setGender] = useState(initialGender ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaved(false);

    // `notes: null` : l'éditeur d'identité ne touche pas la note (route #32).
    const validated = validateCustomer({ fullName, phone, gender, notes: null });
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
        default:
          setError("Le genre sélectionné est invalide.");
      }
      return;
    }

    setPending(true);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/customers/${encodeURIComponent(customerId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            full_name: validated.value.fullName,
            phone: validated.value.phone,
            gender: validated.value.gender,
          }),
        },
      );

      if (response.ok) {
        setSaved(true);
        router.refresh();
        onSaved?.();
        return;
      }
      if (response.status === 409) {
        setError("Une fiche existe déjà pour ce numéro dans ce salon.");
      } else if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Fiche client introuvable.");
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
            onChange={(e) => {
              setFullName(e.target.value);
              setSaved(false);
            }}
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
              onChange={(e) => {
                setPhone(e.target.value);
                setSaved(false);
              }}
              placeholder="07 00 00 00 00"
            />
          </div>
          <span className="text-xs font-normal text-muted">
            Unique au sein du salon. Laisser vide pour retirer le numéro.
          </span>
        </label>
        <div className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Genre</FieldLabel>
          <SearchableSelect
            ariaLabel="Genre"
            value={gender}
            options={GENDER_OPTIONS}
            onChange={(value) => {
              setGender(value);
              setSaved(false);
            }}
            placeholder="Non renseigné"
            searchPlaceholder="Rechercher un genre"
            emptyLabel="Aucun genre trouvé"
          />
        </div>
      </div>
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      {saved && !error ? (
        <p className="text-sm text-muted" role="status">
          Informations enregistrées.
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          disabled={pending}
        >
          {pending ? null : <CheckIcon className="shrink-0" />}
          {pending ? "Enregistrement…" : "Enregistrer les modifications"}
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
