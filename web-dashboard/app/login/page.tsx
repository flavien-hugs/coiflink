// Écran de connexion minimal (public) — hors zone `/gerant`. Point d'entrée de
// session : établit une session via le Route Handler BFF puis redirige vers
// /gerant. L'UX aboutie (design, « mot de passe oublié » relié à #11) relève
// d'une issue distincte (#14 se limite au minimum démontrant la garde).

import { LoginForm } from "@/src/adapters/ui/login-form";

export default function LoginPage() {
  return (
    <main className="login-screen">
      <h1>Connexion</h1>
      <p>Connectez-vous pour accéder à votre tableau de bord.</p>
      <LoginForm />
    </main>
  );
}
