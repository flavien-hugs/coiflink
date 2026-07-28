"use client";

// Éditeur de la **note privée** d'une fiche client — adapter UI (hexagonal,
// ADR-0008, US-4.5 #32). Pré-remplit une `<textarea>` avec la note courante,
// valide **côté client** (parité domaine, retour immédiat) puis poste vers le
// Route Handler BFF `PUT /api/salons/{id}/customers/{customerId}`, qui proxifie
// le backend avec le jeton du cookie httpOnly. En cas de succès, rafraîchit la
// page (`router.refresh()`).
//
// La note est **interne au salon** : la mention l'indique explicitement (PRD
// §11.3, critère d'acceptation « non visible du client »). « Effacer » vide le
// champ et enregistre une note nulle (`null`) : « éditer » couvre « retirer ».
// Messages génériques ; aucune PII journalisée. Le backend reste l'autorité (#32).

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FieldLabel } from "@/src/adapters/ui/field-label";
import { NOTES_MAX_LENGTH, validateNote } from "@/src/domain/customer/customer";

const INPUT_CLASS =
  "rounded-lg border border-border bg-surface px-3 py-2.5 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface CustomerNoteFormProps {
  salonId: string;
  customerId: string;
  // Note actuellement enregistrée (pré-remplissage) ; `null` = aucune note.
  initialNotes: string | null;
}

export function CustomerNoteForm({
  salonId,
  customerId,
  initialNotes,
}: CustomerNoteFormProps) {
  const router = useRouter();
  const [notes, setNotes] = useState(initialNotes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);

  async function save(value: string) {
    setError(null);
    setSaved(false);

    const validated = validateNote(value);
    if (!validated.ok) {
      setError(
        `Les notes internes ne doivent pas dépasser ${NOTES_MAX_LENGTH} caractères.`,
      );
      return;
    }

    setPending(true);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/customers/${encodeURIComponent(customerId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ notes: validated.value }),
        },
      );

      if (response.ok) {
        setNotes(validated.value ?? "");
        setSaved(true);
        router.refresh();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Fiche client introuvable.");
      } else if (response.status === 422 || response.status === 400) {
        setError("Note invalide.");
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

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await save(notes);
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={onSubmit} noValidate>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <FieldLabel optional>Note privée</FieldLabel>
        <textarea
          name="notes"
          className={INPUT_CLASS}
          value={notes}
          onChange={(e) => {
            setNotes(e.target.value);
            setSaved(false);
          }}
          maxLength={NOTES_MAX_LENGTH}
          rows={3}
          placeholder="Préférences, allergies, habitudes…"
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
      {saved && !error ? (
        <p className="text-sm text-muted" role="status">
          Note enregistrée.
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="inline-flex cursor-pointer items-center justify-center rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          disabled={pending}
        >
          {pending ? "Enregistrement…" : "Enregistrer la note"}
        </button>
        <button
          type="button"
          className="text-sm font-medium text-muted hover:text-foreground disabled:opacity-60"
          onClick={() => {
            setNotes("");
            void save("");
          }}
          disabled={pending || notes.trim().length === 0}
        >
          Effacer
        </button>
      </div>
    </form>
  );
}
