import { useSearchParams } from "react-router-dom";
import { Star } from "lucide-react";
import { toast } from "sonner";
import { useBidMutation } from "../api/hooks";
import type { Opportunity } from "../api/types";
import { fmtDate } from "../lib/format";
import {
  AiDot,
  CountyPill,
  DetailMeter,
  DueBadge,
  NewDot,
  StatusPill,
  TypeTag,
  ValueTag,
} from "./ui";

/** One bid as a responsive row-card. Click opens the drawer. */
export default function BidRow({ bid, showStatus = false }: {
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

  return (
    <button
      onClick={openDrawer}
      className="card group flex w-full items-center gap-3 px-4 py-3 text-left transition-all hover:-translate-y-px hover:border-accent/40"
    >
      <div className="w-12 shrink-0 text-center">
        <div className="text-[11px] font-bold uppercase text-ink-faint">
          {bid.due_date ? fmtDate(bid.due_date).split(" ")[0] : "—"}
        </div>
        <div className="text-lg font-extrabold leading-tight text-ink">
          {bid.due_date ? fmtDate(bid.due_date).split(" ")[1] : ""}
        </div>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-bold text-ink group-hover:text-accent">
            {bid.title}
          </span>
          {bid.is_new && <NewDot />}
          {bid.has_summary && <AiDot />}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-soft">
          <span className="truncate">{bid.agency}</span>
          <TypeTag offer={bid.offer_type} />
          {bid.prior_cycles > 0 && (
            <span className="text-[11px] font-semibold text-upcoming">↻ rebid</span>
          )}
          {bid.status === "award" && (
            <span className="truncate text-[11px] font-semibold text-warn">
              {bid.awarded_vendor ? `won by ${bid.awarded_vendor}` : "winner not published"}
            </span>
          )}
        </div>
      </div>

      <div className="hidden shrink-0 sm:block"><CountyPill county={bid.county} small /></div>
      <div className="hidden shrink-0 md:block"><DetailMeter score={bid.detail_score} /></div>
      <div className="w-16 shrink-0 text-right">
        {/* An awarded row's number is the real award, not the estimate. */}
        {bid.status === "award" && bid.award_amount != null
          ? <ValueTag amount={bid.award_amount} est={false} />
          : <ValueTag amount={bid.budget_amount} />}
      </div>
      <div className="shrink-0">
        {showStatus ? <StatusPill status={bid.status} />
                    : <DueBadge days={bid.days_until_due} status={bid.status} />}
      </div>
      <span
        role="button"
        tabIndex={0}
        onClick={toggleTrack}
        onKeyDown={(e) => { if (e.key === "Enter") toggleTrack(e as unknown as React.MouseEvent); }}
        className={`shrink-0 rounded-full p-1.5 transition-colors ${
          bid.tracked
            ? "text-warn"
            : "text-ink-faint opacity-40 hover:text-warn hover:opacity-100"
        }`}
        aria-label={bid.tracked ? "Untrack" : "Track"}
      >
        <Star size={16} fill={bid.tracked ? "currentColor" : "none"} />
      </span>
    </button>
  );
}
