import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "./client";
import type {
  DeepDiveStatus,
  DetectResponse,
  FetchStatus,
  NotificationItem,
  Opportunity,
  OpportunityDetail,
  ResearchStatus,
  SettingsResponse,
  SnapshotResponse,
  SourcesResponse,
  Stats,
  TaxonomyResponse,
  TestEmailResult,
  Watchlist,
  WatchlistRules,
} from "./types";

export const keys = {
  opportunities: ["opportunities"] as const,
  opportunity: (id: string) => ["opportunity", id] as const,
  stats: ["stats"] as const,
  watchlists: ["watchlists"] as const,
  watchlistMatches: (id: string) => ["watchlist-matches", id] as const,
  sources: ["sources"] as const,
  notifications: ["notifications"] as const,
  settings: ["settings"] as const,
  fetchStatus: ["fetch-status"] as const,
  deepDive: (id: string) => ["deep-dive", id] as const,
  taxonomy: ["taxonomy"] as const,
  research: (id: string) => ["research", id] as const,
};

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useOpportunities() {
  return useQuery({
    queryKey: keys.opportunities,
    queryFn: () => api.get<SnapshotResponse>("/api/opportunities"),
    staleTime: 30_000,
  });
}

export function useOpportunity(id: string | null) {
  return useQuery({
    queryKey: keys.opportunity(id ?? "none"),
    queryFn: () => api.get<OpportunityDetail>(`/api/opportunities/${id}`),
    enabled: !!id,
  });
}

export function useStats() {
  return useQuery({
    queryKey: keys.stats,
    queryFn: () => api.get<Stats>("/api/stats"),
    staleTime: 30_000,
  });
}

export function useTaxonomy() {
  return useQuery({
    queryKey: keys.taxonomy,
    queryFn: () => api.get<TaxonomyResponse>("/api/taxonomy"),
    // The vocabulary is declared in code, not derived from data — only the
    // counts move, and never fast enough to be worth refetching often.
    staleTime: 5 * 60_000,
  });
}

export function useWatchlists() {
  return useQuery({
    queryKey: keys.watchlists,
    queryFn: () => api.get<{ watchlists: Watchlist[] }>("/api/watchlists"),
    staleTime: 30_000,
  });
}

export function useWatchlistMatches(id: string | null) {
  return useQuery({
    queryKey: keys.watchlistMatches(id ?? "none"),
    queryFn: () =>
      api.get<{ watchlist: Watchlist; matches: Opportunity[] }>(
        `/api/watchlists/${id}/matches`,
      ),
    enabled: !!id,
  });
}

export function useSources() {
  return useQuery({
    queryKey: keys.sources,
    queryFn: () => api.get<SourcesResponse>("/api/sources"),
    staleTime: 30_000,
  });
}

export function useNotifications() {
  return useQuery({
    queryKey: keys.notifications,
    queryFn: () =>
      api.get<{ unread_count: number; items: NotificationItem[] }>("/api/notifications"),
    refetchInterval: 45_000,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => api.get<SettingsResponse>("/api/settings"),
    staleTime: 60_000,
  });
}

export function useFetchStatus(enabled = true) {
  return useQuery({
    queryKey: keys.fetchStatus,
    queryFn: () => api.get<FetchStatus>("/api/fetch/status"),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.state === "running" ? 2000 : false,
  });
}

// ---------------------------------------------------------------------------
// Bid mutations — every endpoint returns the updated bid, which we write
// straight into the snapshot cache so the UI never waits for a refetch.
// ---------------------------------------------------------------------------

export function useBidMutation() {
  const qc = useQueryClient();

  const writeBack = (updated: Opportunity) => {
    qc.setQueryData<SnapshotResponse>(keys.opportunities, (old) =>
      old
        ? {
            ...old,
            opportunities: old.opportunities.map((o) =>
              o.opportunity_id === updated.opportunity_id ? { ...o, ...updated } : o,
            ),
          }
        : old,
    );
    qc.setQueryData(keys.opportunity(updated.opportunity_id), (old: unknown) =>
      old ? { ...(old as OpportunityDetail), ...updated } : old,
    );
    qc.invalidateQueries({ queryKey: keys.stats });
    qc.invalidateQueries({ queryKey: keys.watchlists });
  };

  return useMutation({
    mutationFn: async (input: { id: string; action: string; body?: unknown }) => {
      const { id, action, body } = input;
      switch (action) {
        case "track":
          return api.post<Opportunity>(`/api/bids/${id}/track`);
        case "untrack":
          return api.del<Opportunity>(`/api/bids/${id}/track`);
        case "stage":
          return api.put<Opportunity>(`/api/bids/${id}/stage`, body);
        case "decision":
          return api.put<Opportunity>(`/api/bids/${id}/decision`, body);
        case "checks":
          return api.put<Opportunity>(`/api/bids/${id}/checks`, body);
        case "notes":
          return api.put<Opportunity>(`/api/bids/${id}/notes`, body);
        case "result":
          return api.put<Opportunity>(`/api/bids/${id}/result`, body);
        case "archive":
          return api.post<Opportunity>(`/api/bids/${id}/archive`);
        case "unarchive":
          return api.del<Opportunity>(`/api/bids/${id}/archive`);
        default:
          throw new Error(`unknown action ${action}`);
      }
    },
    onSuccess: writeBack,
  });
}

