import { ArrowDownWideNarrow, ArrowUpNarrowWide } from "lucide-react";
import type { SortKeyDef, SortPref } from "../lib/sort";

/** Sort-key select + direction toggle. Preference is persisted by useSortPref. */
export default function SortControl({ keys, pref, onChange }: {
  keys: SortKeyDef[];
  pref: SortPref;
  onChange: (next: SortPref) => void;
}) {
  const onKeyChange = (key: string) => {
    const def = keys.find((k) => k.value === key);
    onChange({ key, dir: def?.defaultDir ?? "asc" });
  };

  return (
    <div className="inline-flex items-center overflow-hidden rounded-[10px] border border-line bg-surface">
      <select
        value={pref.key}
        onChange={(e) => onKeyChange(e.target.value)}
        aria-label="Sort by"
        className="bg-surface py-2 pl-3 pr-1 text-sm font-semibold text-ink-soft outline-none"
      >
        {keys.map((k) => (
          <option key={k.value} value={k.value}>{k.label}</option>
        ))}
      </select>
      <button
        onClick={() => onChange({ ...pref, dir: pref.dir === "asc" ? "desc" : "asc" })}
        aria-label={pref.dir === "asc" ? "Ascending — click for descending" : "Descending — click for ascending"}
        title={pref.dir === "asc" ? "Ascending" : "Descending"}
        className="border-l border-line px-2.5 py-2.5 text-ink-soft transition-colors hover:bg-bg hover:text-accent"
      >
        {pref.dir === "asc" ? <ArrowUpNarrowWide size={15} /> : <ArrowDownWideNarrow size={15} />}
      </button>
    </div>
  );
}
