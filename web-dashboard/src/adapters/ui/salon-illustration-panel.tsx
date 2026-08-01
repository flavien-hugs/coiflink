// Panneau décoratif « galerie de coiffures » — remplace un fond uni sur les
// écrans publics (accueil, connexion) par une composition illustrée évoquant
// la diversité des textures et styles proposés en salon. Un semis d'icônes en
// arrière-plan (positions fixes, non aléatoires : composant serveur, doit
// rester déterministe entre rendu serveur et client) ajoute une texture
// derrière la légende au premier plan.

import { HAIRSTYLES, HairstyleBust, type Hairstyle } from "./hairstyle-bust";
import { SalonToolIcon, type SalonTool } from "./salon-tool-icons";

type ScatterItem = { top: string; left: string; size: number; rotate: number } & (
  | { kind: "hair"; hair: Hairstyle }
  | { kind: "tool"; tool: SalonTool }
);

const SCATTER: ScatterItem[] = [
  { kind: "hair", hair: "afro", top: "6%", left: "12%", size: 44, rotate: -12 },
  { kind: "hair", hair: "braids", top: "12%", left: "76%", size: 36, rotate: 10 },
  { kind: "hair", hair: "bob", top: "32%", left: "6%", size: 32, rotate: 8 },
  { kind: "hair", hair: "curly", top: "70%", left: "10%", size: 40, rotate: -6 },
  { kind: "hair", hair: "locs", top: "78%", left: "72%", size: 44, rotate: 14 },
  { kind: "hair", hair: "afro", top: "56%", left: "88%", size: 30, rotate: -18 },
  { kind: "hair", hair: "bob", top: "8%", left: "46%", size: 28, rotate: 20 },
  { kind: "hair", hair: "braids", top: "88%", left: "40%", size: 34, rotate: -10 },
  { kind: "tool", tool: "comb", top: "44%", left: "94%", size: 26, rotate: 6 },
  { kind: "tool", tool: "scissors", top: "22%", left: "28%", size: 26, rotate: -22 },
];

export function SalonIllustrationPanel() {
  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden bg-accent/[0.06] p-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-1/4 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-accent/10 blur-3xl"
      />
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 opacity-[0.08]">
        {SCATTER.map((item, index) => {
          const style = {
            top: item.top,
            left: item.left,
            width: item.size,
            height: item.size,
            transform: `rotate(${item.rotate}deg)`,
          };
          return item.kind === "hair" ? (
            <HairstyleBust key={index} hair={item.hair} className="absolute" style={style} />
          ) : (
            <SalonToolIcon key={index} tool={item.tool} className="absolute" style={style} />
          );
        })}
      </div>
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
