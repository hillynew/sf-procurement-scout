import { useEffect, useMemo, useState } from "react";
import { Copy, Mail, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  useOpportunities,
  useSettings,
  useTaxonomy,
  useWatchlistMatches,
  useWatchlistMutation,
  useWatchlists,
} from "../api/hooks";
import type { TaxonomyResponse, Watchlist, WatchlistRules } from "../api/types";
import BidRow from "../components/BidRow";
import MultiSelect, { type MultiSelectOption } from "../components/MultiSelect";
import SortControl from "../components/SortControl";
import { Button, EmptyState, FilterChip, Modal, NewDot, Spinner } from "../components/ui";
import { COUNTY_LABEL, fmtMoney, OFFER_LABEL } from "../lib/format";
import { BID_SORT_KEYS, sortOpportunities, useSortPref } from "../lib/sort";

/** Rule chips read from the taxonomy when it has loaded, and degrade to the
 *  built-in labels when it hasn't — a watchlist card should never render a raw
 *  slug like `mosquito_control` just because a request is in flight. */
function ruleChips(rules: WatchlistRules, tax?: TaxonomyResponse): string[] {
  const catLabel = (slug: string) =>
    tax?.categories.find((c) => c.slug === slug)?.label ?? slug.replace(/_/g, " ");
  const countyLabel = (slug: string) =>
    tax?.county_labels[slug] ?? COUNTY_LABEL[slug] ?? slug;

  const chips: string[] = [];
  for (const kw of rules.keywords ?? []) chips.push(`“${kw}”`);
  for (const c of rules.categories ?? []) chips.push(catLabel(c));
  for (const c of rules.counties ?? []) chips.push(countyLabel(c));
  for (const o of rules.offers ?? []) chips.push(OFFER_LABEL[o] ?? o);
  if (rules.min_value) chips.push(`≥ ${fmtMoney(rules.min_value)}`);
  if (rules.max_value) chips.push(`≤ ${fmtMoney(rules.max_value)}`);
  if (rules.no_bond) chips.push("no bond");
  if (rules.recurring_only) chips.push("recurring");
  return chips;
}

