import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useSourceMutation, useSources } from "../api/hooks";
import type { DetectResponse } from "../api/types";
import { Button, FilterChip, Spinner, StatCard } from "../components/ui";
import { COUNTY_LABEL, fmtRelative } from "../lib/format";

const STATUS_META: Record<string, { label: string; color: string; icon: string }> = {
  ok: { label: "OK", color: "var(--color-open)", icon: "●" },
  empty: { label: "No listings", color: "var(--color-ink-faint)", icon: "○" },
  degraded: { label: "Degraded", color: "var(--color-warn)", icon: "◒" },
  error: { label: "Error", color: "var(--color-danger)", icon: "✗" },
};

export default function Sources() {
  const { data, isLoading } = useSources();
  const { detect, add, remove } = useSourceMutation();
  const [filter, setFilter] = useState("");
  const [url, setUrl] = useState("");
  const [detected, setDetected] = useState<DetectResponse | null>(null);
  const [county, setCounty] = useState("broward");

  const sources = data?.sources ?? [];
  const counts = useMemo(() => {
    const c = { ok: 0, empty: 0, degraded: 0, error: 0, silent: 0 };
    for (const s of sources) {
      if (!s.health) { c.silent += 1; continue; }
      const st = s.health.status as keyof typeof c;
      if (st in c) c[st] += 1;
    }
    return c;
  }, [sources]);

  const visible = useMemo(() => {
    let pool = sources;
    if (filter === "attention")
      pool = pool.filter((s) => s.health && ["degraded", "error"].includes(s.health.status));
    else if (filter === "custom") pool = pool.filter((s) => s.custom);
    else if (filter) pool = pool.filter((s) => s.health?.status === filter);
    return [...pool].sort((a, b) => (b.health?.count ?? -1) - (a.health?.count ?? -1));
  }, [sources, filter]);

  const runDetect = () => {
    if (!url.trim()) return;
    setDetected(null);
    detect.mutate(url.trim(), {
      onSuccess: setDetected,
      onError: (e) => toast.error(`Detection failed: ${e.message}`),
    });
  };

  const confirmAdd = () => {
    if (!detected) return;
    add.mutate(
      { name: detected.name, county, portal_url: detected.portal_url, id: detected.suggested_id },
      {
        onSuccess: (r) => {
          setDetected(null);
          setUrl("");
          if (r.test.ok) toast.success(`Added — test fetch found ${r.test.count} listings`);
          else toast.warning(`Added, but the test fetch failed: ${r.test.error}`);
        },
        onError: (e) => toast.error(`Couldn't add: ${e.message}`),
      },
    );
  };

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;

  return (
    <div className="fade-up">
      <div className="mb-4">
        <h1 className="text-xl font-extrabold">Sources</h1>
        <p className="text-sm text-ink-soft">
          {sources.length} portals monitored
          {data?.last_run?.finished_at && ` · last scan ${fmtRelative(data.last_run.finished_at)}`}
        </p>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <StatCard label="Healthy" value={counts.ok} accent />
        <StatCard label="No listings" value={counts.empty} />
        <StatCard label="Degraded" value={counts.degraded} />
        <StatCard label="Errors" value={counts.error} />
      </div>

      {(counts.degraded > 0 || counts.error > 0) && (
        <div className="mb-4 rounded-[14px] border border-warn/40 bg-warn-soft px-4 py-3 text-sm font-medium text-warn">
          {counts.degraded + counts.error} source{counts.degraded + counts.error > 1 ? "s" : ""} need
          attention — a broken scraper looks exactly like a quiet portal.
        </div>
      )}

      <div className="scrollbar-none mb-3 flex gap-2 overflow-x-auto pb-1">
        {[
          ["", "All"], ["attention", "Needs attention"], ["ok", "OK"],
          ["empty", "No listings"], ["custom", "My additions"],
        ].map(([key, label]) => (
          <FilterChip key={key} active={filter === key} onClick={() => setFilter(key)}>
            {label}
          </FilterChip>
        ))}
      </div>

      <div className="card mb-6 divide-y divide-line overflow-hidden">
        {visible.map((s) => {
          const meta = s.health ? STATUS_META[s.health.status] : null;
          return (
            <div key={s.id} className="flex items-center gap-3 px-4 py-2.5">
              <span className="w-4 text-center text-sm"
                    style={{ color: meta?.color ?? "var(--color-line)" }}>
                {meta?.icon ?? "·"}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <a href={s.portal_url} target="_blank" rel="noreferrer"
                     className="truncate text-sm font-semibold hover:text-accent">
                    {s.name}
                  </a>
                  {s.custom && (
                    <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-bold text-accent">
                      ADDED BY YOU
                    </span>
                  )}
                </div>
                <div className="truncate text-xs text-ink-faint">
                  {COUNTY_LABEL[s.county] ?? s.county}
                  {s.health?.note && ` · ${s.health.note}`}
                  {s.health?.error && ` · ${s.health.error}`}
                </div>
              </div>
              <div className="shrink-0 text-right text-xs">
                {s.health ? (
                  <>
                    <div className="font-bold text-ink">{s.health.count} deals</div>
                    <div className="text-ink-faint">{s.health.elapsed_ms}ms</div>
                  </>
                ) : (
                  <span className="text-ink-faint">not scanned yet</span>
                )}
              </div>
              {s.custom && (
                <button
                  onClick={() => {
                    if (confirm(`Remove ${s.name}?`))
                      remove.mutate(s.id, { onSuccess: () => toast.success("Source removed") });
                  }}
                  className="shrink-0 rounded p-1.5 text-ink-faint hover:bg-danger-soft hover:text-danger">
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          );
        })}
        {visible.length === 0 && (
          <div className="px-4 py-10 text-center text-sm text-ink-faint">Nothing matches this filter.</div>
        )}
      </div>

      <div className="card p-4">
        <div className="mb-1 flex items-center gap-1.5 text-sm font-bold">
          <Plus size={15} className="text-accent" /> Add a source
        </div>
        <p className="mb-3 text-xs text-ink-soft">
          Paste a city's bid page URL. CivicPlus portals (most South Florida cities) are
          detected and added automatically — other platforms aren't supported yet.
        </p>
        <div className="flex gap-2">
          <input value={url} onChange={(e) => setUrl(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && runDetect()}
                 placeholder="https://www.cityname.gov/bids.aspx"
                 className="flex-1 rounded-[10px] border border-line px-3 py-2.5 text-sm outline-none focus:border-accent" />
          <Button onClick={runDetect} disabled={detect.isPending || !url.trim()}>
            {detect.isPending ? "Checking…" : "Detect"}
          </Button>
        </div>

        {detected && (
          <div className={`fade-up mt-3 rounded-[10px] border px-4 py-3 ${
            detected.supported ? "border-open/40 bg-open-soft" : "border-line bg-bg"}`}>
            <div className="text-sm font-semibold">
              {detected.supported ? `✓ ${detected.message}` : detected.message}
            </div>
            {detected.supported && (
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <span className="text-sm font-bold">{detected.name}</span>
                <select value={county} onChange={(e) => setCounty(e.target.value)}
                        className="rounded-lg border border-line bg-surface px-2 py-1.5 text-xs font-semibold">
                  {Object.entries(COUNTY_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
                <Button onClick={confirmAdd} disabled={add.isPending} className="!py-1.5">
                  {add.isPending ? "Adding + testing…" : "Add & test fetch"}
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
