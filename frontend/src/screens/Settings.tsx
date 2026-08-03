import { useState } from "react";
import { Link } from "react-router-dom";
import { Database, Download, Radar } from "lucide-react";
import { toast } from "sonner";
import {
  useLoadDemo,
  useOpportunities,
  usePurge,
  useSettings,
  useSettingsMutation,
  useTestDigestEmail,
} from "../api/hooks";
import { Button, SegmentedControl, Spinner } from "../components/ui";
import { fmtRelative } from "../lib/format";

function Row({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <div className="text-sm font-semibold">{label}</div>
        {hint && <div className="text-xs text-ink-soft">{hint}</div>}
      </div>
      {children}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card px-4 py-2">
      <div className="border-b border-line py-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
        {title}
      </div>
      <div className="divide-y divide-line">{children}</div>
    </div>
  );
}

function Toggle({ checked, onChange, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <button onClick={() => onChange(!checked)} disabled={disabled}
            className={`h-6 w-11 shrink-0 rounded-full p-0.5 transition-colors disabled:opacity-40 ${
              checked ? "bg-accent" : "bg-line"}`}
            role="switch" aria-checked={checked}>
      <span className={`block h-5 w-5 rounded-full bg-white shadow transition-transform ${
        checked ? "translate-x-5" : ""}`} />
    </button>
  );
}

