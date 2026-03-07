import { useQuery } from "@tanstack/react-query"

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Failed to fetch ${url}`)
  return res.json()
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
    queryFn: () => fetchJson<{
      weeks: Array<{ week: string; label: string; count: number }>
      totalDeals: number
    }>("/api/deal-flow"),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function useTeamActivity() {
  return useQuery({
    queryKey: ["team-activity"],
    queryFn: () => fetchJson<{
      heatmap: Array<{ member: string; weeks: number[] }>
      weekLabels: string[]
      totalDeals: number
    }>("/api/team-activity"),
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
      }>
    }>("/api/service-health"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}
