// Écran de connexion minimal (public) — hors zone `/gerant`. Point d'entrée de
// session : établit une session via le Route Handler BFF puis redirige vers
// /gerant. L'UX aboutie (design, « mot de passe oublié » relié à #11) relève
// d'une issue distincte (#14 se limite au minimum démontrant la garde).

import { BrandMark, Wordmark } from "@/src/adapters/ui/brand-mark";
import { LoginForm } from "@/src/adapters/ui/login-form";
import { SalonIllustrationPanel } from "@/src/adapters/ui/salon-illustration-panel";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen flex-1">
      <div className="flex flex-1 items-center justify-center bg-white px-6 py-16">
        <div className="w-full max-w-sm rounded-2xl border border-border bg-surface p-8 shadow-elevated">
          <div className="mb-6 flex items-center gap-2.5">
            <BrandMark className="size-9 shrink-0" />
            <Wordmark className="text-xl font-bold tracking-tight" />
          </div>
          <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">Connexion</h1>
          <p className="mt-1.5 text-sm text-muted">
            Connectez-vous pour accéder à votre tableau de bord.
          </p>
          <LoginForm />
        </div>
      </div>
      <div className="hidden flex-1 border-l border-border lg:block">
        <SalonIllustrationPanel />
      </div>
    </main>
  );
}
