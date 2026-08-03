import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  Compass,
  FileText,
  HelpCircle,
  Link2,
  Mail,
  Phone,
  Send,
  Sparkles,
  Telescope,
} from "lucide-react";
import { toast } from "sonner";
import {
  useAskResearch,
  useBidMutation,
  useDeepDive,
  useOpportunity,
  useResearch,
  useSettings,
  useStartDeepDive,
  useSummarize,
} from "../api/hooks";
import type { AiBrief, DeepDiveReport, OpportunityDetail } from "../api/types";
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

/** Same defensive stance as sanitizeBrief: render whatever shape arrives. */
function objList<T extends object>(v: unknown, key: string): T[] {
  return Array.isArray(v)
    ? v.filter((x): x is T => !!x && typeof x === "object" && !!(x as Record<string, unknown>)[key])
    : [];
}

function sanitizeReport(raw: DeepDiveReport | undefined): DeepDiveReport | undefined {
  if (!raw || typeof raw !== "object" || !raw.overview) return undefined;
  return {
    overview: String(raw.overview),
    dollar_amounts: objList(raw.dollar_amounts, "amount"),
    key_dates: objList(raw.key_dates, "label"),
    scope_items: safeList(raw.scope_items),
    requirements: objList(raw.requirements, "item"),
    evaluation: safeList(raw.evaluation),
    contacts: objList(raw.contacts, "name"),
    documents_reviewed: objList(raw.documents_reviewed, "name"),
    red_flags: safeList(raw.red_flags),
    open_questions: safeList(raw.open_questions),
    fit_assessment: String(raw.fit_assessment ?? ""),
  };
}

const REQ_CATEGORY_LABEL: Record<string, string> = {
  bonding: "Bonding",
  insurance: "Insurance",
  licensing: "Licensing",
  submission: "Submission",
  wage_set_aside: "Wage / set-aside",
  other: "Other",
};

function DeepSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-ink-soft">
        {title}
      </div>
      {children}
    </div>
  );
}

function Bullets({ items, tone = "accent" }: { items: string[]; tone?: "accent" | "danger" | "warn" }) {
  const dot = tone === "danger" ? "text-danger" : tone === "warn" ? "text-warn" : "text-accent";
  return (
    <ul className="space-y-1">
      {items.map((x, i) => (
        <li key={i} className="flex gap-1.5 text-[13px] text-ink-soft">
          <span className={dot}>•</span>
          <span>{x}</span>
        </li>
      ))}
    </ul>
  );
}