export function useSummarize() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) =>
      api.post<{ summary: unknown; model: string; cached: boolean }>(
        `/api/bids/${id}/summarize${force ? "?force=true" : ""}`,
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: keys.opportunity(vars.id) });
      qc.invalidateQueries({ queryKey: keys.opportunities });
    },
  });
}

export function useDeepDive(id: string | null) {
  return useQuery({
    queryKey: keys.deepDive(id ?? "none"),
    queryFn: () => api.get<DeepDiveStatus>(`/api/bids/${id}/deep-dive`),
    enabled: !!id,
    // Poll while the dive is running; a dive takes a minute or two.
    refetchInterval: (query) =>
      query.state.data?.state === "running" ? 3000 : false,
  });
}

export function useStartDeepDive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) =>
      api.post<DeepDiveStatus>(`/api/bids/${id}/deep-dive${force ? "?force=true" : ""}`),
    onSuccess: (_data, vars) => {
      // Flip the query into its polling loop immediately.
      qc.setQueryData<DeepDiveStatus>(keys.deepDive(vars.id), { state: "running" });
      qc.invalidateQueries({ queryKey: keys.deepDive(vars.id) });
    },
  });
}

export function useResearch(id: string | null) {
  return useQuery({
    queryKey: keys.research(id ?? "none"),
    queryFn: () => api.get<ResearchStatus>(`/api/bids/${id}/research`),
    enabled: !!id,
    // Poll while an answer is being researched; web search takes ~15-60s.
    refetchInterval: (query) =>
      query.state.data?.state === "running" ? 3000 : false,
  });
}

export function useAskResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, question }: { id: string; question: string }) =>
      api.post<{ state: string }>(`/api/bids/${id}/research`, { question }),
    onSuccess: (_data, vars) => {
      // Flip the query into its polling loop immediately.
      qc.setQueryData<ResearchStatus>(keys.research(vars.id), (old) => ({
        turns: old?.turns ?? [],
        suggested_questions: old?.suggested_questions ?? [],
        state: "running",
      }));
      qc.invalidateQueries({ queryKey: keys.research(vars.id) });
    },
  });
}

// ---------------------------------------------------------------------------
// Watchlists / sources / settings / misc
// ---------------------------------------------------------------------------

export function useWatchlistMutation() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: keys.watchlists });
    qc.invalidateQueries({ queryKey: ["watchlist-matches"] });
  };
  return {
    create: useMutation({
      mutationFn: (body: { name: string; rules: WatchlistRules; email_digest?: boolean }) =>
        api.post<Watchlist>("/api/watchlists", body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: string } & Partial<{
        name: string; rules: WatchlistRules; email_digest: boolean }>) =>
        api.put<Watchlist>(`/api/watchlists/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.del(`/api/watchlists/${id}`),
      onSuccess: invalidate,
    }),
    markSeen: useMutation({
      mutationFn: (id: string) => api.post(`/api/watchlists/${id}/seen`),
      onSuccess: invalidate,
    }),
  };
}

export function useSourceMutation() {
  const qc = useQueryClient();
  return {
    detect: useMutation({
      mutationFn: (url: string) => api.post<DetectResponse>("/api/sources/detect", { url }),
    }),
    add: useMutation({
      mutationFn: (body: { name: string; county: string; portal_url: string; id?: string }) =>
        api.post<{ source: unknown; test: { ok: boolean; count: number; error: string | null } }>(
          "/api/sources",
          body,
        ),
      onSuccess: () => qc.invalidateQueries({ queryKey: keys.sources }),
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.del(`/api/sources/${id}`),
      onSuccess: () => qc.invalidateQueries({ queryKey: keys.sources }),
    }),
  };
}

export function useSettingsMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api.put<SettingsResponse>("/api/settings", patch),
    onSuccess: (data) => qc.setQueryData(keys.settings, data),
  });
}

export function useTestDigestEmail() {
  return useMutation({
    mutationFn: () => api.post<TestEmailResult>("/api/settings/digest/test"),
  });
}

export function usePurge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target: string) => api.post("/api/settings/data/purge", { target }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useLoadDemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ count: number; seeded_pipeline: boolean }>("/api/demo"),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useMarkNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[] | "all") => api.post("/api/notifications/read", { ids }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.notifications }),
  });
}

export function useStartFetch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/api/fetch"),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.fetchStatus }),
  });
}

/** Called when a fetch completes: refresh everything data-bearing. */
export function useRefreshAfterFetch() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: keys.opportunities });
    qc.invalidateQueries({ queryKey: keys.stats });
    qc.invalidateQueries({ queryKey: keys.watchlists });
    qc.invalidateQueries({ queryKey: keys.sources });
    qc.invalidateQueries({ queryKey: keys.notifications });
  };
}
