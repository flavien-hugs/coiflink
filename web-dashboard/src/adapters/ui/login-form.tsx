"use client";

// Formulaire de connexion minimal — adapter UI (hexagonal, ADR-0008). Poste
// identifiant + mot de passe vers le Route Handler BFF `POST /api/auth/login`
// (qui proxifie `POST /auth/login` et pose les cookies httpOnly). En cas de
// succès, redirige vers `/` : la racine route ensuite **côté serveur** vers la
// zone du rôle (`/gerant` pour un gérant, `/coiffeur/planning` pour un coiffeur —
// #27), sans divulguer de contenu privé. Les messages d'erreur restent
// **génériques** (aucun détail sensible) ; identifiant et mot de passe ne sont
// jamais journalisés.

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { LoginIcon, MailIcon, PhoneIcon } from "@/src/adapters/ui/action-icons";

type IdentifierType = "phone" | "email";

export function LoginForm() {
  const router = useRouter();
  const [identifierType, setIdentifierType] = useState<IdentifierType>("phone");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Change de type d'identifiant réinitialise la saisie : éviter qu'une valeur
  // au format téléphone se retrouve sous l'onglet e-mail (et inversement). Le
  // backend accepte toujours un seul champ `identifier` (§ auth) — ces onglets
  // ne sont qu'un guidage de saisie (icône/clavier/placeholder adaptés).
  function switchIdentifierType(type: IdentifierType) {
    if (type === identifierType) return;
    setIdentifierType(type);
    setIdentifier("");
    setError(null);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, password }),
      });

      if (response.ok) {
        router.replace("/");
        router.refresh();
        return;
      }

      if (response.status === 429) {
        setError("Trop de tentatives. Veuillez réessayer plus tard.");
      } else if (response.status === 503) {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      } else {
        setError("Identifiants invalides.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="mt-6 flex flex-col gap-4" onSubmit={onSubmit} noValidate>
      <div className="flex flex-col gap-1.5 text-sm font-medium">
        <span id="identifier-label">Identifiant</span>
        <div
          role="tablist"
          aria-label="Type d'identifiant"
          className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-surface p-1"
        >
          <button
            type="button"
            role="tab"
            aria-selected={identifierType === "phone"}
            onClick={() => switchIdentifierType("phone")}
            className={`cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium transition ${
              identifierType === "phone"
                ? "bg-accent text-accent-foreground shadow-soft"
                : "text-muted hover:text-foreground"
            }`}
          >
            Téléphone
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={identifierType === "email"}
            onClick={() => switchIdentifierType("email")}
            className={`cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium transition ${
              identifierType === "email"
                ? "bg-accent text-accent-foreground shadow-soft"
                : "text-muted hover:text-foreground"
            }`}
          >
            E-mail
          </button>
        </div>
        <div className="relative">
          {identifierType === "email" ? (
            <MailIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          ) : (
            <PhoneIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          )}
          <input
            key={identifierType}
            id="identifier"
            aria-labelledby="identifier-label"
            type={identifierType === "email" ? "email" : "tel"}
            inputMode={identifierType === "email" ? "email" : "tel"}
            name="identifier"
            autoComplete={identifierType === "email" ? "email" : "tel"}
            placeholder={identifierType === "email" ? "vous@exemple.com" : "07 01 02 03 04"}
            className="w-full rounded-lg border border-border bg-transparent py-2.5 pl-9 pr-3 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25"
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            required
          />
        </div>
      </div>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <span>Mot de passe</span>
        <div className="relative">
          <LockIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type={showPassword ? "text" : "password"}
            name="password"
            autoComplete="current-password"
            className="w-full rounded-lg border border-border bg-transparent py-2.5 pl-9 pr-10 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <button
            type="button"
            className="absolute right-2.5 top-1/2 flex -translate-y-1/2 cursor-pointer items-center justify-center text-muted transition hover:text-foreground"
            aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
            aria-pressed={showPassword}
            onClick={() => setShowPassword((current) => !current)}
          >
            {showPassword ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        </div>
      </label>
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        className="mt-1 inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
        disabled={pending}
      >
        {pending ? null : <LoginIcon className="shrink-0" />}
        {pending ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}

function LockIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className={`size-4 ${className}`}
      aria-hidden="true"
    >
      <rect x="4.5" y="9" width="11" height="7.5" rx="1.5" />
      <path d="M6.5 9V6.5a3.5 3.5 0 0 1 7 0V9" strokeLinecap="round" />
    </svg>
  );
}

function EyeIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className={`size-4.5 ${className}`}
      aria-hidden="true"
    >
      <path
        d="M1.5 10S4.5 4.5 10 4.5 18.5 10 18.5 10 15.5 15.5 10 15.5 1.5 10 1.5 10Z"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="10" r="2.25" />
    </svg>
  );
}

function EyeOffIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className={`size-4.5 ${className}`}
      aria-hidden="true"
    >
      <path
        d="M1.5 10S4.5 4.5 10 4.5c1.42 0 2.66.32 3.72.82M18.5 10S15.5 15.5 10 15.5c-1.42 0-2.66-.32-3.72-.82"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M7.6 7.6a2.25 2.25 0 0 0 3.18 3.18" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2.5 2.5l15 15" strokeLinecap="round" />
    </svg>
  );
}
