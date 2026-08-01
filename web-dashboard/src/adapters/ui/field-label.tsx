// Label de champ de formulaire — mention « (Optionnel) » ou marqueur requis
// (`*`). Partagé par tous les formulaires du dashboard (prestations, salon…)
// pour une convention visuelle unique : un champ sans mention ni `*` n'existe pas.

export function FieldLabel({
  children,
  optional = false,
  required = false,
}: {
  children: string;
  optional?: boolean;
  required?: boolean;
}) {
  return (
    <span>
      {children}
      {required ? " *" : ""}
      {optional ? <span className="font-normal text-muted"> (Optionnel)</span> : null}
    </span>
  );
}
