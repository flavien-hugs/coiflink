"use client";

// Formulaire de coiffeuse (ajout **ou** édition de profil) — adapter UI
// (hexagonal, ADR-0008). Valide **côté client** (parité domaine, retour
// immédiat) puis poste vers le Route Handler BFF `/api/salons/{id}/employees`
// (POST) ou `/api/salons/{id}/employees/{employeeId}` (PUT), qui proxifie le
// backend avec le jeton du cookie httpOnly. En cas de succès, rafraîchit la
// page. Messages génériques ; aucune PII journalisée. Le backend reste
// l'autorité (#13/#150). **Aucun champ statut** : la disponibilité se pilote
// depuis le tableau (activer/désactiver), jamais depuis ce formulaire.

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import {
  CalendarIcon,
  CheckIcon,
  EyeIcon,
  EyeOffIcon,
  LockIcon,
  MailIcon,
  PersonIcon,
  PhoneIcon,
  TagIcon,
  XIcon,
} from "@/src/adapters/ui/action-icons";
import { FieldLabel } from "@/src/adapters/ui/field-label";
import {
  validateCreateEmployee,
  validateUpdateEmployeeProfile,
  type Employee,
} from "@/src/domain/employee/employee";

// `w-full` est **nécessaire** (pas seulement stylistique) : le `<input>` est
// imbriqué dans un `<div className="relative">`, lui-même l'enfant flex
// étiré (le `<label>` parent est `flex flex-col` — `align-items: stretch`
// s'applique au `<div>`, pas à l'`<input>` qu'il contient). Sans `w-full`,
// l'`<input>` garde sa largeur intrinsèque (`size=20` du navigateur) tandis
// que l'icône/bouton **positionnés en absolu** restent calés sur les bords du
// `<div>`, désormais plus large que le champ visible — l'icône/bouton
// semblent alors « hors du champ » plutôt qu'à l'intérieur.
const INPUT_WITH_ICON_CLASS =
  "w-full rounded-lg border border-border bg-surface py-2.5 pl-9 pr-3 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";
// Icône descriptive à gauche **et** bouton afficher/masquer à droite — seul
// champ de ce formulaire à combiner les deux, d'où une variante dédiée de
// `INPUT_WITH_ICON_CLASS` (pr-10 au lieu de pr-3, pour laisser la place au
// bouton plutôt qu'à une icône purement décorative). Même nécessité de
// `w-full` que ci-dessus.
const PASSWORD_INPUT_CLASS =
  "w-full rounded-lg border border-border bg-surface py-2.5 pl-9 pr-10 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface EmployeeFormProps {
  salonId: string;
  // Coiffeuse à éditer ; absente pour une création.
  employee?: Employee;
  onSaved?: () => void;
  onCancel?: () => void;
}

export function EmployeeForm({ salonId, employee, onCancel, onSaved }: EmployeeFormProps) {
  const router = useRouter();
  const editing = employee != null;
  const [fullName, setFullName] = useState(employee?.fullName ?? "");
  const [phone, setPhone] = useState(employee?.phone ?? "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState(employee?.email ?? "");
  const [specialties, setSpecialties] = useState(employee?.specialties ?? "");
  const [hiredAt, setHiredAt] = useState(employee?.hiredAt ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const raw = { fullName, phone, password, email, specialties, hiredAt };
    const validated = editing
      ? validateUpdateEmployeeProfile(raw)
      : validateCreateEmployee(raw);
    if (!validated.ok) {
      switch (validated.reason) {
        case "invalid-name":
          setError("Le nom est requis (255 caractères max).");
          break;
        case "invalid-phone":
          setError("Le téléphone est requis et doit être exploitable.");
          break;
        case "invalid-password":
          setError("Le mot de passe initial doit contenir entre 8 et 128 caractères.");
          break;
        default:
          setError("Les spécialités ne doivent pas dépasser 1000 caractères.");
      }
      return;
    }

    setPending(true);
    try {
      const url = editing
        ? `/api/salons/${encodeURIComponent(salonId)}/employees/${encodeURIComponent(employee.id)}`
        : `/api/salons/${encodeURIComponent(salonId)}/employees`;
      const response = await fetch(url, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(validated.value),
      });

      if (response.ok) {
        if (!editing) {
          setFullName("");
          setPhone("");
          setPassword("");
          setEmail("");
          setSpecialties("");
          setHiredAt("");
        }
        router.refresh();
        onSaved?.();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Coiffeuse introuvable.");
      } else if (response.status === 409) {
        setError("Ce téléphone ou cet e-mail est déjà utilisé par un autre compte.");
      } else if (response.status === 422 || response.status === 400) {
        setError("Coiffeuse invalide.");
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
        <FieldLabel required>Nom complet</FieldLabel>
        <div className="relative">
          <PersonIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="text"
            name="fullName"
            className={INPUT_WITH_ICON_CLASS}
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            maxLength={255}
            required
          />
        </div>
      </label>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel required>Téléphone</FieldLabel>
          <div className="relative">
            <PhoneIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="tel"
              name="phone"
              className={INPUT_WITH_ICON_CLASS}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="0700000000"
              required
            />
          </div>
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>E-mail</FieldLabel>
          <div className="relative">
            <MailIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="email"
              name="email"
              className={INPUT_WITH_ICON_CLASS}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="awa@example.com"
            />
          </div>
        </label>
      </div>
      {!editing ? (
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel required>Mot de passe initial</FieldLabel>
          <div className="relative">
            <LockIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type={showPassword ? "text" : "password"}
              name="password"
              className={PASSWORD_INPUT_CLASS}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              maxLength={128}
              autoComplete="new-password"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
              className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer text-muted transition hover:text-foreground"
            >
              {showPassword ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
          <p className="text-xs font-normal text-muted">
            8 caractères minimum. La coiffeuse pourra le changer à sa connexion.
          </p>
        </label>
      ) : null}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Spécialités</FieldLabel>
          <div className="relative">
            <TagIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              name="specialties"
              className={INPUT_WITH_ICON_CLASS}
              value={specialties}
              onChange={(e) => setSpecialties(e.target.value)}
              maxLength={1000}
              placeholder="Tresses, colorations, lissages"
            />
          </div>
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          <FieldLabel optional>Date d&apos;embauche</FieldLabel>
          <div className="relative">
            <CalendarIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="date"
              name="hiredAt"
              className={`${INPUT_WITH_ICON_CLASS} cursor-pointer`}
              value={hiredAt ?? ""}
              onChange={(e) => setHiredAt(e.target.value)}
            />
          </div>
        </label>
      </div>
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
          {pending
            ? "Enregistrement…"
            : editing
              ? "Enregistrer les modifications"
              : "Ajouter la coiffeuse"}
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
