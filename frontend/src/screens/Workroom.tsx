import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  Mail,
  Phone,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { useBidMutation, useOpportunity, useSettings, useSummarize } from "../api/hooks";
import type { AiBrief, OpportunityDetail } from "../api/types";
import {
  Button,
  CountyPill,
  DueBadge,
  Spinner,
  StatusPill,
  TypeTag,
  ValueTag,
} from "../components/ui";
import { fmtDateTime, STAGE_LABEL, STAGES } from "../lib/format";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card p-4">
      <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
        {title}
      </div>
      {children}
    </div>
  );
}

/** Never trust a cached payload's shape — a brief from an older prompt
 *  version (or a partial model response) must render, not crash. */
function safeList(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

function sanitizeBrief(raw: AiBrief | undefined): AiBrief | undefined {
  if (!raw || typeof raw !== "object" || !raw.what_the_work_is) return undefined;
  return {
    what_the_work_is: String(raw.what_the_work_is),
    requirements: safeList(raw.requirements),
    red_flags: safeList(raw.red_flags),
    fit_hint: String(raw.fit_hint ?? ""),
    key_dates: Array.isArray(raw.key_dates)
      ? raw.key_dates.filter((d) => d && typeof d === "object" && d.label)
      : [],
    money: raw.money && typeof raw.money === "object" ? raw.money : undefined,
  };
}

function AiBriefCard({ bid }: { bid: OpportunityDetail }) {
  const summarize = useSummarize();
  const { data: settings } = useSettings();
  const aiAvailable = settings?.capabilities.ai_available ?? false;
  const brief = sanitizeBrief(bid.ai_summary?.summary as AiBrief | undefined);

  const generate = (force = false) =>
    summarize.mutate(
      { id: bid.opportunity_id, force },
      {
        onSuccess: (r) => toast.success(r.cached ? "Brief loaded from cache" : "✨ AI brief ready"),
        onError: (e) => toast.error(`Couldn't summarize: ${e.message}`),
      },
    );

  return (
    <div className="card border-accent/25 bg-gradient-to-br from-accent-soft/60 to-surface p-4">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-accent">
          <Sparkles size={13} /> AI deal brief
          {bid.ai_summary && (
            <span className="font-medium normal-case text-ink-faint">
              · {bid.ai_summary.model}
            </span>
          )}
        </div>
        {brief && aiAvailable && (
          <button onClick={() => generate(true)} disabled={summarize.isPending}
                  className="text-xs font-semibold text-accent hover:underline disabled:opacity-50">
            {summarize.isPending ? "Regenerating…" : "Regenerate"}
          </button>
        )}
      </div>

      {brief ? (
        <div className="space-y-3 text-sm">
          <p className="leading-relaxed text-ink">{brief.what_the_work_is}</p>
          {brief.red_flags?.length > 0 && (
            <div>
              <div className="mb-1 flex items-center gap-1 text-xs font-bold text-danger">
                <AlertTriangle size={12} /> Red flags
              </div>
              <ul className="space-y-1">
                {brief.red_flags.map((f, i) => (
                  <li key={i} className="flex gap-1.5 text-[13px] text-ink-soft">
                    <span className="text-danger">•</span>{f}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {brief.requirements?.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-bold text-ink-soft">You'll need</div>
              <ul className="space-y-1">
                {brief.requirements.map((r, i) => (
                  <li key={i} className="flex gap-1.5 text-[13px] text-ink-soft">
                    <span className="text-accent">•</span>{r}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {brief.money?.estimated_value && (
            <div className="text-[13px]">
              <span className="font-bold text-ink-soft">Value: </span>
              <span className="money">{brief.money.estimated_value}</span>
              {brief.money.bonding && (
                <span className="text-ink-soft"> · {brief.money.bonding}</span>
              )}
            </div>
          )}
          <p className="rounded-[10px] bg-surface px-3 py-2 text-[13px] font-medium italic text-ink-soft">
            {brief.fit_hint}
          </p>
        </div>
      ) : aiAvailable ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-[13px] text-ink-soft">
            Get a plain-English breakdown: what the work is, red flags, what you'll need.
          </p>
          <Button kind="soft" onClick={() => generate()} disabled={summarize.isPending}>
            {summarize.isPending ? "Reading the docs…" : "✨ Summarize with AI"}
          </Button>
        </div>
      ) : (
        <div className="text-[13px] text-ink-soft">
          {bid.brief ?? "No brief available."}
          <div className="mt-1.5 text-xs text-ink-faint">
            Set <code className="rounded bg-bg px-1">SF_SCOUT_ANTHROPIC_KEY</code> to
            unlock AI briefs — this is the rule-based summary.
          </div>
        </div>
      )}
    </div>
  );
}

export default function Workroom() {
  const { id } = useParams<{ id: string }>();
  const { data: bid, isLoading } = useOpportunity(id ?? null);
  const mutate = useBidMutation();
  const [notes, setNotes] = useState<string | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  const notesTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Autosave notes 800ms after the last keystroke.
  useEffect(() => {
    if (notes === null || !id) return;
    clearTimeout(notesTimer.current);
    notesTimer.current = setTimeout(() => {
      mutate.mutate({ id, action: "notes", body: { text: notes } });
    }, 800);
    return () => clearTimeout(notesTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes]);

  if (isLoading || !bid) {
    return <div className="flex justify-center py-24"><Spinner size={26} /></div>;
  }

  const checks = bid.checks ?? {};
  const done = bid.requirements.filter((_, i) => checks[String(i)]).length;
  const scope = bid.scope ?? "";
  const scopeTruncated = scope.length > 600 && !scopeOpen;

  const track = () =>
    mutate.mutate({ id: bid.opportunity_id, action: bid.tracked ? "untrack" : "track" });

  const setStage = (stage: string) =>
    mutate.mutate({ id: bid.opportunity_id, action: "stage", body: { stage } });

  const decide = (decision: "go" | "nogo" | null) =>
    mutate.mutate(
      { id: bid.opportunity_id, action: "decision", body: { decision } },
      { onSuccess: () => decision === "go" && toast.success("GO — moved to Preparing") },
    );

  return (
    <div className="fade-up">
      <Link to="/bids" className="mb-3 inline-flex items-center gap-1 text-sm font-semibold text-ink-soft hover:text-accent">
        <ArrowLeft size={15} /> All bids
      </Link>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <CountyPill county={bid.county} />
            <StatusPill status={bid.status} />
            <TypeTag offer={bid.offer_type} />
            <DueBadge days={bid.days_until_due} status={bid.status} />
          </div>
          <h1 className="text-xl font-extrabold leading-snug">{bid.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-ink-soft">
            <span>{bid.agency}</span>
            {bid.external_id && <span className="text-ink-faint">#{bid.external_id}</span>}
            <ValueTag amount={bid.budget_amount} className="text-base" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={track} kind={bid.tracked ? "ghost" : "primary"}>
            {bid.tracked ? "★ Tracked" : "★ Track"}
          </Button>
          <a href={bid.url} target="_blank" rel="noreferrer"
             className="flex items-center gap-1 rounded-[10px] border border-line bg-surface px-3.5 py-2 text-sm font-semibold text-ink-soft hover:border-accent hover:text-accent">
            Portal <ArrowUpRight size={14} />
          </a>
        </div>
      </div>

      {bid.tracked && (
        <div className="card mb-5 flex flex-wrap items-center gap-1 p-1.5">
          {STAGES.map((s, i) => (
            <button key={s} onClick={() => setStage(s)}
                    className={`flex-1 whitespace-nowrap rounded-[10px] px-3 py-2 text-xs font-bold transition-colors ${
                      bid.stage === s
                        ? "bg-accent text-white"
                        : "text-ink-soft hover:bg-bg"
                    }`}>
              {i + 1}. {STAGE_LABEL[s]}
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        {/* Left column */}
        <div className="space-y-4">
          <AiBriefCard bid={bid} />

          {scope && (
            <Section title="Scope of work">
              <p className="whitespace-pre-line text-sm leading-relaxed text-ink-soft">
                {scopeTruncated ? scope.slice(0, 600) + "…" : scope}
              </p>
              {scope.length > 600 && (
                <button onClick={() => setScopeOpen(!scopeOpen)}
                        className="mt-2 text-xs font-bold text-accent hover:underline">
                  {scopeOpen ? "Show less" : "Read full scope"}
                </button>
              )}
            </Section>
          )}

          {bid.requirements.length > 0 && (
            <Section title={`Requirements — ${done} of ${bid.requirements.length} ready`}>
              <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-line">
                <div className="h-full rounded-full bg-open transition-all"
                     style={{ width: `${(done / bid.requirements.length) * 100}%` }} />
              </div>
              <div className="space-y-1.5">
                {bid.requirements.map((r, i) => {
                  const checked = !!checks[String(i)];
                  return (
                    <label key={i}
                           className="flex cursor-pointer items-start gap-2.5 rounded-[10px] px-2 py-1.5 hover:bg-bg">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={!bid.tracked}
                        onChange={() =>
                          mutate.mutate({ id: bid.opportunity_id, action: "checks",
                                          body: { index: i, checked: !checked } })}
                        className="mt-0.5 h-4 w-4 accent-(--color-open)"
                      />
                      <span className={`text-sm ${checked ? "text-ink-faint line-through" : "text-ink"}`}>
                        {r}
                      </span>
                    </label>
                  );
                })}
              </div>
              {!bid.tracked && (
                <div className="mt-2 text-xs text-ink-faint">Track this bid to use the checklist.</div>
              )}
            </Section>
          )}

          {bid.documents.length > 0 && (
            <Section title={`Documents (${bid.documents.length})`}>
              <div className="space-y-1">
                {bid.documents.map((d, i) => (
                  <a key={i} href={d.url} target="_blank" rel="noreferrer"
                     className="flex items-center justify-between rounded-[10px] border border-line px-3 py-2 text-sm font-medium hover:border-accent hover:text-accent">
                    <span className="truncate">{d.name}</span>
                    <span className={`ml-2 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                      d.kind === "addendum" ? "bg-warn-soft text-warn" : "bg-bg text-ink-faint"}`}>
                      {d.kind}
                    </span>
                  </a>
                ))}
              </div>
            </Section>
          )}
        </div>

        {/* Right column */}
        <div className="space-y-4">
          <Section title="Key dates">
            <div className="space-y-2.5 text-sm">
              {[
                { label: "Questions due", value: fmtDateTime(bid.questions_due) },
                { label: "Pre-bid meeting", value: bid.pre_bid_meeting },
                { label: "Bid due", value: fmtDateTime(bid.due_date), bold: true },
                { label: "Bid opening", value: bid.bid_opening },
              ].filter((d) => d.value).map((d) => (
                <div key={d.label} className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-semibold text-ink-faint">{d.label}</span>
                  <span className={`text-right ${d.bold ? "font-bold" : "font-medium"}`}>{d.value}</span>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Commercial terms">
            <div className="space-y-2.5 text-sm">
              {[
                { label: "Est. value", value: bid.budget },
                { label: "Duration", value: bid.duration_days ? `${bid.duration_days} days` : null },
                { label: "Liquidated damages", value: bid.liquidated_damages },
                { label: "License", value: bid.licenses },
                { label: "Location", value: bid.project_location },
              ].filter((d) => d.value).map((d) => (
                <div key={d.label} className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-semibold text-ink-faint">{d.label}</span>
                  <span className="text-right font-medium">{d.value}</span>
                </div>
              ))}
              {!bid.budget && !bid.duration_days && !bid.liquidated_damages && (
                <div className="text-xs text-ink-faint">Nothing extracted yet — check the bid package.</div>
              )}
            </div>
          </Section>

          <Section title="Go / no-go">
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => decide(bid.decision === "go" ? null : "go")}
                      disabled={!bid.tracked}
                      className={`rounded-[10px] border-2 py-2 text-sm font-extrabold transition-colors disabled:opacity-40 ${
                        bid.decision === "go"
                          ? "border-open bg-open-soft text-open"
                          : "border-line text-ink-faint hover:border-open hover:text-open"
                      }`}>
                GO
              </button>
              <button onClick={() => decide(bid.decision === "nogo" ? null : "nogo")}
                      disabled={!bid.tracked}
                      className={`rounded-[10px] border-2 py-2 text-sm font-extrabold transition-colors disabled:opacity-40 ${
                        bid.decision === "nogo"
                          ? "border-danger bg-danger-soft text-danger"
                          : "border-line text-ink-faint hover:border-danger hover:text-danger"
                      }`}>
                NO-GO
              </button>
            </div>
            {!bid.tracked && (
              <div className="mt-2 text-xs text-ink-faint">Track the bid to decide.</div>
            )}
          </Section>

          {(bid.contact_email || bid.contact_phone || bid.contact) && (
            <Section title="Contact">
              <div className="space-y-1.5 text-sm">
                {bid.contact && <div className="font-medium">{bid.contact}</div>}
                {bid.contact_email && (
                  <a href={`mailto:${bid.contact_email}`}
                     className="flex items-center gap-1.5 text-accent hover:underline">
                    <Mail size={13} /> {bid.contact_email}
                  </a>
                )}
                {bid.contact_phone && (
                  <a href={`tel:${bid.contact_phone}`}
                     className="flex items-center gap-1.5 text-accent hover:underline">
                    <Phone size={13} /> {bid.contact_phone}
                  </a>
                )}
              </div>
            </Section>
          )}

          <Section title="Notes">
            <textarea
              defaultValue={bid.notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={!bid.tracked}
              rows={5}
              placeholder={bid.tracked ? "Pricing thoughts, subs to call, questions…" : "Track this bid to take notes."}
              className="w-full rounded-[10px] border border-line bg-bg px-3 py-2.5 text-sm outline-none transition-colors focus:border-accent disabled:opacity-50"
            />
            <div className="mt-1 text-right text-[11px] text-ink-faint">
              {notes !== null && (mutate.isPending ? "Saving…" : "Saved ✓")}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
