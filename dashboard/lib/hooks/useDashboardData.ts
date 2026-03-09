import { useQuery } from "@tanstack/react-query"

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Failed to fetch ${url}`)
  return res.json()
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
    queryFn: () => fetchJson<{
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
    queryFn: () => fetchJson<{
      signals: Array<{
        id: string
        name: string
        company: string
        signal: string
        strength: "high" | "medium" | "low"
        timestamp: string
        source: string
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
