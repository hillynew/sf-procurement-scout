import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight, FolderOpen, X } from "lucide-react";
import { toast } from "sonner";
import { useBidMutation, useOpportunity } from "../api/hooks";
import { fmtDate, fmtDateTime } from "../lib/format";
import {
  Button,
  CountyPill,
  DetailMeter,
  DueBadge,
  Spinner,
  StatusPill,
  TypeTag,
  ValueTag,
} from "../components/ui";

function Fact({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wide text-ink-faint">{label}</div>
      <div className="text-[13px] font-medium text-ink">{value}</div>
    </div>
  );
}

export default function BidDrawer() {
  const [params, setParams] = useSearchParams();
  const id = params.get("drawer");
  const { data: bid, isLoading } = useOpportunity(id);
  const mutate = useBidMutation();

  const close = () => {
    params.delete("drawer");
    setParams(params, { replace: true });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && id) close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!id) return null;

  const toggleTrack = async () => {
    if (!bid) return;
    await mutate.mutateAsync({ id, action: bid.tracked ? "untrack" : "track" });
    toast.success(bid.tracked ? "Untracked" : "Tracking — added to your pipeline");
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/25" onClick={close}>
      <div
        className="drawer-in h-full w-full overflow-y-auto border-l border-line bg-surface p-5 sm:max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        {isLoading || !bid ? (
          <div className="flex h-40 items-center justify-center"><Spinner size={22} /></div>
        ) : (
          <>
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <CountyPill county={bid.county} small />
                <StatusPill status={bid.status} />
                <TypeTag offer={bid.offer_type} />
              </div>
              <button onClick={close}
                      className="rounded-lg p-1.5 text-ink-faint hover:bg-bg hover:text-ink">
                <X size={17} />
              </button>
            </div>

            <h2 className="text-lg font-bold leading-snug">{bid.title}</h2>
            <div className="mt-1 text-sm text-ink-soft">{bid.agency}</div>

            <div className="mt-3 flex flex-wrap items-center gap-2.5">
              <DueBadge days={bid.days_until_due} status={bid.status} />
              <ValueTag amount={bid.budget_amount} className="text-base" />
              <DetailMeter score={bid.detail_score} />
            </div>

            {bid.brief && (
              <p className="mt-4 rounded-[10px] bg-bg px-3.5 py-3 text-[13px] leading-relaxed text-ink-soft">
                {bid.brief}
              </p>
            )}

            <div className="mt-4 grid grid-cols-2 gap-3">
              <Fact label="Due" value={fmtDateTime(bid.due_date)} />
              <Fact label="Questions due" value={fmtDateTime(bid.questions_due)} />
              <Fact label="Pre-bid" value={bid.pre_bid_meeting} />
              <Fact label="Posted" value={fmtDate(bid.posted_date)} />
              <Fact label="Reference" value={bid.external_id} />
              <Fact label="Duration" value={bid.duration_days ? `${bid.duration_days} days` : null} />
              <Fact label="Liquidated damages" value={bid.liquidated_damages} />
              <Fact label="License" value={bid.licenses} />
              <Fact label="Location" value={bid.project_location} />
              <Fact label="Contact" value={bid.contact_email ?? bid.contact} />
              {bid.prior_cycles > 0 && (
                <Fact label="Recurring"
                      value={`${bid.prior_cycles} prior cycle${bid.prior_cycles > 1 ? "s" : ""}${
                        bid.last_cycle_closed ? `, last ${fmtDate(bid.last_cycle_closed)}` : ""}`} />
              )}
            </div>

            {bid.requirements.length > 0 && (
              <div className="mt-4">
                <div className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-ink-faint">
                  Requirements
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {bid.requirements.map((r, i) => (
                    <span key={i}
                          className="rounded-full border border-line bg-bg px-2.5 py-1 text-xs text-ink-soft">
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {bid.documents.length > 0 && (
              <div className="mt-4">
                <div className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-ink-faint">
                  Documents ({bid.documents.length})
                </div>
                <div className="space-y-1">
                  {bid.documents.map((d, i) => (
                    <a key={i} href={d.url} target="_blank" rel="noreferrer"
                       className="flex items-center justify-between rounded-[10px] border border-line px-3 py-2 text-[13px] font-medium text-ink transition-colors hover:border-accent hover:text-accent">
                      <span className="truncate">{d.name}</span>
                      <span className={`ml-2 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                        d.kind === "addendum" ? "bg-warn-soft text-warn" : "bg-bg text-ink-faint"}`}>
                        {d.kind}
                      </span>
                    </a>
                  ))}
                </div>
              </div>
            )}

            <div className="sticky bottom-0 mt-6 flex gap-2 border-t border-line bg-surface pt-4">
              <Button onClick={toggleTrack} kind={bid.tracked ? "ghost" : "primary"}>
                {bid.tracked ? "Untrack" : "★ Track"}
              </Button>
              <Link to={`/bids/${bid.opportunity_id}`} onClick={() => close()}
                    className="flex items-center gap-1.5 rounded-[10px] bg-accent-soft px-3.5 py-2 text-sm font-semibold text-accent transition-colors hover:bg-accent hover:text-white">
                <FolderOpen size={15} /> Workroom
              </Link>
              <a href={bid.url} target="_blank" rel="noreferrer"
                 className="ml-auto flex items-center gap-1 rounded-[10px] border border-line px-3.5 py-2 text-sm font-semibold text-ink-soft transition-colors hover:border-accent hover:text-accent">
                Portal <ArrowUpRight size={14} />
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
