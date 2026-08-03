import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";

export interface MultiSelectOption {
  value: string;
  label: string;
  group?: string;
  /** Matches in the current snapshot. `0` is shown muted, never disabled —
   *  a category with nothing open today is exactly what a watchlist is for. */
  count?: number;
  /** Extra words the search box should match on beyond the label. */
  synonyms?: string;
}

/**
 * A grouped, searchable, multi-select dropdown.
 *
 * Chips stop scaling somewhere around a dozen options; this list runs to two
 * hundred, so the control has to be a dropdown with a filter box. Groups are
 * collapsible headers with a select-all, because picking "everything under
 * Construction & Trades" is the common case and clicking twenty-two rows to do
 * it is not a real option.
 */
export default function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = "Any",
  groupOrder,
  emptyHint,
}: {
  options: MultiSelectOption[];
  selected: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  /** Group keys in render order; groups not listed fall to the end. */
  groupOrder?: { key: string; label: string }[];
  emptyHint?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Close on outside click or Escape — a dropdown this tall is easy to
  // lose track of otherwise.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); setQuery(""); }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open]);

  const byValue = useMemo(
    () => Object.fromEntries(options.map((o) => [o.value, o])),
    [options],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(q) ||
        o.value.toLowerCase().includes(q) ||
        (o.synonyms ?? "").toLowerCase().includes(q),
    );
  }, [options, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, MultiSelectOption[]>();
    for (const o of filtered) {
      const key = o.group ?? "";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(o);
    }
    const order = groupOrder ?? [];
    const known = order.filter((g) => map.has(g.key));
    const extra = [...map.keys()]
      .filter((k) => !order.some((g) => g.key === k))
      .map((k) => ({ key: k, label: k || "Other" }));
    return [...known, ...extra].map((g) => ({ ...g, items: map.get(g.key) ?? [] }));
  }, [filtered, groupOrder]);

  const toggle = (value: string) =>
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value],
    );

  const toggleGroup = (items: MultiSelectOption[]) => {
    const values = items.map((i) => i.value);
    const allOn = values.every((v) => selected.includes(v));
    onChange(
      allOn
        ? selected.filter((v) => !values.includes(v))
        : [...selected, ...values.filter((v) => !selected.includes(v))],
    );
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={`flex w-full items-center justify-between gap-2 rounded-[10px] border px-3 py-2.5 text-left text-sm transition-colors ${
          open ? "border-accent" : "border-line hover:border-accent/50"
        }`}
      >
        <span className={selected.length ? "text-ink" : "text-ink-faint"}>
          {selected.length === 0
            ? placeholder
            : selected.length === 1
              ? byValue[selected[0]]?.label ?? selected[0]
              : `${selected.length} selected`}
        </span>
        <ChevronDown
          size={15}
          className={`shrink-0 text-ink-faint transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {selected.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {selected.map((v) => (
            <span
              key={v}
              className="flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent"
            >
              {byValue[v]?.label ?? v}
              <button
                type="button"
                aria-label={`Remove ${byValue[v]?.label ?? v}`}
                onClick={() => toggle(v)}
                className="hover:text-danger"
              >
                <X size={11} />
              </button>
            </span>
          ))}
          {selected.length > 1 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="rounded-full px-2 py-1 text-xs font-semibold text-ink-faint hover:text-danger"
            >
              Clear all
            </button>
          )}
        </div>
      )}

      {open && (
        <div className="absolute z-50 mt-1.5 max-h-80 w-full overflow-y-auto rounded-[10px] border border-line bg-surface shadow-lg">
          <div className="sticky top-0 flex items-center gap-2 border-b border-line bg-surface px-3 py-2">
            <Search size={14} className="shrink-0 text-ink-faint" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="w-full bg-transparent py-0.5 text-sm outline-none placeholder:text-ink-faint"
            />
            {query && (
              <button type="button" onClick={() => setQuery("")} className="text-ink-faint hover:text-ink">
                <X size={13} />
              </button>
            )}
          </div>

          {grouped.length === 0 && (
            <div className="px-3 py-6 text-center text-xs text-ink-faint">
              {emptyHint ?? "Nothing matches that search."}
            </div>
          )}

          {grouped.map((g) => {
            const allOn = g.items.length > 0 && g.items.every((i) => selected.includes(i.value));
            return (
              <div key={g.key || "_"}>
                {g.key !== "" && (
                  <div className="sticky top-[37px] flex items-center justify-between gap-2 bg-bg px-3 py-1.5">
                    <span className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">
                      {g.label}
                    </span>
                    <button
                      type="button"
                      onClick={() => toggleGroup(g.items)}
                      className="text-[11px] font-semibold text-accent hover:underline"
                    >
                      {allOn ? "None" : "All"}
                    </button>
                  </div>
                )}
                {g.items.map((o) => {
                  const on = selected.includes(o.value);
                  return (
                    <button
                      key={o.value}
                      type="button"
                      onClick={() => toggle(o.value)}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-bg ${
                        on ? "text-accent" : "text-ink"
                      }`}
                    >
                      <span
                        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                          on ? "border-accent bg-accent text-white" : "border-line"
                        }`}
                      >
                        {on && <Check size={11} strokeWidth={3} />}
                      </span>
                      <span className="flex-1 truncate">{o.label}</span>
                      {o.count !== undefined && (
                        <span
                          className={`shrink-0 text-[11px] tabular-nums ${
                            o.count > 0 ? "text-ink-faint" : "text-ink-faint/50"
                          }`}
                          title={
                            o.count > 0
                              ? `${o.count} open now`
                              : "Nothing open right now — the watchlist will flag the first one"
                          }
                        >
                          {o.count}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
