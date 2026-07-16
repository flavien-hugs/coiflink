"use client";

// Combobox avec recherche intégrée — bouton qui ouvre un menu positionné en
// `fixed` (portal) contenant un champ de recherche. Remplace un `<select>`
// natif quand la liste d'options gagne à être filtrable (ex. tri d'un
// tableau). Aucune dépendance externe : positionnement + portal via
// react-dom, déjà présent dans le projet.

import { createPortal } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

export interface SearchableSelectOption {
  value: string;
  label: string;
}

export interface SearchableSelectProps {
  value: string;
  options: SearchableSelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyLabel?: string;
  ariaLabel?: string;
  className?: string;
}

export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder = "Sélectionner",
  searchPlaceholder = "Rechercher",
  emptyLabel = "Aucun résultat",
  ariaLabel,
  className = "",
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value);

  const updateMenuPosition = useCallback(() => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect) return;
    setMenuStyle({
      position: "fixed",
      top: rect.bottom + 6,
      left: rect.left,
      width: rect.width,
      zIndex: 60,
    });
  }, []);

  const filteredOptions = useMemo(() => {
    const term = query.trim().toLocaleLowerCase("fr-FR");
    if (!term) return options;
    return options.filter((option) => option.label.toLocaleLowerCase("fr-FR").includes(term));
  }, [options, query]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    updateMenuPosition();

    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        close();
      }
    }
    function onReposition() {
      updateMenuPosition();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }

    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("scroll", onReposition, true);
    window.addEventListener("resize", onReposition);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("scroll", onReposition, true);
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, close, updateMenuPosition]);

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="flex h-10 w-full cursor-pointer items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 text-left text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25"
      >
        <span className="truncate">{selected?.label ?? placeholder}</span>
        <ChevronIcon className={`shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open
        ? createPortal(
            <div
              ref={menuRef}
              style={menuStyle}
              role="listbox"
              className="overflow-hidden rounded-lg border border-border bg-surface shadow-elevated"
            >
              <div className="border-b border-border p-2">
                <div className="relative">
                  <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
                  <input
                    type="text"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={searchPlaceholder}
                    autoFocus
                    className="w-full rounded-md border border-border bg-background/60 py-1.5 pl-8 pr-3 text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25"
                  />
                </div>
              </div>
              <div className="max-h-60 overflow-y-auto py-1">
                {filteredOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="option"
                    aria-selected={option.value === value}
                    onClick={() => {
                      onChange(option.value);
                      close();
                    }}
                    className={`block w-full cursor-pointer truncate px-3 py-2 text-left text-sm transition hover:bg-foreground/5 ${
                      option.value === value ? "font-semibold text-accent" : "text-foreground"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
                {filteredOptions.length === 0 ? (
                  <p className="px-3 py-6 text-center text-xs text-muted">{emptyLabel}</p>
                ) : null}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

export function SearchIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className={`size-3.5 ${className}`}
      aria-hidden="true"
    >
      <circle cx="9" cy="9" r="6" />
      <path d="m17 17-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}

function ChevronIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className={`size-3.5 ${className}`}
      aria-hidden="true"
    >
      <path d="m5 7.5 5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
