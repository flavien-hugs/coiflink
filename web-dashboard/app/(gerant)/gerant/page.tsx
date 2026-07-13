// Dashboard gérant — **page vide mais protégée** (#14). Rendue uniquement à un
// gérant authentifié (garde du layout `(gerant)`). Aucune donnée métier : les
// indicateurs, planning, caisse, etc. arriveront avec les issues M2–M5 (PRD §7.2).

export default function GerantDashboardPage() {
  return (
    <section className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Tableau de bord</h1>
      <div className="rounded-2xl border border-dashed border-border p-10 text-center">
        <p className="text-sm font-medium tracking-[0.14em] text-accent uppercase">Bientôt disponible</p>
        <p className="mx-auto mt-2 max-w-md text-muted">
          Bienvenue sur votre espace de gestion CoifLink. Les indicateurs, le planning et les
          sections du salon arriveront prochainement.
        </p>
      </div>
    </section>
  );
}
