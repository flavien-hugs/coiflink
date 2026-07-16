// Label de champ de formulaire — badge « Optionnel » ou marqueur requis (`*`).
// Partagé par tous les formulaires du dashboard (prestations, salon…) pour une
// convention visuelle unique : un champ sans badge ni `*` n'existe pas.

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
    <span className="flex flex-wrap items-center gap-2">
      {optional ? (
        <span className="rounded-full bg-foreground/5 px-2 py-0.5 text-xs font-medium text-muted">
          Optionnel
        </span>
      ) : null}
      <span>
        {children}
        {required ? " *" : ""}
      </span>
    </span>
  );
}
