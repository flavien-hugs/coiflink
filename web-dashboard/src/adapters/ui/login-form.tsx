"use client";

// Formulaire de connexion minimal — adapter UI (hexagonal, ADR-0008). Poste
// identifiant + mot de passe vers le Route Handler BFF `POST /api/auth/login`
// (qui proxifie `POST /auth/login` et pose les cookies httpOnly). En cas de
// succès, redirige vers /gerant. Les messages d'erreur restent **génériques**
// (aucun détail sensible) ; identifiant et mot de passe ne sont jamais
// journalisés.

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

export function LoginForm() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

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
        router.replace("/gerant");
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
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <span>Identifiant (téléphone ou e-mail)</span>
        <input
          type="text"
          name="identifier"
          autoComplete="username"
          className="rounded-lg border border-border bg-transparent px-3 py-2.5 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25"
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
          required
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        <span>Mot de passe</span>
        <input
          type="password"
          name="password"
          autoComplete="current-password"
          className="rounded-lg border border-border bg-transparent px-3 py-2.5 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
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
        className="mt-1 inline-flex cursor-pointer items-center justify-center rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
        disabled={pending}
      >
        {pending ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}
