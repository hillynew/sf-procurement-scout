import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Link2, Mail, Phone, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useContractorMutation, useContractors } from "../api/hooks";
import type { Contractor, ContractorStatus } from "../api/types";
import { CountyPill, EmptyState, FilterChip, Spinner } from "../components/ui";
import {
  CONTRACTOR_STATUS_LABEL,
  fmtRelative,
  MATCH_STATUS_LABEL,
} from "../lib/format";

const STATUS_ORDER: ContractorStatus[] = [
  "prospect",
  "contacted",
  "in_network",
  "passed",
];

const GOV_LABEL: Record<string, string> = {
  none: "New to gov work",
  some: "Some gov work",
  regular: "Regular gov bidder",
};

/** One firm in the outsourcing bench: who they are, where the relationship
 *  stands, and every bid they've been matched to. */
function ContractorCard({ contractor }: { contractor: Contractor }) {
  const { update, remove } = useContractorMutation();
  const [notes, setNotes] = useState<string | null>(null);

  const saveNotes = () => {
    if (notes === null || notes === contractor.notes) return;
    update.mutate(
      { id: contractor.id, notes },
      { onError: (e) => toast.error(`Couldn't save notes: ${e.message}`) },
    );
  };

  const del = () => {
    if (!confirm(`Remove ${contractor.name} from the network?`)) return;
    remove.mutate(contractor.id, {
      onSuccess: () => toast.success("Removed from network"),
      onError: (e) => toast.error(`Couldn't remove: ${e.message}`),
    });
  };

  const gov = contractor.profile?.gov_experience;
  const sources = contractor.profile?.sources ?? [];

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {contractor.website ? (
              <a href={contractor.website} target="_blank" rel="noreferrer"
                 className="text-base font-bold text-ink hover:text-accent hover:underline">
                {contractor.name}
              </a>
            ) : (
              <span className="text-base font-bold">{contractor.name}</span>
            )}
            {contractor.county && <CountyPill county={contractor.county} small />}
            {gov && GOV_LABEL[gov] && (
              <span className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${
                gov === "none" ? "bg-open-soft text-open" : "bg-bg text-ink-faint"
              }`}>
                {GOV_LABEL[gov]}
              </span>
            )}
          </div>
          <div className="mt-0.5 text-xs text-ink-faint">
            {[contractor.trade, contractor.location].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={contractor.status}
            onChange={(e) =>
              update.mutate(
                { id: contractor.id, status: e.target.value },
                { onError: (err) => toast.error(`Couldn't update: ${err.message}`) },
              )}
            className="rounded-[10px] border border-line bg-bg px-2 py-1.5 text-xs font-semibold outline-none focus:border-accent"
          >
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>{CONTRACTOR_STATUS_LABEL[s]}</option>
            ))}
          </select>
          <button onClick={del} title="Remove from network"
                  className="rounded-[10px] p-1.5 text-ink-faint hover:bg-danger-soft hover:text-danger">
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {(contractor.phone || contractor.email) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {contractor.phone && (
            <a href={`tel:${contractor.phone}`}
               className="flex items-center gap-1.5 text-accent hover:underline">
              <Phone size={13} /> {contractor.phone}
            </a>
          )}
          {contractor.email && (
            <a href={`mailto:${contractor.email}`}
               className="flex items-center gap-1.5 text-accent hover:underline">
              <Mail size={13} /> {contractor.email}
            </a>
          )}
        </div>
      )}

      {contractor.matched_bids.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
            Matched bids ({contractor.matched_bids.length})
          </div>
          <div className="space-y-1">
            {contractor.matched_bids.map((b) => (
              <Link key={b.opportunity_id} to={`/bids/${b.opportunity_id}`}
                    className="flex items-center justify-between gap-2 rounded-[10px] border border-line px-3 py-2 text-sm hover:border-accent">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{b.title}</span>
                  <span className="block truncate text-xs text-ink-faint">{b.agency}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
                    b.match_status === "committed" ? "bg-open-soft text-open"
                      : b.match_status === "interested" ? "bg-warn-soft text-warn"
                      : b.match_status === "passed" ? "bg-danger-soft text-danger"
                      : "bg-bg text-ink-soft"
                  }`}>
                    {MATCH_STATUS_LABEL[b.match_status] ?? b.match_status}
                  </span>
                  <ArrowUpRight size={13} className="text-ink-faint" />
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {sources.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {sources.map((url) => (
            <a key={url} href={url} target="_blank" rel="noreferrer"
               className="flex max-w-60 items-center gap-1 rounded-full bg-bg px-2 py-0.5 text-[11px] font-medium text-ink-soft hover:text-accent">
              <Link2 size={10} className="shrink-0" />
              <span className="truncate">{url.replace(/^https?:\/\/(www\.)?/, "")}</span>
            </a>
          ))}
        </div>
      )}

      <textarea
        defaultValue={contractor.notes}
        onChange={(e) => setNotes(e.target.value)}
        onBlur={saveNotes}
        rows={2}
        placeholder="Notes — who you spoke to, licensing, fee terms…"
        className="mt-3 w-full rounded-[10px] border border-line bg-bg px-3 py-2 text-sm outline-none transition-colors placeholder:text-ink-faint focus:border-accent"
      />
      <div className="mt-1 flex items-center justify-between text-[11px] text-ink-faint">
        <span>Added {fmtRelative(contractor.created_at)}</span>
        {notes !== null && notes !== contractor.notes && (
          <span>{update.isPending ? "Saving…" : "Click away to save"}</span>
        )}
      </div>
    </div>
  );
}

/** The outsourcing network: every firm AI matching has surfaced, with the
 *  relationship pipeline that turns a found business into a bench partner. */
export default function Network() {
  const { data, isLoading } = useContractors();
  const [filter, setFilter] = useState<ContractorStatus | "all">("all");

  if (isLoading) {
    return <div className="flex justify-center py-24"><Spinner size={26} /></div>;
  }

  const contractors = data?.contractors ?? [];
  const shown = filter === "all"
    ? contractors
    : contractors.filter((c) => c.status === filter);
  const countOf = (s: ContractorStatus) =>
    contractors.filter((c) => c.status === s).length;

  return (
    <div className="fade-up">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Network</h1>
          <p className="mt-0.5 text-sm text-ink-soft">
            Firms that could fill your bids — you broker the deal and handle the
            compliance, they do the work.
          </p>
        </div>
      </div>

      {contractors.length === 0 ? (
        <EmptyState
          title="No contractors yet"
          body="Open a bid and hit “Find contractors” — every firm found lands here, so the bench grows with each deal you scout."
          action={
            <Link to="/bids"
                  className="rounded-[10px] bg-accent px-4 py-2 text-sm font-bold text-white hover:bg-accent-deep">
              Browse bids
            </Link>
          }
        />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-1.5">
            <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>
              All ({contractors.length})
            </FilterChip>
            {STATUS_ORDER.map((s) => (
              <FilterChip key={s} active={filter === s} onClick={() => setFilter(s)}>
                {CONTRACTOR_STATUS_LABEL[s]} ({countOf(s)})
              </FilterChip>
            ))}
          </div>

          {shown.length === 0 ? (
            <div className="py-16 text-center text-sm text-ink-faint">
              Nothing with this status yet.
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {shown.map((c) => (
                <ContractorCard key={c.id} contractor={c} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
