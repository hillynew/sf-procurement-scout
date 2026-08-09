import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAwards, usePricing, useVendors } from "../api/hooks";
import { CountyPill, EmptyState, Spinner, StatCard, LoadFailed } from "../components/ui";
import { fmtDate, fmtMoney } from "../lib/format";

/** Awards — who won, for how much — and the contracts about to expire.
 *
 * The trailing indicator and the leading one on one screen: an award tells
 * you what work went for; an incumbent contract ending in 90 days tells you
 * what is coming up for rebid before anyone advertises it.
 */
export default function Awards() {
  const { data, isLoading, isError, refetch } = useAwards();
  const { data: pricing } = usePricing();
  const { data: vendorData } = useVendors();
  const navigate = useNavigate();
  const [q, setQ] = useState("");

  const awards = useMemo(() => {
    const pool = data?.awards ?? [];
    if (!q.trim()) return pool;
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return pool.filter((a) => {
      const hay = `${a.title} ${a.agency} ${a.awarded_vendor ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [data, q]);

  const contracts = useMemo(() => {
    const pool = data?.contracts ?? [];
    if (!q.trim()) return pool;
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return pool.filter((c) => {
      const hay = `${c.name} ${c.agency} ${c.vendor ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [data, q]);

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;
  if (isError) return <LoadFailed what="awards" onRetry={() => refetch()} />;

  const withAmount = (data?.awards ?? []).filter((a) => a.award_amount != null);
  const totalAwarded = withAmount.reduce((sum, a) => sum + (a.award_amount ?? 0), 0);

  return (
    <div className="fade-up">
      <div className="mb-4">
        <h1 className="text-xl font-extrabold">Awards &amp; rebids</h1>
        <p className="text-sm text-ink-soft">
          Who won, for how much — and whose contract runs out next
        </p>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <StatCard label="Awards captured" value={data?.awards.length ?? 0} accent />
        <StatCard label="With a dollar amount" value={withAmount.length}
                  sub={withAmount.length ? `${fmtMoney(totalAwarded)} total` : "—"} />
        <StatCard label="Contracts expiring ≤180d" value={data?.contracts_total ?? 0}
                  sub="the earliest rebid warning" />
      </div>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Filter by title, agency, or vendor…"
        className="input mb-4 w-full max-w-md"
      />

      {vendorData && vendorData.vendors.length > 0 && (
        <div className="card mb-4 p-4">
          <div className="mb-2.5 flex items-baseline justify-between">
            <div className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">
              Who wins — from awards and contract registers
            </div>
            <div className="text-xs text-ink-faint">{vendorData.total} firms seen</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px]">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-ink-faint">
                  <th className="px-2 py-1 text-left font-semibold">Vendor</th>
                  <th className="px-2 py-1 text-right font-semibold">Awards</th>
                  <th className="px-2 py-1 text-right font-semibold">Awarded $</th>
                  <th className="px-2 py-1 text-right font-semibold">Contracts held</th>
                  <th className="px-2 py-1 text-left font-semibold">Wins with</th>
                </tr>
              </thead>
              <tbody>
                {vendorData.vendors.slice(0, 10).map((v) => (
                  <tr key={v.name} className="cursor-pointer border-t border-line hover:bg-bg"
                      onClick={() => setQ(v.name)}
                      title="Click to filter the lists below to this firm">
                    <td className="max-w-[220px] truncate px-2 py-1.5 text-sm font-semibold">{v.name}</td>
                    <td className="px-2 py-1.5 text-right text-sm tabular-nums">{v.awards || "—"}</td>
                    <td className="px-2 py-1.5 text-right text-sm font-bold tabular-nums">
                      {v.awarded_total != null ? fmtMoney(v.awarded_total) : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-right text-sm tabular-nums">{v.contracts || "—"}</td>
                    <td className="max-w-[220px] truncate px-2 py-1.5 text-xs text-ink-soft">
                      {v.agencies.join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pricing && pricing.categories.length > 0 && (
        <div className="card mb-4 p-4">
          <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
            Going rates — median of real awards and contracts, by category
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px]">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-ink-faint">
                  <th className="px-2 py-1 text-left font-semibold">Category</th>
                  <th className="px-2 py-1 text-right font-semibold">Median</th>
                  <th className="px-2 py-1 text-right font-semibold">Typical range</th>
                  <th className="px-2 py-1 text-right font-semibold">Data points</th>
                </tr>
              </thead>
              <tbody>
                {pricing.categories.slice(0, 12).map((c) => (
                  <tr key={c.slug} className="border-t border-line">
                    <td className="px-2 py-1.5 text-sm font-semibold">{c.label}</td>
                    <td className="px-2 py-1.5 text-right text-sm font-bold tabular-nums">{fmtMoney(c.median)}</td>
                    <td className="px-2 py-1.5 text-right text-xs tabular-nums text-ink-soft">
                      {fmtMoney(c.low)} – {fmtMoney(c.high)}
                    </td>
                    <td className="px-2 py-1.5 text-right text-xs tabular-nums text-ink-faint">{c.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-ink-faint">
            Medians, not means — categories with fewer than {pricing.min_samples} real
            numbers stay out rather than dress an anecdote as a statistic.
          </p>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="card p-4">
          <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
            Recent awards
          </div>
          {awards.length === 0 ? (
            <EmptyState title="No award records yet"
                        body="Awards arrive from commission agendas, FDOT lettings, SAM.gov and award notices as fetches run." />
          ) : (
            <div className="space-y-1.5">
              {awards.slice(0, 100).map((a) => (
                <button key={a.opportunity_id}
                        onClick={() => navigate(`/bids/${a.opportunity_id}`)}
                        className="flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left hover:bg-bg">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{a.title}</span>
                    <span className="block truncate text-xs text-ink-soft">
                      {a.agency}
                      {a.awarded_vendor ? <> · won by <b>{a.awarded_vendor}</b></> : " · winner not published"}
                      {a.award_linkage ? ` · linked (${a.award_linkage})` : ""}
                    </span>
                  </span>
                  <CountyPill county={a.county} small />
                  <span className="w-24 shrink-0 text-right text-sm font-bold tabular-nums">
                    {a.award_amount != null ? fmtMoney(a.award_amount) : "—"}
                  </span>
                  <span className="w-20 shrink-0 text-right text-xs text-ink-faint">
                    {fmtDate(a.award_date ?? a.posted_date ?? null)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="card p-4">
          <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
            Incumbent contracts expiring — likely rebids
          </div>
          {contracts.length === 0 ? (
            <EmptyState title="No contract register loaded"
                        body="Enable the weekly contract-register job in Settings → Background upkeep, or run: python -m src.cli contracts --refresh" />
          ) : (
            <div className="space-y-1.5">
              {contracts.slice(0, 100).map((c) => (
                <a key={c.contract_id} href={c.url ?? undefined} target="_blank" rel="noreferrer"
                   className="flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left hover:bg-bg">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{c.name}</span>
                    <span className="block truncate text-xs text-ink-soft">
                      {c.agency}
                      {c.vendor ? <> · held by <b>{c.vendor}</b></> : " · vendor not published"}
                      {c.extendable ? " · renewal option" : ""}
                    </span>
                  </span>
                  <span className="w-24 shrink-0 text-right text-sm font-bold tabular-nums">
                    {c.amount != null ? fmtMoney(Math.round(c.amount)) : "—"}
                  </span>
                  <span className="w-24 shrink-0 text-right">
                    <span className="rounded-full px-2 py-0.5 text-xs font-bold"
                          style={{
                            background: (c.days_left ?? 999) <= 60 ? "var(--color-warn-soft)" : "var(--color-closed-soft)",
                            color: (c.days_left ?? 999) <= 60 ? "var(--color-warn)" : "var(--color-ink-soft)",
                          }}>
                      {c.days_left != null ? `${c.days_left}d left` : "—"}
                    </span>
                  </span>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
