import { useSearchParams } from "react-router-dom";
import { Star } from "lucide-react";
import { toast } from "sonner";
import { useBidMutation } from "../api/hooks";
import type { Opportunity } from "../api/types";
import { fmtDate } from "../lib/format";
import {
  AiDot,
  CountyPill,
  DueBadge,
  NewDot,
  StatusPill,
  TypeTag,
  ValueTag,
} from "./ui";

/** One bid as a grid card — the browsing view. More room than a row, so the
 *  scope preview earns its place here. Click opens the drawer. */
export function BidCard({ bid, showStatus = false }: {
  bid: Opportunity; showStatus?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const mutate = useBidMutation();

  const openDrawer = () => {
    params.set("drawer", bid.opportunity_id);
    setParams(params);
  };

  const toggleTrack = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await mutate.mutateAsync({
      id: bid.opportunity_id,
      action: bid.tracked ? "untrack" : "track",
    });
    toast.success(bid.tracked ? "Untracked" : "Tracking — added to your pipeline");
  };

  const preview = bid.scope ?? bid.description ?? "";

  return (
    <button
      onClick={openDrawer}
      className="card group flex h-full w-full flex-col p-4 text-left transition-all hover:-translate-y-px hover:border-accent/40"
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          {showStatus ? <StatusPill status={bid.status} />
                      : <DueBadge days={bid.days_until_due} status={bid.status} />}
          {bid.is_new && <NewDot />}
          {bid.has_summary && <AiDot />}
        </div>
        <span
          role="button"
          tabIndex={0}
          onClick={toggleTrack}
          onKeyDown={(e) => { if (e.key === "Enter") toggleTrack(e as unknown as React.MouseEvent); }}
          className={`shrink-0 rounded-full p-1 transition-colors ${
            bid.tracked ? "text-warn"
                        : "text-ink-faint opacity-40 hover:text-warn hover:opacity-100"
          }`}
          aria-label={bid.tracked ? "Untrack" : "Track"}
        >
          <Star size={15} fill={bid.tracked ? "currentColor" : "none"} />
        </span>
      </div>

      <div className="text-sm font-bold leading-snug text-ink group-hover:text-accent">
        {bid.title}
      </div>
      <div className="mt-1 truncate text-xs text-ink-soft">{bid.agency}</div>

      {preview && (
        <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-ink-faint">
          {preview}
        </p>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 pt-3">
        <div className="flex min-w-0 items-center gap-1.5">
          <CountyPill county={bid.county} small />
          <TypeTag offer={bid.offer_type} />
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-ink-soft">
          <ValueTag amount={bid.budget_amount} />
          {bid.due_date && <span className="text-ink-faint">{fmtDate(bid.due_date)}</span>}
        </div>
      </div>
    </button>
  );
}

/** One bid as a dense single line — the scanning view. Everything on one row,
 *  nothing wraps; for working through hundreds of bids quickly. */
export function BidCompactRow({ bid, showStatus = false }: {
  bid: Opportunity; showStatus?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const mutate = useBidMutation();

  const openDrawer = () => {
    params.set("drawer", bid.opportunity_id);
    setParams(params);
  };

  const toggleTrack = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await mutate.mutateAsync({
      id: bid.opportunity_id,
      action: bid.tracked ? "untrack" : "track",
    });
  };

  return (
    <button
      onClick={openDrawer}
      className="group flex w-full items-center gap-2.5 border-b border-line px-2 py-1.5 text-left transition-colors last:border-0 hover:bg-bg"
    >
      <span
        role="button"
        tabIndex={0}
        onClick={toggleTrack}
        onKeyDown={(e) => { if (e.key === "Enter") toggleTrack(e as unknown as React.MouseEvent); }}
        className={`shrink-0 ${bid.tracked ? "text-warn" : "text-ink-faint opacity-30 hover:text-warn hover:opacity-100"}`}
        aria-label={bid.tracked ? "Untrack" : "Track"}
      >
        <Star size={13} fill={bid.tracked ? "currentColor" : "none"} />
      </span>
      <span className="w-14 shrink-0 text-xs tabular-nums text-ink-soft">
        {bid.due_date ? fmtDate(bid.due_date) : "—"}
      </span>
      <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink group-hover:text-accent">
        {bid.title}
        {bid.is_new && <span className="ml-1.5 align-middle"><NewDot /></span>}
      </span>
      <span className="hidden w-44 shrink-0 truncate text-xs text-ink-soft md:block">
        {bid.agency}
      </span>
      <span className="hidden shrink-0 sm:block"><CountyPill county={bid.county} small /></span>
      <span className="w-16 shrink-0 text-right"><ValueTag amount={bid.budget_amount} /></span>
      <span className="shrink-0">
        {showStatus ? <StatusPill status={bid.status} />
                    : <DueBadge days={bid.days_until_due} status={bid.status} />}
      </span>
    </button>
  );
}
