import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search } from "lucide-react";
import { useLoadDemo, useOpportunities } from "../api/hooks";
import type { Opportunity } from "../api/types";
import BidRow from "../components/BidRow";
import SortControl from "../components/SortControl";
import { Button, EmptyState, FilterChip, Spinner } from "../components/ui";
import { COUNTY_LABEL, OFFER_LABEL } from "../lib/format";
import { BID_SORT_KEYS, sortOpportunities, useSortPref } from "../lib/sort";

const STATUS_TABS = ["all", "open", "upcoming", "closed"] as const;

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

  const status = params.get("f") ?? "open";
  const county = params.get("c") ?? "";
  const otype = params.get("t") ?? "";
  const [sort, setSort] = useSortPref("bids", { key: "due", dir: "asc" });

  const setParam = (key: string, value: string) => {
    if (value) params.set(key, value);
    else params.delete(key);
    setParams(params, { replace: true });
  };

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

  const counts = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = all
      .filter((o) => !county || o.county === county)
      .filter((o) => !otype || o.offer_type === otype)
      .filter((o) => !q || matchesQuery(o, q));
    return {
      all: pool.length,
      open: pool.filter((o) => o.status === "open").length,
      upcoming: pool.filter((o) => o.status === "upcoming").length,
      closed: pool.filter((o) => ["closed", "cancelled"].includes(o.status)).length,
      pool,
    };
  }, [all, county, otype, query]);

  const visible = useMemo(() => {
    let pool = counts.pool;
    if (status === "open") pool = pool.filter((o) => o.status === "open");
    else if (status === "upcoming") pool = pool.filter((o) => o.status === "upcoming");
    else if (status === "closed")
      pool = pool.filter((o) => ["closed", "cancelled"].includes(o.status));
    return sortOpportunities(pool, sort.key, sort.dir);
  }, [counts.pool, status, sort]);

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;

  if (all.length === 0) {
    return (
      <EmptyState
        title="No bids yet"
        body="Fetch live data from ~40 South Florida portals, or load the sample data to explore."
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

      <div className="relative mb-3">
        <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-faint" />
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title, agency, reference, scope…"
          className="w-full rounded-[10px] border border-line bg-surface py-2.5 pl-10 pr-4 text-sm outline-none transition-colors placeholder:text-ink-faint focus:border-accent"
        />
      </div>

      <div className="scrollbar-none mb-4 flex items-center gap-2 overflow-x-auto pb-1">
        {STATUS_TABS.map((s) => (
          <FilterChip key={s} active={status === s} onClick={() => setParam("f", s)}>
            {s[0].toUpperCase() + s.slice(1)} {counts[s] > 0 && `· ${counts[s]}`}
          </FilterChip>
        ))}
        <span className="mx-1 h-5 w-px shrink-0 bg-line" />
        {Object.entries(COUNTY_LABEL).map(([key, label]) => (
          <FilterChip key={key} active={county === key}
                      onClick={() => setParam("c", county === key ? "" : key)}>
            {label}
          </FilterChip>
        ))}
        <span className="mx-1 h-5 w-px shrink-0 bg-line" />
        {["construction", "services", "goods", "professional_services"].map((t) => (
          <FilterChip key={t} active={otype === t}
                      onClick={() => setParam("t", otype === t ? "" : t)}>
            {OFFER_LABEL[t]}
          </FilterChip>
        ))}
      </div>

      <div className="space-y-2">
        {visible.map((bid) => (
          <BidRow key={bid.opportunity_id} bid={bid} showStatus={status === "all" || status === "closed"} />
        ))}
        {visible.length === 0 && (
          <div className="py-16 text-center text-sm text-ink-faint">
            Nothing matches — try clearing a filter.
          </div>
        )}
      </div>
    </div>
  );
}
