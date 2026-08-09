import type { ReactNode } from "react";
import { Loader2, Sparkles } from "lucide-react";
import {
  COUNTY_COLOR,
  COUNTY_SOFT,
  countyLabel,
  dueText,
  dueTone,
  fmtMoney,
  OFFER_LABEL,
} from "../lib/format";

export function CountyPill({ county, small }: { county: string; small?: boolean }) {
  const label = countyLabel(county);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold ${
        small ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"
      }`}
      style={{ background: COUNTY_SOFT[county] ?? "var(--color-closed-soft)",
               color: COUNTY_COLOR[county] ?? "var(--color-ink-soft)" }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: COUNTY_COLOR[county] ?? "var(--color-ink-faint)" }}
      />
      {label}
    </span>
  );
}

const STATUS_STYLE: Record<string, { bg: string; fg: string }> = {
  open: { bg: "var(--color-open-soft)", fg: "var(--color-open)" },
  upcoming: { bg: "var(--color-upcoming-soft)", fg: "var(--color-upcoming)" },
  closed: { bg: "var(--color-closed-soft)", fg: "var(--color-closed)" },
  cancelled: { bg: "var(--color-danger-soft)", fg: "var(--color-danger)" },
  // Award notices were falling through to the grey closed style, which made
  // the most time-critical status in the system invisible.
  award: { bg: "var(--color-warn-soft)", fg: "var(--color-warn)" },
  catalog: { bg: "var(--color-closed-soft)", fg: "var(--color-ink-soft)" },
};

export function StatusPill({ status }: { status: string }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.closed;
  return (
    <span className="rounded-full px-2.5 py-1 text-xs font-semibold capitalize"
          style={{ background: s.bg, color: s.fg }}>
      {status}
    </span>
  );
}

export function TypeTag({ offer }: { offer: string }) {
  const label = OFFER_LABEL[offer] ?? offer;
  if (label === "—") return null;
  return (
    <span className="rounded-md border border-line px-1.5 py-0.5 text-[11px] font-medium text-ink-soft">
      {label}
    </span>
  );
}

export function ValueTag({ amount, est = true, className = "" }: {
  amount: number | null | undefined; est?: boolean; className?: string;
}) {
  const text = fmtMoney(amount);
  if (!text) return null;
  return (
    <span className={`money text-sm ${className}`}>
      {text}
      {est && <span className="ml-0.5 text-[10px] font-medium opacity-70">est</span>}
    </span>
  );
}

const TONE_STYLE = {
  danger: { bg: "var(--color-danger-soft)", fg: "var(--color-danger)" },
  warn: { bg: "var(--color-warn-soft)", fg: "var(--color-warn)" },
  ok: { bg: "var(--color-open-soft)", fg: "var(--color-open)" },
  closed: { bg: "var(--color-closed-soft)", fg: "var(--color-closed)" },
  none: { bg: "var(--color-closed-soft)", fg: "var(--color-ink-faint)" },
} as const;

export function DueBadge({ days, status }: { days: number | null; status: string }) {
  const tone = TONE_STYLE[dueTone(days, status)];
  return (
    <span className="whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-bold"
          style={{ background: tone.bg, color: tone.fg }}>
      {dueText(days, status)}
    </span>
  );
}

export function DetailMeter({ score }: { score: number }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={`Detail score ${score}/100`}>
      <span className="h-1.5 w-10 overflow-hidden rounded-full bg-line">
        <span className="block h-full rounded-full bg-accent"
              style={{ width: `${score}%` }} />
      </span>
      <span className="text-[11px] font-semibold text-ink-faint">{score}</span>
    </span>
  );
}

export function NewDot() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-bold text-accent">
      NEW
    </span>
  );
}

export function AiDot() {
  return (
    <span title="AI brief ready"
          className="inline-flex items-center rounded-full bg-accent-soft p-1 text-accent">
      <Sparkles size={11} />
    </span>
  );
}

export function StatCard({ label, value, sub, accent }: {
  label: string; value: ReactNode; sub?: ReactNode; accent?: boolean;
}) {
  return (
    <div className="card flex-1 px-4 py-3.5">
      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${accent ? "text-accent" : "text-ink"}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-ink-soft">{sub}</div>}
    </div>
  );
}

export function SegmentedControl<T extends string>({ options, value, onChange }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-[10px] border border-line bg-bg p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
            value === o.value
              ? "bg-surface text-ink shadow-sm"
              : "text-ink-soft hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function FilterChip({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
        active
          ? "border-accent bg-accent text-white"
          : "border-line bg-surface text-ink-soft hover:border-accent hover:text-accent"
      }`}
    >
      {children}
    </button>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="animate-spin text-ink-faint" />;
}

export function LoadFailed({ what, onRetry }: { what: string; onRetry?: () => void }) {
  return (
    <div className="card mx-auto my-16 max-w-md p-6 text-center">
      <div className="text-sm font-bold">Couldn't load {what}</div>
      <p className="mt-1 text-sm text-ink-soft">
        The server didn't answer. If the app just woke up, give it a few
        seconds — free-tier hosting sleeps when idle.
      </p>
      {onRetry && (
        <button onClick={onRetry}
                className="mt-3 rounded-[10px] border border-line px-3 py-1.5 text-sm font-semibold hover:border-accent hover:text-accent">
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, body, action }: {
  title: string; body?: string; action?: ReactNode;
}) {
  return (
    <div className="card fade-up mx-auto my-16 flex max-w-md flex-col items-center gap-3 px-8 py-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft text-2xl">
        🔎
      </div>
      <h2 className="text-lg font-bold">{title}</h2>
      {body && <p className="text-sm text-ink-soft">{body}</p>}
      {action}
    </div>
  );
}

export function Button({ children, onClick, kind = "primary", disabled, type, className = "" }: {
  children: ReactNode;
  onClick?: () => void;
  kind?: "primary" | "ghost" | "danger" | "soft";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  const styles = {
    primary: "bg-accent text-white hover:bg-accent-deep",
    soft: "bg-accent-soft text-accent hover:bg-accent hover:text-white",
    ghost: "border border-line bg-surface text-ink-soft hover:border-accent hover:text-accent",
    danger: "bg-danger-soft text-danger hover:bg-danger hover:text-white",
  } as const;
  return (
    <button
      type={type ?? "button"}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-[10px] px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles[kind]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Modal({ title, onClose, children, wide }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 p-0 sm:items-center sm:p-6"
         onClick={onClose}>
      <div
        className={`sheet-in card max-h-[92vh] w-full overflow-y-auto rounded-b-none p-5 sm:rounded-b-[14px] ${
          wide ? "sm:max-w-2xl" : "sm:max-w-md"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-bold">{title}</h3>
          <button onClick={onClose}
                  className="rounded-lg px-2 py-1 text-ink-faint hover:bg-bg hover:text-ink">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