function DeepDiveCard({ bid }: { bid: OpportunityDetail }) {
  const { data: settings } = useSettings();
  const aiAvailable = settings?.capabilities.ai_available ?? false;
  const { data: dive } = useDeepDive(bid.opportunity_id);
  const start = useStartDeepDive();

  if (!aiAvailable) return null;

  const running = dive?.state === "running" || start.isPending;
  const report = sanitizeReport(dive?.report);

  const go = (force = false) =>
    start.mutate(
      { id: bid.opportunity_id, force },
      {
        onSuccess: () => toast.info("🔭 Going deep — reading every document…"),
        onError: (e) => toast.error(`Couldn't start deep dive: ${e.message}`),
      },
    );

  return (
    <div className="card border-accent/25 p-4">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-accent">
          <Telescope size={13} /> Go Deep
          {dive?.state === "done" && (
            <span className="font-medium normal-case text-ink-faint">
              · {dive.model} · read {dive.docs_read ?? 0} doc{(dive.docs_read ?? 0) === 1 ? "" : "s"}
            </span>
          )}
        </div>
        {report && !running && (
          <button onClick={() => go(true)} disabled={start.isPending}
                  className="text-xs font-semibold text-accent hover:underline disabled:opacity-50">
            Re-run
          </button>
        )}
      </div>

      {dive?.state === "error" && (
        <div className="mb-3 flex items-start gap-2 rounded-[10px] bg-danger-soft px-3 py-2 text-[13px] text-danger">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <div>
            Deep dive failed: {dive.error}
            <button onClick={() => go(true)} className="ml-2 font-bold underline">Try again</button>
          </div>
        </div>
      )}

      {running ? (
        <div className="flex items-center gap-3 py-2 text-sm text-ink-soft">
          <Spinner size={18} />
          <div>
            <div className="font-semibold text-ink">Reading everything on this deal…</div>
            <div className="text-xs text-ink-faint">
              Downloading the documents and compiling dollar amounts, dates, scope and
              requirements. Usually one to two minutes — you can leave this page.
            </div>
          </div>
        </div>
      ) : report ? (
        <div className="space-y-4 text-sm">
          <p className="leading-relaxed text-ink">{report.overview}</p>

          {report.dollar_amounts.length > 0 && (
            <DeepSection title={`Every dollar amount (${report.dollar_amounts.length})`}>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <tbody>
                    {report.dollar_amounts.map((d, i) => (
                      <tr key={i} className="border-b border-line last:border-0">
                        <td className="py-1.5 pr-3 text-ink-soft">{d.label}</td>
                        <td className="money whitespace-nowrap py-1.5 pr-3 text-right font-bold">
                          {d.amount}
                        </td>
                        <td className="hidden py-1.5 text-right text-xs text-ink-faint sm:table-cell">
                          {d.source ?? ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </DeepSection>
          )}

          {report.key_dates.length > 0 && (
            <DeepSection title="Dates that matter">
              <div className="space-y-1.5">
                {report.key_dates.map((d, i) => (
                  <div key={i} className="flex items-baseline justify-between gap-2 text-[13px]">
                    <span className="text-ink-soft">
                      {d.label}
                      {d.note && <span className="text-ink-faint"> — {d.note}</span>}
                    </span>
                    <span className="whitespace-nowrap font-semibold">{d.date}</span>
                  </div>
                ))}
              </div>
            </DeepSection>
          )}

          {report.scope_items.length > 0 && (
            <DeepSection title="Scope, line by line">
              <Bullets items={report.scope_items} />
            </DeepSection>
          )}

          {report.requirements.length > 0 && (
            <DeepSection title="Requirements">
              <div className="space-y-1">
                {report.requirements.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 text-[13px] text-ink-soft">
                    <span className="mt-px shrink-0 rounded bg-bg px-1.5 py-0.5 text-[10px] font-bold uppercase text-ink-faint">
                      {REQ_CATEGORY_LABEL[r.category] ?? r.category}
                    </span>
                    <span>{r.item}</span>
                  </div>
                ))}
              </div>
            </DeepSection>
          )}

          {report.evaluation.length > 0 && (
            <DeepSection title="How the award is decided">
              <Bullets items={report.evaluation} />
            </DeepSection>
          )}

          {report.red_flags.length > 0 && (
            <DeepSection title="Red flags">
              <Bullets items={report.red_flags} tone="danger" />
            </DeepSection>
          )}

          {report.open_questions.length > 0 && (
            <DeepSection title="Worth asking before the deadline">
              <ul className="space-y-1">
                {report.open_questions.map((q, i) => (
                  <li key={i} className="flex gap-1.5 text-[13px] text-ink-soft">
                    <HelpCircle size={13} className="mt-0.5 shrink-0 text-warn" />
                    <span>{q}</span>
                  </li>
                ))}
              </ul>
            </DeepSection>
          )}

          {report.contacts.length > 0 && (
            <DeepSection title="Contacts">
              <div className="space-y-1.5 text-[13px]">
                {report.contacts.map((c, i) => (
                  <div key={i} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold text-ink">{c.name}</span>
                    {c.role && <span className="text-ink-faint">{c.role}</span>}
                    {c.email && (
                      <a href={`mailto:${c.email}`} className="text-accent hover:underline">{c.email}</a>
                    )}
                    {c.phone && (
                      <a href={`tel:${c.phone}`} className="text-accent hover:underline">{c.phone}</a>
                    )}
                  </div>
                ))}
              </div>
            </DeepSection>
          )}

          {report.documents_reviewed.length > 0 && (
            <DeepSection title="What each document says">
              <div className="space-y-1.5">
                {report.documents_reviewed.map((d, i) => (
                  <div key={i} className="flex items-start gap-2 text-[13px]">
                    <FileText size={13} className="mt-0.5 shrink-0 text-ink-faint" />
                    <div>
                      <span className="font-semibold text-ink">{d.name}</span>
                      <span className="text-ink-soft"> — {d.gist}</span>
                    </div>
                  </div>
                ))}
              </div>
            </DeepSection>
          )}

          {report.fit_assessment && (
            <p className="rounded-[10px] bg-accent-soft/50 px-3 py-2 text-[13px] font-medium italic text-ink-soft">
              {report.fit_assessment}
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-start gap-2">
          <p className="text-[13px] text-ink-soft">
            Have Claude read <span className="font-semibold text-ink">every attached document</span> and
            compile the full picture: every dollar amount, every date, scope line items,
            requirements, evaluation criteria, red flags and the questions worth asking.
          </p>
          <Button kind="soft" onClick={() => go()} disabled={start.isPending}>
            🔭 Go Deep
          </Button>
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
          <DeepDiveCard bid={bid} />
          <ResearchCard bid={bid} />

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

/** Follow-up research: ask Claude to dig past what the documents say.
 *
 *  The deep dive is bounded by the bid package. The questions a bidder prices
 *  with — what did this go for last time, who won it, what does the agency
 *  usually pay — live on the open web, so this card sends them to Claude with
 *  web search and keeps the answers as a running thread on the deal. */
function ResearchCard({ bid }: { bid: OpportunityDetail }) {
  const { data: settings } = useSettings();
  const aiAvailable = settings?.capabilities.ai_available ?? false;
  const { data } = useResearch(bid.opportunity_id);
  const ask = useAskResearch();
  const [question, setQuestion] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  const running = data?.state === "running";
  const turns = data?.turns ?? [];

  useEffect(() => {
    if (running || turns.length) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [running, turns.length]);

  if (!aiAvailable) return null;

  const submit = (q: string) => {
    const text = q.trim();
    if (!text || running) return;
    ask.mutate(
      { id: bid.opportunity_id, question: text },
      {
        onSuccess: () => setQuestion(""),
        onError: (e) => toast.error(`Couldn't start research: ${e.message}`),
      },
    );
  };

  // Suggested questions stay useful mid-thread, but the openers matter most
  // before anything has been asked.
  const suggestions = (data?.suggested_questions ?? []).slice(0, turns.length ? 2 : 3);

  return (
    <div className="card border-accent/25 p-4">
      <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-accent">
        <Compass size={13} /> Dig deeper
        <span className="font-medium normal-case text-ink-faint">
          · web research on this deal — past awards, pricing, competitors
        </span>
      </div>

      <div className="space-y-3">
        {turns.map((t, i) => (
          <div key={i}>
            <div className="mb-1 flex items-start gap-2">
              <span className="mt-0.5 shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-bold text-accent">
                Q
              </span>
              <span className="text-sm font-semibold">{t.question}</span>
            </div>
            <div className="whitespace-pre-line pl-7 text-sm leading-relaxed text-ink-soft">
              {t.answer}
            </div>
            {t.citations.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5 pl-7">
                {t.citations.map((c) => (
                  <a key={c.url} href={c.url} target="_blank" rel="noreferrer"
                     className="flex max-w-60 items-center gap-1 rounded-full bg-bg px-2 py-0.5 text-[11px] font-medium text-ink-soft hover:text-accent">
                    <Link2 size={10} className="shrink-0" />
                    <span className="truncate">{c.title}</span>
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}

        {running && (
          <div className="flex items-center gap-2.5 pl-1 text-sm text-ink-soft">
            <Spinner size={16} />
            <span>
              Researching — searching the web for awards, prices and history…
            </span>
          </div>
        )}

        {data?.error && !running && (
          <div className="flex items-start gap-2 rounded-[10px] bg-danger-soft px-3 py-2 text-[13px] text-danger">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span>Research failed: {data.error}</span>
          </div>
        )}

        {!running && suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {suggestions.map((q) => (
              <button key={q} onClick={() => submit(q)}
                      className="rounded-full border border-line px-2.5 py-1 text-xs font-medium text-ink-soft transition-colors hover:border-accent hover:text-accent">
                {q}
              </button>
            ))}
          </div>
        )}

        <form
          className="flex items-center gap-2"
          onSubmit={(e) => { e.preventDefault(); submit(question); }}
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={running}
            placeholder={turns.length ? "Ask a follow-up…"
                                      : "e.g. What did they pay for this service before?"}
            className="w-full rounded-[10px] border border-line px-3 py-2 text-sm outline-none transition-colors placeholder:text-ink-faint focus:border-accent disabled:opacity-60"
          />
          <Button type="submit" disabled={running || !question.trim()}
                  className="!px-3 shrink-0">
            <Send size={15} />
          </Button>
        </form>
        <div ref={endRef} />
      </div>
    </div>
  );
}
