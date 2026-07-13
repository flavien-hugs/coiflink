// Dashboard gérant — **page vide mais protégée** (#14). Rendue uniquement à un
// gérant authentifié (garde du layout `(gerant)`). Aucune donnée métier : les
// indicateurs, planning, caisse, etc. arriveront avec les issues M2–M5 (PRD §7.2).

export default function GerantDashboardPage() {
  return (
    <section className="dashboard-home">
      <h1>Tableau de bord</h1>
      <p>
        Bienvenue sur votre espace de gestion CoifLink. Les indicateurs et les sections du salon
        arriveront prochainement.
      </p>
    </section>
  );
}
