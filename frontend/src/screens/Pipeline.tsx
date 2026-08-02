import { useMemo, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { Link, useNavigate } from "react-router-dom";
import { Archive, ChevronDown, MoreHorizontal, Trophy } from "lucide-react";
import { toast } from "sonner";
import { useBidMutation, useOpportunities } from "../api/hooks";
import type { Opportunity } from "../api/types";
import {
  Button,
  CountyPill,
  DueBadge,
  EmptyState,
  Modal,
  Spinner,
  ValueTag,
} from "../components/ui";
import SortControl from "../components/SortControl";
import {
  fmtMoney,
  fmtMoneyCents,
  fmtMoneyFull,
  STAGE_LABEL,
  STAGES,
} from "../lib/format";
import { PIPELINE_SORT_KEYS, sortOpportunities, useSortPref } from "../lib/sort";

function unmetCount(o: Opportunity): number {
  return o.requirements.filter((_, i) => !o.checks[String(i)]).length;
}

function KanbanCard({ bid, onMove, onResult, dragging }: {
  bid: Opportunity;
  onMove: (stage: string) => void;
  onResult: () => void;
  dragging?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: bid.opportunity_id,
  });
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const unmet = unmetCount(bid);

  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      style={transform ? { transform: `translate(${transform.x}px, ${transform.y}px)`, zIndex: 30 } : undefined}
      className={`card cursor-grab touch-manipulation p-3 active:cursor-grabbing ${
        dragging ? "opacity-40" : ""
      }`}
      onClick={() => navigate(`/bids/${bid.opportunity_id}`)}
    >
      <div className="flex items-start justify-between gap-1">
        <div className="text-[13px] font-bold leading-snug">{bid.title}</div>
        <div className="relative shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
            onPointerDown={(e) => e.stopPropagation()}
            className="rounded p-0.5 text-ink-faint hover:bg-bg hover:text-ink"
            aria-label="Move to…"
          >
            <MoreHorizontal size={15} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-30"
                   onClick={(e) => { e.stopPropagation(); setMenuOpen(false); }}
                   onPointerDown={(e) => e.stopPropagation()} />
              <div className="absolute right-0 z-40 mt-1 w-40 rounded-[10px] border border-line bg-surface py-1 shadow-(--shadow-pop)"
                   onPointerDown={(e) => e.stopPropagation()}>
                {STAGES.filter((s) => s !== bid.stage).map((s) => (
                  <button key={s}
                          onClick={(e) => {
                            e.stopPropagation();
                            setMenuOpen(false);
                            if (s === "result") onResult();
                            else onMove(s);
                          }}
                          className="block w-full px-3 py-1.5 text-left text-xs font-semibold text-ink-soft hover:bg-bg hover:text-ink">
                    Move to {STAGE_LABEL[s]}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <CountyPill county={bid.county} small />
        <DueBadge days={bid.days_until_due} status={bid.status} />
        <ValueTag amount={bid.budget_amount} />
      </div>

      {bid.stage !== "result" && unmet > 0 && (
        <div className="mt-2 text-[11px] font-semibold text-warn">
          {unmet} requirement{unmet > 1 ? "s" : ""} unmet
        </div>
      )}
      {bid.result && (
        <div className={`mt-2 text-xs font-bold ${
          bid.result.outcome === "won" ? "text-open" : "text-danger"}`}>
          {bid.result.outcome === "won" ? "🏆 WON" : "LOST"}
          {bid.result.amount_cents != null && ` · ${fmtMoneyFull(bid.result.amount_cents)}`}
        </div>
      )}
      {bid.decision === "nogo" && (
        <div className="mt-2 text-[11px] font-bold uppercase text-ink-faint">passed (no-go)</div>
      )}
    </div>
  );
}

function Column({ stage, bids, onMove, onResult, activeId }: {
  stage: string;
  bids: Opportunity[];
  onMove: (id: string, stage: string) => void;
  onResult: (id: string) => void;
  activeId: string | null;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage });
  const total = bids.reduce((sum, b) => sum + (b.budget_amount ?? 0), 0);
  return (
    <div
      ref={setNodeRef}
      className={`flex w-72 shrink-0 snap-start flex-col rounded-[14px] border p-2.5 transition-colors md:w-auto md:flex-1 ${
        isOver ? "border-accent bg-accent-soft/40" : "border-line bg-bg/60"
      }`}
    >
      <div className="mb-2 flex items-baseline justify-between px-1">
        <span className="text-xs font-extrabold uppercase tracking-wide text-ink-soft">
          {STAGE_LABEL[stage]} · {bids.length}
        </span>
        {total > 0 && <span className="money text-xs">{fmtMoney(total)}</span>}
      </div>
      <div className="flex min-h-24 flex-col gap-2">
        {bids.map((b) => (
          <KanbanCard key={b.opportunity_id} bid={b}
                      dragging={activeId === b.opportunity_id}
                      onMove={(s) => onMove(b.opportunity_id, s)}
                      onResult={() => onResult(b.opportunity_id)} />
        ))}
        {bids.length === 0 && (
          <div className="rounded-[10px] border border-dashed border-line py-6 text-center text-xs text-ink-faint">
            drop bids here
          </div>
        )}
      </div>
    </div>
  );
}

export default function Pipeline() {
  const { data, isLoading } = useOpportunities();
  const mutate = useBidMutation();
  const [resultFor, setResultFor] = useState<Opportunity | null>(null);
  const [showArchive, setShowArchive] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
  );

  const tracked = useMemo(
    () => (data?.opportunities ?? []).filter((o) => o.tracked && !o.archived),
    [data],
  );
  const archived = useMemo(
    () => (data?.opportunities ?? []).filter((o) => o.tracked && o.archived),
    [data],
  );

  const [sort, setSort] = useSortPref("pipeline", { key: "due", dir: "asc" });

  const byStage = useMemo(() => {
    const map: Record<string, Opportunity[]> = {};
    for (const s of STAGES) map[s] = [];
    for (const o of tracked) map[o.stage ?? "watching"]?.push(o);
    for (const s of STAGES) map[s] = sortOpportunities(map[s], sort.key, sort.dir);
    return map;
  }, [tracked, sort]);

  const decided = [...tracked, ...archived].filter((o) => o.result);
  const won = decided.filter((o) => o.result?.outcome === "won");
  const revenue = won.reduce((sum, o) => sum + (o.result?.amount_cents ?? 0), 0);

  const move = async (id: string, stage: string) => {
    if (stage === "result") {
      const bid = tracked.find((o) => o.opportunity_id === id);
      if (bid) setResultFor(bid);
      return;
    }
    await mutate.mutateAsync({ id, action: "stage", body: { stage } });
    toast.success(`Moved to ${STAGE_LABEL[stage]}`);
  };

  const onDragEnd = (event: DragEndEvent) => {
    setActiveId(null);
    const stage = event.over?.id as string | undefined;
    const id = event.active.id as string;
    if (!stage || !STAGES.includes(stage as (typeof STAGES)[number])) return;
    const bid = tracked.find((o) => o.opportunity_id === id);
    if (!bid || bid.stage === stage) return;
    void move(id, stage);
  };

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;

  if (tracked.length === 0 && archived.length === 0) {
    return (
      <EmptyState
        title="Your pipeline is empty"
        body="Track bids from All Bids or the Calendar and they'll appear here, moving from Watching to Result."
        action={<Link to="/bids" className="rounded-[10px] bg-accent px-4 py-2 text-sm font-bold text-white">Browse bids</Link>}
      />
    );
  }

  const activeBid = tracked.find((o) => o.opportunity_id === activeId);

  return (
    <div className="fade-up">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">My pipeline</h1>
          <p className="text-sm text-ink-soft">
            {tracked.length} active · drag cards between stages
          </p>
        </div>
        <SortControl keys={PIPELINE_SORT_KEYS} pref={sort} onChange={setSort} />
        {decided.length > 0 && (
          <div className="card flex items-center gap-4 px-4 py-2 text-sm">
            <span className="flex items-center gap-1.5 font-bold text-open">
              <Trophy size={15} /> {won.length}W – {decided.length - won.length}L
            </span>
            <span className="text-ink-faint">
              {Math.round((won.length / decided.length) * 100)}% win rate
            </span>
            {revenue > 0 && <span className="money">{fmtMoneyCents(revenue)} won</span>}
          </div>
        )}
      </div>

      <DndContext sensors={sensors} onDragStart={(e) => setActiveId(e.active.id as string)}
                  onDragEnd={onDragEnd} onDragCancel={() => setActiveId(null)}>
        <div className="scrollbar-none flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2 md:snap-none">
          {STAGES.map((stage) => (
            <Column key={stage} stage={stage} bids={byStage[stage]}
                    activeId={activeId}
                    onMove={move}
                    onResult={(id) => {
                      const bid = tracked.find((o) => o.opportunity_id === id);
                      if (bid) setResultFor(bid);
                    }} />
          ))}
        </div>
        <DragOverlay>
          {activeBid && (
            <div className="card w-64 rotate-2 p-3 shadow-(--shadow-pop)">
              <div className="text-[13px] font-bold">{activeBid.title}</div>
            </div>
          )}
        </DragOverlay>
      </DndContext>

      {archived.length > 0 && (
        <div className="mt-6">
          <button onClick={() => setShowArchive(!showArchive)}
                  className="flex items-center gap-1.5 text-sm font-bold text-ink-soft hover:text-ink">
            <Archive size={15} /> Archive · {archived.length}
            <ChevronDown size={15} className={showArchive ? "rotate-180" : ""} />
          </button>
          {showArchive && (
            <div className="mt-3 space-y-2">
              {archived.map((o) => (
                <div key={o.opportunity_id} className="card flex items-center gap-3 px-4 py-2.5">
                  <Link to={`/bids/${o.opportunity_id}`}
                        className="min-w-0 flex-1 truncate text-sm font-semibold hover:text-accent">
                    {o.title}
                  </Link>
                  {o.result && (
                    <span className={`text-xs font-bold ${
                      o.result.outcome === "won" ? "text-open" : "text-danger"}`}>
                      {o.result.outcome.toUpperCase()}
                      {o.result.amount_cents != null && ` · ${fmtMoneyFull(o.result.amount_cents)}`}
                    </span>
                  )}
                  <Button kind="ghost" className="!px-2.5 !py-1 text-xs"
                          onClick={() => mutate.mutate({ id: o.opportunity_id, action: "unarchive" })}>
                    Restore
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {resultFor && (
        <ResultDialog bid={resultFor} onClose={() => setResultFor(null)} />
      )}
    </div>
  );
}

function ResultDialog({ bid, onClose }: { bid: Opportunity; onClose: () => void }) {
  const mutate = useBidMutation();
  const [outcome, setOutcome] = useState<"won" | "lost">(bid.result?.outcome ?? "won");
  const [amount, setAmount] = useState(
    bid.result?.amount_cents != null ? String(bid.result.amount_cents / 100)
      : bid.budget_amount != null ? String(bid.budget_amount) : "",
  );
  const [notes, setNotes] = useState(bid.result?.notes ?? "");

  const save = async () => {
    const dollars = parseFloat(amount.replace(/[^0-9.]/g, ""));
    await mutate.mutateAsync({
      id: bid.opportunity_id,
      action: "result",
      body: {
        outcome,
        amount_cents: Number.isFinite(dollars) ? Math.round(dollars * 100) : null,
        notes,
      },
    });
    toast.success(outcome === "won" ? "🏆 Marked as won!" : "Recorded — next one's yours");
    onClose();
  };

  return (
    <Modal title="Record result" onClose={onClose}>
      <div className="mb-1 text-sm font-semibold">{bid.title}</div>
      <div className="mb-4 text-xs text-ink-soft">{bid.agency}</div>

      <div className="mb-4 grid grid-cols-2 gap-2">
        {(["won", "lost"] as const).map((o) => (
          <button key={o} onClick={() => setOutcome(o)}
                  className={`rounded-[10px] border-2 py-2.5 text-sm font-extrabold uppercase transition-colors ${
                    outcome === o
                      ? o === "won"
                        ? "border-open bg-open-soft text-open"
                        : "border-danger bg-danger-soft text-danger"
                      : "border-line text-ink-faint hover:border-ink-faint"
                  }`}>
            {o === "won" ? "🏆 Won" : "Lost"}
          </button>
        ))}
      </div>

      <label className="mb-3 block">
        <span className="mb-1 block text-xs font-bold text-ink-soft">
          {outcome === "won" ? "Contract amount" : "Winning bid (if known)"}
        </span>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-bold text-ink-faint">$</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)}
                 inputMode="decimal" placeholder="92,400"
                 className="w-full rounded-[10px] border border-line py-2.5 pl-7 pr-3 text-sm outline-none focus:border-accent" />
        </div>
      </label>

      <label className="mb-4 block">
        <span className="mb-1 block text-xs font-bold text-ink-soft">Notes</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
                  placeholder="What decided it?"
                  className="w-full rounded-[10px] border border-line px-3 py-2.5 text-sm outline-none focus:border-accent" />
      </label>

      <div className="flex justify-end gap-2">
        <Button kind="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={save} disabled={mutate.isPending}>
          {mutate.isPending ? "Saving…" : "Save result"}
        </Button>
      </div>
    </Modal>
  );
}
