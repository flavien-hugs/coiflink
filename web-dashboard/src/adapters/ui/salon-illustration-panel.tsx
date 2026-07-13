// Panneau décoratif « galerie de coiffures » — remplace un fond uni sur les
// écrans publics (accueil, connexion) par une composition illustrée évoquant
// la diversité des textures et styles proposés en salon.

import { HAIRSTYLES, HairstyleBust } from "./hairstyle-bust";

export function SalonIllustrationPanel() {
  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden bg-accent/[0.06] p-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-1/4 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-accent/10 blur-3xl"
      />
      <div className="relative flex max-w-xs flex-wrap justify-center gap-6">
        {HAIRSTYLES.map(({ key, label }) => (
          <div key={key} className="flex w-20 flex-col items-center gap-2">
            <div className="flex size-20 items-center justify-center rounded-full bg-surface p-4 shadow-soft ring-1 ring-border">
              <HairstyleBust hair={key} className="h-full w-full" />
            </div>
            <span className="text-xs font-medium text-muted">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