export default function SettingsScreen() {
  const { data, isLoading } = useSettings();
  const save = useSettingsMutation();
  const purge = usePurge();
  const demo = useLoadDemo();
  const testEmail = useTestDigestEmail();
  const { data: snapshot } = useOpportunities();
  const [confirmTarget, setConfirmTarget] = useState<string | null>(null);

  if (isLoading || !data) {
    return <div className="flex justify-center py-24"><Spinner size={26} /></div>;
  }
  const { settings, capabilities } = data;

  const patch = (section: string, values: Record<string, unknown>) =>
    save.mutate({ [section]: values }, {
      onSuccess: () => toast.success("Settings saved"),
      onError: (e) => toast.error(`Couldn't save: ${e.message}`),
    });

  const sendTestEmail = () =>
    testEmail.mutate(undefined, {
      onSuccess: (r) =>
        r.sent
          ? toast.success(`Test email sent to ${r.recipient}`)
          : toast.error(r.error ?? "Resend didn't accept the message"),
      onError: (e) => toast.error(`Couldn't send: ${e.message}`),
    });

  const doPurge = (target: string) => {
    purge.mutate(target, {
      onSuccess: () => { setConfirmTarget(null); toast.success("Cleared"); },
    });
  };

  return (
    <div className="fade-up mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-extrabold">Settings</h1>
        <p className="text-sm text-ink-soft">Fetching, notifications, AI, and your data</p>
      </div>

      <Card title="Auto-fetch">
        <Row label="Refresh mode"
             hint="Runs while the app is awake — on Render's free tier that means while you're using it.">
          <SegmentedControl
            value={settings.auto_fetch.mode}
            onChange={(mode) => patch("auto_fetch", { mode })}
            options={[
              { value: "off", label: "Manual" },
              { value: "on_open", label: "On open" },
              { value: "interval", label: "Every N hrs" },
            ]}
          />
        </Row>
        {settings.auto_fetch.mode === "interval" && (
          <Row label="Interval">
            <SegmentedControl
              value={String(settings.auto_fetch.interval_minutes)}
              onChange={(v) => patch("auto_fetch", { interval_minutes: parseInt(v, 10) })}
              options={[
                { value: "120", label: "2h" },
                { value: "240", label: "4h" },
                { value: "480", label: "8h" },
                { value: "1440", label: "Daily" },
              ]}
            />
          </Row>
        )}
        {settings.auto_fetch.mode === "on_open" && (
          <Row label="Refresh when data is older than">
            <SegmentedControl
              value={String(settings.auto_fetch.stale_minutes)}
              onChange={(v) => patch("auto_fetch", { stale_minutes: parseInt(v, 10) })}
              options={[
                { value: "120", label: "2h" },
                { value: "360", label: "6h" },
                { value: "720", label: "12h" },
              ]}
            />
          </Row>
        )}
      </Card>

      <Card title="Notifications">
        <Row label="Deadline reminders" hint="Tracked bids approaching their due date">
          <SegmentedControl
            value={String(settings.notifications.deadline_days)}
            onChange={(v) => patch("notifications", { deadline_days: parseInt(v, 10) })}
            options={[
              { value: "3", label: "3 days" },
              { value: "5", label: "5 days" },
              { value: "7", label: "7 days" },
            ]}
          />
        </Row>
        <Row label="Watchlist matches" hint="Notify when a fetch finds new matching bids">
          <Toggle checked={settings.notifications.watchlist}
                  onChange={(v) => patch("notifications", { watchlist: v })} />
        </Row>
        <Row label="Fetch results" hint="Notify when fetches finish or fail">
          <Toggle checked={settings.notifications.fetch_events}
                  onChange={(v) => patch("notifications", { fetch_events: v })} />
        </Row>
      </Card>

      <Card title="Email digest">
        {!capabilities.email_available && (
          <div className="my-3 rounded-[10px] bg-bg px-3 py-2.5 text-xs text-ink-soft">
            Email is off because <code className="rounded bg-surface px-1">RESEND_API_KEY</code> isn't
            set. Add it (free at resend.com) plus a recipient below, and digests light up.
          </div>
        )}
        <Row label="Send digests">
          <Toggle checked={settings.digest.enabled}
                  disabled={!capabilities.email_available}
                  onChange={(v) => patch("digest", { enabled: v })} />
        </Row>
        <Row label="Cadence" hint="Instant sends after each fetch with new matches">
          <SegmentedControl
            value={settings.digest.cadence}
            onChange={(cadence) => patch("digest", { cadence })}
            options={[
              { value: "daily", label: "Daily" },
              { value: "instant", label: "Instant" },
            ]}
          />
        </Row>
        {settings.digest.cadence === "daily" && (
          <Row label="Send at (UTC)">
            <SegmentedControl
              value={String(settings.digest.hour)}
              onChange={(v) => patch("digest", { hour: parseInt(v, 10) })}
              options={[
                { value: "7", label: "7am" },
                { value: "12", label: "noon" },
                { value: "17", label: "5pm" },
              ]}
            />
          </Row>
        )}
        <Row label="Recipient">
          <input
            defaultValue={settings.digest.email}
            onBlur={(e) => e.target.value !== settings.digest.email &&
              patch("digest", { email: e.target.value.trim() })}
            placeholder="you@company.com"
            className="w-56 rounded-[10px] border border-line px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </Row>
        <Row label="Test email" hint="Sends one message now so you can confirm delivery">
          <Button kind="ghost"
                  disabled={!capabilities.email_available || testEmail.isPending}
                  onClick={sendTestEmail}>
            {testEmail.isPending ? "Sending…" : "Send test email"}
          </Button>
        </Row>
      </Card>

      <Card title="AI briefs">
        {!capabilities.ai_available && (
          <div className="my-3 rounded-[10px] bg-bg px-3 py-2.5 text-xs text-ink-soft">
            AI briefs are off because no API key is set. Add{" "}
            <code className="rounded bg-surface px-1">SF_SCOUT_ANTHROPIC_KEY</code> to the
            environment; costs are roughly a cent per 50 bids on the default model.
          </div>
        )}
        <Row label="Model">
          <SegmentedControl
            value={settings.ai.model}
            onChange={(model) => patch("ai", { model })}
            options={capabilities.ai_models.map((m) => ({
              value: m,
              label: m.includes("haiku") ? "Haiku (fast)" : "Sonnet (smart)",
            }))}
          />
        </Row>
        <Row label="Auto-summarize tracked bids" hint="After each fetch, brief anything you track">
          <Toggle checked={settings.ai.auto_summarize_tracked}
                  disabled={!capabilities.ai_available}
                  onChange={(v) => patch("ai", { auto_summarize_tracked: v })} />
        </Row>
      </Card>

      <Card title="Data">
        <Row label="Storage"
             hint={capabilities.db_backend === "postgres"
               ? "Postgres — survives restarts and deploys"
               : "SQLite file — fine locally; use Postgres on Render"}>
          <span className="flex items-center gap-1.5 rounded-full bg-bg px-3 py-1.5 text-xs font-bold uppercase text-ink-soft">
            <Database size={13} /> {capabilities.db_backend}
          </span>
        </Row>
        <Row label="Snapshot"
             hint={snapshot?.fetched_at
               ? `${snapshot.count} bids, fetched ${fmtRelative(snapshot.fetched_at)}`
               : "No data yet"}>
          <a href="/api/export.csv"
             className="flex items-center gap-1.5 rounded-[10px] border border-line px-3 py-2 text-xs font-bold text-ink-soft hover:border-accent hover:text-accent">
            <Download size={13} /> Export CSV
          </a>
        </Row>
        <Row label="Sources" hint="Manage the monitored portals">
          <Link to="/sources"
                className="flex items-center gap-1.5 rounded-[10px] border border-line px-3 py-2 text-xs font-bold text-ink-soft hover:border-accent hover:text-accent">
            <Radar size={13} /> Open sources
          </Link>
        </Row>
        <Row label="Demo data" hint="Load the sample snapshot (never overwrites a real pipeline)">
          <Button kind="ghost" onClick={() => demo.mutate(undefined, {
            onSuccess: () => toast.success("Sample data loaded"),
          })}>
            Load sample
          </Button>
        </Row>
        {[
          ["snapshot", "Clear bid snapshot", "Removes fetched bids and run history"],
          ["workflow", "Clear my pipeline", "Removes tracked bids, notes, results"],
          ["summaries", "Clear AI briefs", "Regenerate summaries from scratch"],
          ["contractors", "Clear contractor network", "Removes every matched firm and its bid matches"],
          ["notifications", "Clear notifications", ""],
        ].map(([target, label, hint]) => (
          <Row key={target} label={label} hint={hint || undefined}>
            {confirmTarget === target ? (
              <div className="flex gap-1.5">
                <Button kind="danger" className="!py-1.5 text-xs" onClick={() => doPurge(target)}>
                  Confirm
                </Button>
                <Button kind="ghost" className="!py-1.5 text-xs" onClick={() => setConfirmTarget(null)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button kind="ghost" className="!py-1.5 text-xs" onClick={() => setConfirmTarget(target)}>
                Clear…
              </Button>
            )}
          </Row>
        ))}
      </Card>
    </div>
  );
}
