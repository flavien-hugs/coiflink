// Toggle switch accessible — partagé par les formulaires du dashboard
// (horaires, jours exceptionnels…). `type="button"` : jamais un submit
// involontaire quand il est rendu dans un `<form>`.

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full p-0.5 transition ${
        checked ? "bg-accent" : "bg-foreground/15"
      }`}
    >
      <span
        className={`size-4 rounded-full bg-surface shadow-soft transition-transform ${
          checked ? "translate-x-4" : "translate-x-0"
        }`}
      />
    </button>
  );
}
