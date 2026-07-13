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
    <form className="login-form" onSubmit={onSubmit} noValidate>
      <label className="login-field">
        <span>Identifiant (téléphone ou e-mail)</span>
        <input
          type="text"
          name="identifier"
          autoComplete="username"
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
          required
        />
      </label>
      <label className="login-field">
        <span>Mot de passe</span>
        <input
          type="password"
          name="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
      </label>
      {error ? (
        <p className="login-error" role="alert">
          {error}
        </p>
      ) : null}
      <button type="submit" className="login-submit" disabled={pending}>
        {pending ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}
