import { useQuery } from "@tanstack/react-query"
import type { FreshnessMeta } from "@/lib/withFreshness"

export type { FreshnessMeta }

export interface WithMeta<T> {
  data: T
  meta: FreshnessMeta
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Failed to fetch ${url}`)
  return res.json()
}

/** Fetch and unwrap a freshness envelope. Returns {data, meta}. */
async function fetchWithMeta<T>(url: string): Promise<WithMeta<T>> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Failed to fetch ${url}`)
  const json = await res.json()
  // Handle both envelope format {data, meta} and legacy format
  if (json && typeof json === "object" && "meta" in json && "data" in json) {
    return json as WithMeta<T>
  }
  // Legacy: wrap with synthetic meta
  return {
    data: json as T,
    meta: { fetchedAt: new Date().toISOString(), dataAge: 0, source: "unknown", stale: false, cacheHit: false },
  }
}

function fetchJsonDelayed<T>(url: string, delayMs: number): () => Promise<T> {
  return () => new Promise((resolve) => {
    setTimeout(() => resolve(fetchJson<T>(url)), delayMs)
  })
}

export function usePipeline() {
  return useQuery({
    queryKey: ["pipeline"],
    queryFn: () => fetchJson<{
      stages: Array<{ id: string; label: string; order: number; count: number; deals: Array<{ name: string; amount: string | null; owner: string | null; created: string | null }> }>
      totalDeals: number
    }>("/api/pipeline"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: () => fetchWithMeta<{
      dealsThisWeek: number
      dealsThisMonth: number
      decksAnalyzed: number
      meetingsRecorded: number
      emailsProcessed: number
      founderSignals: number
    }>("/api/stats"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

export function useDealFlow() {
  return useQuery({
    queryKey: ["deal-flow"],
    queryFn: fetchJsonDelayed<{
      weeks: Array<{ week: string; label: string; count: number }>
      totalDeals: number
    }>("/api/deal-flow", 2000),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useTeamActivity() {
  return useQuery({
    queryKey: ["team-activity"],
    queryFn: fetchJsonDelayed<{
      heatmap: Array<{ member: string; weeks: number[] }>
      weekLabels: string[]
      totalDeals: number
    }>("/api/team-activity", 2000),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useSignals() {
  return useQuery({
    queryKey: ["signals"],
    queryFn: () => fetchWithMeta<{
      signals: Array<{
        id: string
        name: string
        company: string
        signal: string
        strength: "high" | "medium" | "low"
        timestamp: string
        source: string
        linkedinUrl: string | null
        githubUrl: string | null
        approached: boolean
        outcome: string | null
        compositeScore: number | null
        classification: string | null
        thesisMatch: string | null
        introPath: string | null
        scoreTrend: number[]
      }>
    }>("/api/signals"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

export function useStageMovements() {
  return useQuery({
    queryKey: ["stage-movements"],
    queryFn: fetchJsonDelayed<{
      movements: Array<{ id: string; name: string; stage: string; owner: string | null; lastModified: string | null; amount: string | null }>
      staleDeals: Array<{ id: string; name: string; stage: string; owner: string | null; lastModified: string | null; daysStale: number }>
    }>("/api/stage-movements", 4000),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

export function useMeetings() {
  return useQuery({
    queryKey: ["meetings"],
    queryFn: () => fetchJson<{
      meetings: Array<{ id: string; title: string; start: string; end: string; attendees: string[]; company: string | null }>
    }>("/api/meetings"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

export function useDealSources() {
  return useQuery({
    queryKey: ["deal-sources"],
    queryFn: fetchJsonDelayed<{
      sources: Array<{ name: string; count: number }>
      total: number
    }>("/api/deal-sources", 6000),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useResponseTime() {
  return useQuery({
    queryKey: ["response-time"],
    queryFn: () => fetchJson<{
      avgMinutes: number
      medianMinutes: number
      totalProcessed: number
      trend: number[]
    }>("/api/response-time"),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useSignalConversion() {
  return useQuery({
    queryKey: ["signal-conversion"],
    queryFn: fetchJsonDelayed<{
      signalsDetected: number
      dealsCreated: number
      conversionRate: number
      totalDeals: number
    }>("/api/signal-conversion", 8000),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useLeads() {
  return useQuery({
    queryKey: ["leads"],
    queryFn: () => fetchJson<{
      leads: Array<{
        id: number
        name: string
        linkedinUrl: string | null
        signalTier: "high" | "medium" | "low" | null
        lastSignal: string | null
        approached: boolean
        approachedAt: string | null
        hubspotContactId: string | null
        addedAt: string
      }>
      stats: {
        total: number
        approached: number
        high: number
        medium: number
        inHubspot: number
      }
    }>("/api/leads"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

export function useDealTimeline(company: string | null) {
  return useQuery({
    queryKey: ["deal-timeline", company],
    queryFn: () => fetchJson<{
      company: string
      companyId: string | null
      events: Array<{
        type: "note" | "deal_created" | "signal" | "email"
        date: string
        summary: string
        source: string
      }>
    }>(`/api/deal-timeline?company=${encodeURIComponent(company || "")}`),
    enabled: !!company,
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useServiceHealth() {
  return useQuery({
    queryKey: ["service-health"],
    queryFn: () => fetchJson<{
      services: Record<string, {
        serviceId: string
        lastSuccess: string | null
        lastError: string | null
        lastRun: string | null
        status: "healthy" | "warning" | "error" | "unknown"
        recentErrors: number
        dailyActivity: number[]
      }>
    }>("/api/service-health"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

export interface RelConnection {
  person: {
    name: string
    email: string | null
    company: string | null
    role: string | null
  }
  rel_type: string
  context: string | null
  source: string | null
  strength: number
  first_seen: string
  last_seen: string
}

export interface RelIntroStep {
  person: { name: string; email: string | null; company: string | null }
  via_rel_type: string | null
  via_context: string | null
}

export function useRelationships(person: string | null) {
  return useQuery({
    queryKey: ["relationships", person],
    queryFn: () => fetchJson<{
      connections: RelConnection[]
    }>(`/api/relationships?person=${encodeURIComponent(person || "")}`),
    enabled: !!person,
    staleTime: 120_000,
  })
}

export function useIntroPath(from: string | null, to: string | null) {
  return useQuery({
    queryKey: ["intro-path", from, to],
    queryFn: () => fetchJson<{
      path: RelIntroStep[]
    }>(`/api/relationships?action=intro-path&from=${encodeURIComponent(from || "")}&to=${encodeURIComponent(to || "")}`),
    enabled: !!from && !!to,
    staleTime: 120_000,
  })
}

export interface ScoringDimension {
  current_weight: number
  suggested_weight: number
  effectiveness: number
  mean_positive: number
  mean_negative: number
}

export interface ScoringInsightsData {
  dimensions: Record<string, ScoringDimension>
  precision_by_tier: Record<string, { total: number; positive: number; precision: number }>
  total_outcomes: number
  sufficient_data: boolean
  current_weights: Record<string, number>
}

export function useScoringInsights() {
  return useQuery({
    queryKey: ["scoring-insights"],
    queryFn: () => fetchWithMeta<ScoringInsightsData>("/api/scoring-insights"),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useRelationshipStats() {
  return useQuery({
    queryKey: ["relationship-stats"],
    queryFn: () => fetchJson<{
      people: number
      relationships: number
      by_type: Record<string, number>
    }>("/api/relationships?action=stats"),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}
