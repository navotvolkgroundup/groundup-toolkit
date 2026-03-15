"use client"

import { motion } from "framer-motion"
import { Newspaper, Sparkles } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { FreshnessBadge } from "@/components/ui/FreshnessBadge"
import type { FreshnessMeta } from "@/lib/withFreshness"

const areaColors: Record<string, string> = {
  "AI Infrastructure": "text-violet-400 bg-violet-500/10 border-violet-500/20",
  "Developer Tools": "text-blue-400 bg-blue-500/10 border-blue-500/20",
  "Cybersecurity": "text-red-400 bg-red-500/10 border-red-500/20",
  "Data Infrastructure": "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  "Defense Tech": "text-amber-400 bg-amber-500/10 border-amber-500/20",
}

interface ThesisData {
  areas: string[]
  totalSeen: number
  lastUpdated: string | null
}

function useThesisNews() {
  return useQuery({
    queryKey: ["thesis-news"],
    queryFn: async () => {
      const res = await fetch("/api/thesis-news")
      if (!res.ok) throw new Error("Failed to fetch")
      const json = await res.json()
      if (json && "data" in json && "meta" in json) return json as { data: ThesisData; meta: FreshnessMeta }
      return { data: json as ThesisData, meta: { fetchedAt: new Date().toISOString(), dataAge: 0, source: "unknown", stale: false, cacheHit: false } }
    },
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function ThesisNewsFeed() {
  const { data: envelope, isLoading } = useThesisNews()
  const data = envelope?.data
  const meta = envelope?.meta

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <Newspaper className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Thesis Radar</h2>
        </div>
        <div className="h-20 flex items-center justify-center text-xs text-muted-foreground">Loading...</div>
      </div>
    )
  }

  const areas = data?.areas || []
  const totalSeen = data?.totalSeen || 0
  const lastUpdated = data?.lastUpdated

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.1 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Newspaper className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Thesis Radar</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">{totalSeen} articles tracked</span>
          {meta && <FreshnessBadge meta={meta} />}
        </div>
      </div>

      {/* Thesis area badges */}
      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {areas.map((area) => {
            const color = areaColors[area] || "text-muted-foreground bg-muted/50 border-border"
            return (
              <span
                key={area}
                className={`text-[10px] rounded px-2 py-1 border inline-flex items-center gap-1 ${color}`}
              >
                <Sparkles className="h-2.5 w-2.5" />
                {area}
              </span>
            )
          })}
        </div>

        {lastUpdated && (
          <p className="text-[10px] text-muted-foreground">
            Last scan: {new Date(lastUpdated).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
          </p>
        )}

        {!lastUpdated && (
          <p className="text-[10px] text-muted-foreground italic">
            Thesis scanner has not run yet. Schedule it daily at 8am.
          </p>
        )}
      </div>
    </motion.div>
  )
}
