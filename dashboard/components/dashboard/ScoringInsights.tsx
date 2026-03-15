"use client"

import { motion } from "framer-motion"
import { Brain, TrendingUp } from "lucide-react"
import { useScoringInsights } from "@/lib/hooks/useDashboardData"
import { FreshnessBadge } from "@/components/ui/FreshnessBadge"
import { cn } from "@/lib/utils"

const DIMENSION_ORDER = ["timing", "pedigree", "activity", "network", "intent"]
const TIER_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "WATCHING"]

const tierColors: Record<string, string> = {
  CRITICAL: "text-red-400",
  HIGH: "text-orange-400",
  MEDIUM: "text-amber-400",
  LOW: "text-blue-400",
  WATCHING: "text-zinc-400",
}

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="h-1.5 w-full rounded-full bg-muted/50">
      <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function ScoringInsights() {
  const { data: envelope, isLoading } = useScoringInsights()
  const data = envelope?.data
  const meta = envelope?.meta

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <Brain className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Scoring Insights</h2>
        </div>
        <div className="h-32 flex items-center justify-center text-xs text-muted-foreground">Loading insights...</div>
      </div>
    )
  }

  if (!data || Object.keys(data.dimensions).length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <Brain className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Scoring Insights</h2>
        </div>
        <div className="text-center py-6 text-xs text-muted-foreground">
          No scoring data available yet. Mark signal outcomes to build insights.
        </div>
      </div>
    )
  }

  const maxEffectiveness = Math.max(
    ...DIMENSION_ORDER.map((d) => data.dimensions[d]?.effectiveness ?? 0),
    1
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.3 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Scoring Insights</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">
            {data.total_outcomes} outcome{data.total_outcomes !== 1 ? "s" : ""}
          </span>
          {meta && <FreshnessBadge meta={meta} />}
        </div>
      </div>

      {/* Dimension effectiveness */}
      <div className="space-y-2 mb-4">
        <h3 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
          <TrendingUp className="h-3 w-3" />
          Dimension Effectiveness
        </h3>
        {DIMENSION_ORDER.map((dim) => {
          const d = data.dimensions[dim]
          if (!d) return null
          const changed = data.sufficient_data && Math.abs(d.current_weight - d.suggested_weight) > 0.02
          return (
            <div key={dim} className="space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium capitalize">{dim}</span>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span>w: {d.current_weight.toFixed(2)}</span>
                  {changed && (
                    <span className="text-amber-400">→ {d.suggested_weight.toFixed(2)}</span>
                  )}
                  <span className="tabular-nums">{d.effectiveness.toFixed(2)}x</span>
                </div>
              </div>
              <Bar
                value={d.effectiveness}
                max={maxEffectiveness}
                color={d.effectiveness >= 1.5 ? "bg-green-500/60" : d.effectiveness >= 1.0 ? "bg-amber-500/60" : "bg-red-500/60"}
              />
            </div>
          )
        })}
      </div>

      {/* Precision by tier */}
      {Object.keys(data.precision_by_tier).length > 0 && (
        <div className="space-y-1.5">
          <h3 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
            Precision by Tier
          </h3>
          <div className="grid grid-cols-5 gap-1.5">
            {TIER_ORDER.map((tier) => {
              const p = data.precision_by_tier[tier]
              if (!p) return <div key={tier} />
              return (
                <div key={tier} className="text-center">
                  <div className={cn("text-[11px] font-semibold", tierColors[tier])}>
                    {(p.precision * 100).toFixed(0)}%
                  </div>
                  <div className="text-[9px] text-muted-foreground">{tier}</div>
                  <div className="text-[9px] text-muted-foreground">n={p.total}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {!data.sufficient_data && data.total_outcomes > 0 && (
        <p className="text-[10px] text-muted-foreground mt-3 italic">
          {20 - data.total_outcomes} more outcomes needed for weight suggestions.
        </p>
      )}
    </motion.div>
  )
}
