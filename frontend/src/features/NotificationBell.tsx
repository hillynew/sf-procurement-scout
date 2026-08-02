import { useState } from "react";
import { Bell, CheckCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useMarkNotificationsRead, useNotifications } from "../api/hooks";
import { fmtRelative } from "../lib/format";

const KIND_EMOJI: Record<string, string> = {
  watchlist_match: "👀",
  deadline_soon: "⏰",
  fetch_done: "✅",
  fetch_failed: "⚠️",
  summary_ready: "✨",
};

export default function NotificationBell() {
  const { data } = useNotifications();
  const markRead = useMarkNotificationsRead();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const unread = data?.unread_count ?? 0;

  const onItemClick = (id: number, oppId: string | null) => {
    markRead.mutate([id]);
    setOpen(false);
    if (oppId) navigate(`/bids/${oppId}`);
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative rounded-[10px] border border-line bg-surface p-2 text-ink-soft transition-colors hover:border-accent hover:text-accent"
        aria-label="Notifications"
      >
        <Bell size={17} />
        {unread > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="fade-up absolute right-0 z-40 mt-2 max-h-[70vh] w-80 overflow-y-auto rounded-[14px] border border-line bg-surface shadow-(--shadow-pop)">
            <div className="sticky top-0 flex items-center justify-between border-b border-line bg-surface px-3 py-2.5">
              <span className="text-xs font-bold uppercase tracking-wide text-ink-faint">
                Notifications
              </span>
              {unread > 0 && (
                <button
                  onClick={() => markRead.mutate("all")}
                  className="flex items-center gap-1 text-xs font-semibold text-accent hover:underline"
                >
                  <CheckCheck size={13} /> Mark all read
                </button>
              )}
            </div>
            {(data?.items ?? []).length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-ink-faint">
                Nothing yet — fetch some data ✨
              </div>
            )}
            {(data?.items ?? []).map((n) => (
              <button
                key={n.id}
                onClick={() => onItemClick(n.id, n.opportunity_id)}
                className={`block w-full border-b border-line px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-bg ${
                  n.read ? "opacity-55" : ""
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="mt-0.5">{KIND_EMOJI[n.kind] ?? "•"}</span>
                  <div className="min-w-0">
                    <div className="truncate text-[13px] font-semibold text-ink">{n.title}</div>
                    {n.body && (
                      <div className="truncate text-xs text-ink-soft">{n.body}</div>
                    )}
                    <div className="mt-0.5 text-[11px] text-ink-faint">
                      {fmtRelative(n.created_at)}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
