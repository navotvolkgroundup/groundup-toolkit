"use client"

import { motion } from "framer-motion"
import { Building2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { FreshnessBadge } from "@/components/ui/FreshnessBadge"
import type { FreshnessMeta } from "@/lib/withFreshness"
import { cn } from "@/lib/utils"
import Link from "next/link"

interface PortfolioStats {
  total: number
  green: number
  yellow: number
  red: number
  noData: number
}

function usePortfolioSummary() {
  return useQuery({
    queryKey: ["portfolio-summary"],
    queryFn: async () => {
      const res = await fetch("/api/portfolio")
      if (!res.ok) throw new Error("Failed to fetch")
      const json = await res.json()
      const data = json.data || json
      const companies: Array<{ health: string | null; lastUpdate: string | null }> = data.companies || []
      const now = Date.now()
      let green = 0, yellow = 0, red = 0, noData = 0
      for (const c of companies) {
        if (!c.lastUpdate) { noData++; continue }
        const age = (now - new Date(c.lastUpdate).getTime()) / (1000 * 60 * 60 * 24)
        if (age <= 30) green++
        else if (age <= 60) yellow++
        else red++
      }
      return {
        data: { total: companies.length, green, yellow, red, noData } as PortfolioStats,
        meta: json.meta as FreshnessMeta | undefined,
      }
    },
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

export function PortfolioSummary() {
  const { data: envelope, isLoading } = usePortfolioSummary()
  const stats = envelope?.data
  const meta = envelope?.meta

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Portfolio Health</h2>
        </div>
        <div className="h-16 flex items-center justify-center text-xs text-muted-foreground">Loading...</div>
      </div>
    )
  }

  if (!stats) return null

  const segments = [
    { label: "Fresh", count: stats.green, color: "bg-green-500", textColor: "text-green-400" },
    { label: "Aging", count: stats.yellow, color: "bg-amber-500", textColor: "text-amber-400" },
    { label: "Stale", count: stats.red, color: "bg-red-500", textColor: "text-red-400" },
    { label: "No data", count: stats.noData, color: "bg-zinc-500", textColor: "text-zinc-400" },
  ].filter(s => s.count > 0)

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.1 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Portfolio Health</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{stats.total} companies</span>
          {meta && <FreshnessBadge meta={meta} />}
        </div>
      </div>

      {/* Health bar */}
      {stats.total > 0 && (
        <div className="flex h-4 rounded-full overflow-hidden mb-3">
          {segments.map(s => (
            <div
              key={s.label}
              className={cn("transition-all", s.color)}
              style={{ width: `${(s.count / stats.total) * 100}%` }}
            />
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {segments.map(s => (
            <div key={s.label} className="flex items-center gap-1.5">
              <div className={cn("h-2 w-2 rounded-sm", s.color)} />
              <span className={cn("text-[10px]", s.textColor)}>{s.count} {s.label}</span>
            </div>
          ))}
        </div>
        <Link href="/portfolio" className="text-[10px] text-primary hover:underline">
          View all
        </Link>
      </div>
    </motion.div>
  )
}
