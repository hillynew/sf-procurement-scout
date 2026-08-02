import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search } from "lucide-react";
import { useLoadDemo, useOpportunities } from "../api/hooks";
import type { Opportunity } from "../api/types";
import BidRow from "../components/BidRow";
import FilterPanel, { ActiveFilterChips } from "../components/FilterPanel";
import SortControl from "../components/SortControl";
import { Button, EmptyState, Spinner } from "../components/ui";
import { applyFilters, parseFilters, writeFilters, type BidFilters } from "../lib/filters";
import { BID_SORT_KEYS, sortOpportunities, useSortPref } from "../lib/sort";

function matchesQuery(o: Opportunity, q: string): boolean {
  const hay = [o.title, o.agency, o.external_id ?? "", o.brief ?? "",
               o.scope ?? "", o.description ?? ""].join(" ").toLowerCase();
  return q.split(/\s+/).every((word) => hay.includes(word));
}

export default function AllBids() {
  const { data, isLoading } = useOpportunities();
  const demo = useLoadDemo();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const searchRef = useRef<HTMLInputElement>(null);
  const [sort, setSort] = useSortPref("bids", { key: "due", dir: "asc" });

  // One filter object drives everything; state lives in the URL so views
  // stay shareable and refresh-safe.
  const filters = useMemo(() => parseFilters(params), [params]);
  const setFilters = (next: BidFilters) =>
    setParams(writeFilters(params, next), { replace: true });

  useEffect(() => {
    if (params.get("focus")) {
      searchRef.current?.focus();
      params.delete("focus");
      setParams(params, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.get("focus")]);

  const all = useMemo(
    () => (data?.opportunities ?? []).filter((o) => o.status !== "catalog"),
    [data],
  );

  const searched = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? all.filter((o) => matchesQuery(o, q)) : all;
  }, [all, query]);

  const filtered = useMemo(() => applyFilters(searched, filters), [searched, filters]);
  const visible = useMemo(
    () => sortOpportunities(filtered, sort.key, sort.dir),
    [filtered, sort],
  );

  const showStatus = filters.statuses.length !== 1 || filters.statuses[0] !== "open";

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;

  if (all.length === 0) {
    return (
      <EmptyState
        title="No bids yet"
        body="Fetch live data from local, state, and federal portals, or load the sample data to explore."
        action={
          <Button onClick={() => demo.mutate()} disabled={demo.isPending}>
            {demo.isPending ? "Loading…" : "Load sample data"}
          </Button>
        }
      />
    );
  }

  return (
    <div className="fade-up">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">All bids</h1>
          <p className="text-sm text-ink-soft">{visible.length} shown · {all.length} captured</p>
        </div>
        <SortControl keys={BID_SORT_KEYS} pref={sort} onChange={setSort} />
      </div>

      <div className="mb-3 flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title, agency, reference, scope…"
            className="w-full rounded-[10px] border border-line bg-surface py-2.5 pl-10 pr-4 text-sm outline-none transition-colors placeholder:text-ink-faint focus:border-accent"
          />
        </div>
        <FilterPanel filters={filters} onChange={setFilters} matchCount={filtered.length} />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-1.5 empty:mb-0">
        <ActiveFilterChips filters={filters} onChange={setFilters} />
      </div>

      <div className="space-y-2">
        {visible.map((bid) => (
          <BidRow key={bid.opportunity_id} bid={bid} showStatus={showStatus} />
        ))}
        {visible.length === 0 && (
          <div className="py-16 text-center text-sm text-ink-faint">
            Nothing matches — loosen a filter or clear the search.
          </div>
        )}
      </div>
    </div>
  );
}
