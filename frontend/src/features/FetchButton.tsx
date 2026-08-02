import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useFetchStatus, useRefreshAfterFetch, useStartFetch } from "../api/hooks";
import type { FetchStatus, SourceHealth } from "../api/types";
import { Spinner } from "../components/ui";

const STATUS_ICON: Record<string, string> = {
  ok: "✓", empty: "○", degraded: "◒", error: "✗",
};
const STATUS_COLOR: Record<string, string> = {
  ok: "var(--color-open)", empty: "var(--color-ink-faint)",
  degraded: "var(--color-warn)", error: "var(--color-danger)",
};

export default function FetchButton() {
  const start = useStartFetch();
  const refreshAll = useRefreshAfterFetch();
  const { data: polled } = useFetchStatus();
  const [live, setLive] = useState<FetchStatus | null>(null);
  const [open, setOpen] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const doneHandled = useRef(false);

  const status: FetchStatus = live ?? polled ?? { state: "idle" };
  const running = status.state === "running";

  // Subscribe to SSE while a fetch runs; fall back to polling on error.
  useEffect(() => {
    if (!running || esRef.current) return;
    const es = new EventSource("/api/fetch/stream");
    esRef.current = es;
    const sources: SourceHealth[] = [...(status.sources ?? [])];

    es.addEventListener("status", (e) => {
      setLive(JSON.parse((e as MessageEvent).data));
    });
    es.addEventListener("source", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      sources.push(data.source);
      setLive((prev) => ({
        ...(prev ?? { state: "running" }),
        state: "running",
        sources: [...sources],
        done_count: data.done,
        total: data.total,
      }));
    });
    es.addEventListener("phase", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setLive((prev) => (prev ? { ...prev, phase: data.phase } : prev));
    });
    const finish = (e: Event) => {
      const data = JSON.parse((e as MessageEvent).data);
      setLive((prev) => ({ ...(prev ?? {}), ...data, state: data.event }));
      es.close();
      esRef.current = null;
    };
    es.addEventListener("done", finish);
    es.addEventListener("error", (e) => {
      // Network-level error (no data): drop to polling. SSE 'error' event
      // with a payload means the fetch itself failed.
      if ((e as MessageEvent).data) finish(e);
      else { es.close(); esRef.current = null; }
    });
    return () => { es.close(); esRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  // One toast + cache refresh per completed fetch.
  useEffect(() => {
    if (status.state === "done" && !doneHandled.current) {
      doneHandled.current = true;
      refreshAll();
      toast.success(
        `Fetch finished — ${status.count} bids` +
          (status.new_count ? `, ${status.new_count} new` : ""),
      );
      setTimeout(() => setOpen(false), 1500);
    } else if (status.state === "error" && !doneHandled.current) {
      doneHandled.current = true;
      refreshAll();
      toast.error(`Fetch failed: ${status.error ?? "unknown error"}`);
    } else if (status.state === "running") {
      doneHandled.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.state]);

  const onClick = async () => {
    if (running) { setOpen(!open); return; }
    setLive(null);
    setOpen(true);
    try {
      await start.mutateAsync();
      setLive({ state: "running", sources: [], done_count: 0, total: 0 });
    } catch {
      toast.info("A fetch is already running");
    }
  };

  const pct = status.total ? Math.round(((status.done_count ?? 0) / status.total) * 100) : 0;

  return (
    <div className="relative">
      <button
        onClick={onClick}
        className={`flex items-center gap-2 rounded-[10px] px-3.5 py-2 text-sm font-bold text-white transition-colors ${
          running ? "bg-accent-deep" : "bg-accent hover:bg-accent-deep"
        }`}
      >
        <RefreshCw size={15} className={running ? "animate-spin" : ""} />
        <span className="hidden sm:inline">{running ? `Fetching ${pct}%` : "Fetch live data"}</span>
      </button>

      {open && (status.state === "running" || status.state === "done" || status.state === "error") && (
        <div className="fade-up absolute right-0 z-40 mt-2 w-80 rounded-[14px] border border-line bg-surface p-3 shadow-(--shadow-pop)">
          <div className="mb-2 flex items-center justify-between text-xs font-bold text-ink-soft">
            <span>
              {status.state === "running"
                ? status.phase && status.phase !== "sources"
                  ? `Enriching (${status.phase})…`
                  : `Scanning portals ${status.done_count ?? 0}/${status.total ?? "…"}`
                : status.state === "done"
                  ? `Done — ${status.count} bids`
                  : "Fetch failed"}
            </span>
            {status.state === "running" && <Spinner size={13} />}
          </div>
          <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-line">
            <div className="h-full rounded-full bg-accent transition-all duration-300"
                 style={{ width: `${status.state === "running" ? pct : 100}%` }} />
          </div>
          <div className="scrollbar-none max-h-56 space-y-1 overflow-y-auto">
            {[...(status.sources ?? [])].reverse().map((s) => (
              <div key={s.source_id} className="flex items-center justify-between text-xs">
                <span className="truncate text-ink-soft">{s.name}</span>
                <span className="ml-2 flex shrink-0 items-center gap-1.5 font-semibold"
                      style={{ color: STATUS_COLOR[s.status] ?? "var(--color-ink-faint)" }}>
                  {s.count > 0 && <span className="text-ink-faint">{s.count}</span>}
                  {STATUS_ICON[s.status] ?? "·"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
