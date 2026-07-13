// Silhouette de coiffure — illustration décorative (accueil, connexion).
// Formes géométriques simples (cercles/rectangles) : seule la silhouette
// capillaire varie, sans détail de peau ni de visage, pour représenter la
// diversité des textures et styles (afro, box braids, locs, bob, bouclé) sans
// dépendre d'un jeu d'illustrations externe.

export type Hairstyle = "afro" | "braids" | "bob" | "curly" | "locs";

export const HAIRSTYLES: { key: Hairstyle; label: string }[] = [
  { key: "afro", label: "Afro" },
  { key: "braids", label: "Box braids" },
  { key: "bob", label: "Bob" },
  { key: "curly", label: "Bouclé" },
  { key: "locs", label: "Locs" },
];

const SHOULDERS_PATH = "M12 100 C12 76 29 64 50 64 C71 64 88 76 88 100 Z";

function HairShape({ hair }: { hair: Hairstyle }) {
  switch (hair) {
    case "afro":
      return <circle cx="50" cy="32" r="26" />;
    case "bob":
      return <rect x="26" y="10" width="48" height="52" rx="22" />;
    case "curly": {
      const bumps: Array<[number, number, number]> = [
        [50, 10, 10],
        [32, 14, 10],
        [68, 14, 10],
        [22, 30, 9],
        [78, 30, 9],
        [28, 48, 9],
        [72, 48, 9],
      ];
      return (
        <>
          {bumps.map(([cx, cy, r], index) => (
            <circle key={index} cx={cx} cy={cy} r={r} />
          ))}
        </>
      );
    }
    case "braids": {
      const strands: Array<[number, number, number]> = [
        [30, 20, 88],
        [38, 16, 94],
        [46, 14, 98],
        [54, 14, 98],
        [62, 16, 94],
        [70, 20, 88],
      ];
      return (
        <>
          {strands.map(([cx, top, bottom], index) => (
            <rect key={index} x={cx - 2.5} y={top} width={5} height={bottom - top} rx={2.5} />
          ))}
        </>
      );
    }
    case "locs": {
      const strands: Array<[number, number, number]> = [
        [34, 16, 70],
        [44, 12, 76],
        [50, 10, 80],
        [56, 12, 76],
        [66, 16, 70],
      ];
      return (
        <>
          {strands.map(([cx, top, bottom], index) => (
            <rect key={index} x={cx - 4.5} y={top} width={9} height={bottom - top} rx={4.5} />
          ))}
        </>
      );
    }
  }
}

export interface HairstyleBustProps {
  hair: Hairstyle;
  className?: string;
}

export function HairstyleBust({ hair, className }: HairstyleBustProps) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden="true">
      <g fill="var(--color-accent)">
        <HairShape hair={hair} />
        <path d={SHOULDERS_PATH} />
      </g>
      <g fill="var(--color-surface)">
        <rect x="41" y="50" width="18" height="20" rx="7" />
        <circle cx="50" cy="36" r="19" />
      </g>
    </svg>
  );
}