export default function Watchlists() {
  const { data, isLoading } = useWatchlists();
  const { data: settings } = useSettings();
  const { data: tax } = useTaxonomy();
  const mutations = useWatchlistMutation();
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<Watchlist | "new" | null>(null);

  const lists = data?.watchlists ?? [];
  const active = lists.find((w) => w.id === selected) ?? lists[0] ?? null;
  const { data: matchData, isLoading: matchesLoading } = useWatchlistMatches(active?.id ?? null);
  const [sort, setSort] = useSortPref("watchlists", { key: "due", dir: "asc" });
  const matches = sortOpportunities(matchData?.matches ?? [], sort.key, sort.dir);

  // Viewing a list clears its NEW badge after a moment.
  useEffect(() => {
    if (!active || !matchData || active.new_count === 0) return;
    const t = setTimeout(() => mutations.markSeen.mutate(active.id), 2000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id, matchData]);

  const remove = (wl: Watchlist) => {
    if (!confirm(`Delete “${wl.name}”? This can't be undone.`)) return;
    mutations.remove.mutate(wl.id, {
      onSuccess: () => {
        if (selected === wl.id) setSelected(null);
        toast.success("Watchlist deleted");
      },
    });
  };

  const duplicate = (wl: Watchlist) =>
    mutations.create.mutate(
      { name: `${wl.name} (copy)`, rules: wl.rules, email_digest: wl.email_digest },
      { onSuccess: (created) => { setSelected(created.id); toast.success("Watchlist duplicated"); } },
    );

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;

  return (
    <div className="fade-up">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Watchlists</h1>
          <p className="text-sm text-ink-soft">Saved searches that flag new matches</p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <span className="flex items-center gap-1.5"><Plus size={15} /> New watchlist</span>
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <div className="space-y-2">
          {lists.map((wl) => {
            const chips = ruleChips(wl.rules, tax);
            return (
            <div
              key={wl.id}
              onClick={() => setSelected(wl.id)}
              className={`card group w-full cursor-pointer p-3.5 text-left transition-colors ${
                active?.id === wl.id ? "border-accent" : "hover:border-accent/40"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-bold">{wl.name}</span>
                <div className="flex shrink-0 items-center gap-1">
                  {wl.new_count > 0 && <NewDot />}
                  {/* Always rendered, revealed on hover/focus: editing a saved
                      search is the point of the screen, so it shouldn't be
                      reachable only after selecting the row. */}
                  <div className="flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                    <button
                      aria-label={`Edit ${wl.name}`}
                      onClick={(e) => { e.stopPropagation(); setEditing(wl); }}
                      className="rounded p-1 text-ink-faint hover:bg-bg hover:text-accent"
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      aria-label={`Duplicate ${wl.name}`}
                      onClick={(e) => { e.stopPropagation(); duplicate(wl); }}
                      className="rounded p-1 text-ink-faint hover:bg-bg hover:text-accent"
                    >
                      <Copy size={12} />
                    </button>
                    <button
                      aria-label={`Delete ${wl.name}`}
                      onClick={(e) => { e.stopPropagation(); remove(wl); }}
                      className="rounded p-1 text-ink-faint hover:bg-bg hover:text-danger"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {chips.slice(0, 6).map((c, i) => (
                  <span key={i} className="rounded-full bg-bg px-2 py-0.5 text-[11px] font-medium text-ink-soft">
                    {c}
                  </span>
                ))}
                {chips.length > 6 && (
                  <span className="rounded-full bg-bg px-2 py-0.5 text-[11px] font-medium text-ink-faint">
                    +{chips.length - 6}
                  </span>
                )}
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-ink-faint">
                <span>{wl.match_count} match{wl.match_count !== 1 ? "es" : ""}</span>
                {wl.email_digest && (
                  <span className="flex items-center gap-1 text-accent"><Mail size={11} /> digest</span>
                )}
              </div>
            </div>
            );
          })}
          {lists.length === 0 && (
            <EmptyState title="No watchlists" body="Create one to get flagged when matching bids appear." />
          )}
        </div>

        <div>
          {active && (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-bold">
                {active.name}
                <span className="ml-2 text-sm font-medium text-ink-faint">
                  {active.match_count} open match{active.match_count !== 1 ? "es" : ""}
                </span>
              </h2>
              <div className="flex items-center gap-1.5">
                <SortControl keys={BID_SORT_KEYS} pref={sort} onChange={setSort} />
                <Button kind="ghost" className="!px-2.5 !py-1.5" onClick={() => setEditing(active)}>
                  <span className="flex items-center gap-1 text-xs"><Pencil size={13} /> Edit</span>
                </Button>
                <Button kind="danger" className="!px-2.5 !py-1.5" onClick={() => remove(active)}>
                  <span className="flex items-center gap-1 text-xs"><Trash2 size={13} /></span>
                </Button>
              </div>
            </div>
          )}
          {matchesLoading ? (
            <div className="flex justify-center py-16"><Spinner size={22} /></div>
          ) : (
            <div className="space-y-2">
              {matches.map((o) => (
                <BidRow key={o.opportunity_id} bid={o} />
              ))}
              {active && matches.length === 0 && (
                <div className="py-16 text-center text-sm text-ink-faint">
                  No open bids match right now — you'll get a notification when one does.
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {editing && (
        <RuleBuilder
          initial={editing === "new" ? null : editing}
          emailAvailable={settings?.capabilities.email_available ?? false}
          onClose={() => setEditing(null)}
          onSaved={(id) => { setEditing(null); setSelected(id); }}
        />
      )}
    </div>
  );
}

function RuleBuilder({ initial, emailAvailable, onClose, onSaved }: {
  initial: Watchlist | null;
  emailAvailable: boolean;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const mutations = useWatchlistMutation();
  const { data: snapshot } = useOpportunities();
  const { data: tax, isLoading: taxLoading } = useTaxonomy();
  const [name, setName] = useState(initial?.name ?? "");
  const [keywords, setKeywords] = useState<string[]>(initial?.rules.keywords ?? []);
  const [kwInput, setKwInput] = useState("");
  const [counties, setCounties] = useState<string[]>(initial?.rules.counties ?? []);
  const [offers, setOffers] = useState<string[]>(initial?.rules.offers ?? []);
  const [categories, setCategories] = useState<string[]>(initial?.rules.categories ?? []);
  const [maxValue, setMaxValue] = useState(initial?.rules.max_value?.toString() ?? "");
  const [minValue, setMinValue] = useState(initial?.rules.min_value?.toString() ?? "");
  const [noBond, setNoBond] = useState(initial?.rules.no_bond ?? false);
  const [recurring, setRecurring] = useState(initial?.rules.recurring_only ?? false);
  const [includeStatewide, setIncludeStatewide] = useState(initial?.rules.include_statewide ?? false);
  const [emailDigest, setEmailDigest] = useState(initial?.email_digest ?? false);

  const rules: WatchlistRules = useMemo(() => ({
    keywords, counties, offers, categories,
    min_value: minValue ? parseInt(minValue.replace(/\D/g, ""), 10) || null : null,
    max_value: maxValue ? parseInt(maxValue.replace(/\D/g, ""), 10) || null : null,
    no_bond: noBond, recurring_only: recurring, include_statewide: includeStatewide,
  }), [keywords, counties, offers, categories, minValue, maxValue, noBond, recurring,
       includeStatewide]);

  const categoryOptions: MultiSelectOption[] = useMemo(
    () =>
      (tax?.categories ?? []).map((c) => ({
        value: c.slug,
        label: c.label,
        group: c.group,
        count: c.count,
        // Searching "sewer" should surface "Water & sewer infrastructure"
        // even though the slug reads `water_sewer_infra`.
        synonyms: c.slug.replace(/_/g, " "),
      })),
    [tax],
  );

  const countyOptions: MultiSelectOption[] = useMemo(
    () =>
      (tax?.counties ?? []).map((c) => ({
        value: c.slug,
        label: c.label,
        group: c.region_label,
        count: c.count,
      })),
    [tax],
  );

  const countyGroupOrder = useMemo(() => {
    const seen: { key: string; label: string }[] = [];
    for (const c of tax?.counties ?? []) {
      if (!seen.some((g) => g.key === c.region_label)) {
        seen.push({ key: c.region_label, label: c.region_label });
      }
    }
    return seen;
  }, [tax]);

  const offerOptions: MultiSelectOption[] = useMemo(
    () =>
      (tax?.offer_types ?? []).map((o) => ({
        value: o.key,
        label: o.label,
        count: o.count,
      })),
    [tax],
  );

  // Live preview against the loaded snapshot (mirrors the server logic).
  const previewCount = useMemo(() => {
    const pool = (snapshot?.opportunities ?? []).filter(
      (o) => o.status === "open" || o.status === "upcoming");
    return pool.filter((o) => {
      if (counties.length && !counties.includes(o.county)) {
        // Mirror the server: a statewide bid still matches when it *names* a
        // wanted county (adapters stamp them into keywords; FDOT's district
        // counties arrive that way), or when the rule opted into unlocated
        // statewide work. Prose inference stays server-side; keywords cover
        // the measured majority.
        if (o.county !== "statewide") return false;
        const named = (o.keywords ?? []).filter((k) => counties.includes(k));
        if (named.length === 0 && !includeStatewide) return false;
      }
      if (offers.length && !offers.includes(o.offer_type)) return false;
      if (categories.length && !o.categories.some((c) => categories.includes(c))) return false;
      const amount = o.budget_amount;
      if (rules.min_value && amount != null && amount < rules.min_value) return false;
      if (rules.max_value && amount != null && amount > rules.max_value) return false;
      if (noBond && o.requirements.some((r) => r.toLowerCase().includes("bond"))) return false;
      if (recurring && !o.prior_cycles) return false;
      if (keywords.length) {
        const hay = [o.title, o.scope ?? "", o.description ?? "", ...o.categories]
          .join(" ").toLowerCase();
        if (!keywords.some((kw) => hay.includes(kw.toLowerCase()))) return false;
      }
      return true;
    }).length;
  }, [snapshot, rules, counties, offers, categories, keywords, noBond, recurring,
      includeStatewide]);

  const addKeyword = () => {
    const kw = kwInput.trim().toLowerCase();
    if (kw && !keywords.includes(kw)) setKeywords([...keywords, kw]);
    setKwInput("");
  };

  const save = () => {
    const finalName = name.trim() ||
      (keywords.length ? keywords.slice(0, 2).join(" + ") : "New watchlist");
    if (initial) {
      mutations.update.mutate(
        { id: initial.id, name: finalName, rules, email_digest: emailDigest },
        { onSuccess: (wl) => { toast.success("Watchlist updated"); onSaved(wl.id); } },
      );
    } else {
      mutations.create.mutate(
        { name: finalName, rules, email_digest: emailDigest },
        { onSuccess: (wl) => { toast.success("Watchlist created"); onSaved(wl.id); } },
      );
    }
  };

  return (
    <Modal title={initial ? "Edit watchlist" : "New watchlist"} onClose={onClose} wide>
      <label className="mb-4 block">
        <span className="mb-1 block text-xs font-bold text-ink-soft">Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="e.g. Roofing under $500k"
               className="w-full rounded-[10px] border border-line px-3 py-2.5 text-sm outline-none focus:border-accent" />
      </label>

      <div className="mb-4">
        <span className="mb-1 block text-xs font-bold text-ink-soft">Keywords (any match)</span>
        <div className="flex flex-wrap items-center gap-1.5 rounded-[10px] border border-line px-2 py-1.5 focus-within:border-accent">
          {keywords.map((kw) => (
            <span key={kw} className="flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent">
              {kw}
              <button onClick={() => setKeywords(keywords.filter((k) => k !== kw))}
                      className="hover:text-danger">×</button>
            </span>
          ))}
          <input value={kwInput}
                 onChange={(e) => setKwInput(e.target.value)}
                 onKeyDown={(e) => {
                   if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addKeyword(); }
                 }}
                 onBlur={addKeyword}
                 placeholder={keywords.length ? "" : "roof, janitorial, paving…"}
                 className="min-w-24 flex-1 py-1 text-sm outline-none placeholder:text-ink-faint" />
        </div>
      </div>

      <div className="mb-4">
        <div className="mb-1 flex items-baseline justify-between gap-2">
          <span className="text-xs font-bold text-ink-soft">Categories</span>
          <span className="text-[11px] text-ink-faint">
            {taxLoading ? "loading…" : `${categoryOptions.length} to choose from`}
          </span>
        </div>
        <MultiSelect
          options={categoryOptions}
          selected={categories}
          onChange={setCategories}
          placeholder="Any category"
          groupOrder={(tax?.groups ?? []).map((g) => ({ key: g.slug, label: g.label }))}
        />
        <p className="mt-1.5 text-[11px] text-ink-faint">
          The number beside each is what's open today. Picking one with none is
          how you get told about the first.
        </p>
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <div>
          <span className="mb-1 block text-xs font-bold text-ink-soft">Counties</span>
          <MultiSelect
            options={countyOptions}
            selected={counties}
            onChange={setCounties}
            placeholder="Anywhere in Florida"
            groupOrder={countyGroupOrder}
          />
        </div>
        <div>
          <span className="mb-1 block text-xs font-bold text-ink-soft">Work type</span>
          <MultiSelect
            options={offerOptions}
            selected={offers}
            onChange={setOffers}
            placeholder="Any work type"
          />
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3">
        <label>
          <span className="mb-1 block text-xs font-bold text-ink-soft">Min value ($)</span>
          <input value={minValue} onChange={(e) => setMinValue(e.target.value)}
                 inputMode="numeric" placeholder="none"
                 className="w-full rounded-[10px] border border-line px-3 py-2 text-sm outline-none focus:border-accent" />
        </label>
        <label>
          <span className="mb-1 block text-xs font-bold text-ink-soft">Max value ($)</span>
          <input value={maxValue} onChange={(e) => setMaxValue(e.target.value)}
                 inputMode="numeric" placeholder="none"
                 className="w-full rounded-[10px] border border-line px-3 py-2 text-sm outline-none focus:border-accent" />
        </label>
      </div>

      <div className="mb-4 flex flex-wrap gap-1.5">
        <FilterChip active={noBond} onClick={() => setNoBond(!noBond)}>No bond required</FilterChip>
        <FilterChip active={recurring} onClick={() => setRecurring(!recurring)}>Recurring buys only</FilterChip>
        {counties.length > 0 && (
          <FilterChip active={includeStatewide}
                      onClick={() => setIncludeStatewide(!includeStatewide)}>
            + unlocated statewide bids
          </FilterChip>
        )}
      </div>

      <label className={`mb-4 flex items-center gap-2.5 rounded-[10px] border border-line px-3 py-2.5 ${
        emailAvailable ? "" : "opacity-50"}`}>
        <input type="checkbox" checked={emailDigest}
               onChange={(e) => setEmailDigest(e.target.checked)}
               disabled={!emailAvailable}
               className="h-4 w-4 accent-(--color-accent)" />
        <span className="text-sm font-medium">
          Include in email digest
          {!emailAvailable && (
            <span className="block text-xs text-ink-faint">Set RESEND_API_KEY to enable email</span>
          )}
        </span>
      </label>

      <div className="flex items-center justify-between border-t border-line pt-4">
        <span className="text-sm font-bold text-accent">{previewCount} current matches</span>
        <div className="flex gap-2">
          <Button kind="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={save}
                  disabled={mutations.create.isPending || mutations.update.isPending}>
            Save watchlist
          </Button>
        </div>
      </div>
    </Modal>
  );
}
