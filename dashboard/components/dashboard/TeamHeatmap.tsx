"use client"

import { motion } from "framer-motion"
import { Users } from "lucide-react"
import { useTeamActivity } from "@/lib/hooks/useDashboardData"
import { cn } from "@/lib/utils"

function getHeatColor(count: number, max: number): string {
  if (count === 0) return "bg-muted/30"
  const intensity = count / Math.max(max, 1)
  if (intensity > 0.7) return "bg-primary/80"
  if (intensity > 0.4) return "bg-primary/50"
  if (intensity > 0) return "bg-primary/25"
  return "bg-muted/30"
}

export function TeamHeatmap() {
  const { data, isLoading } = useTeamActivity()

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <Users className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Team Activity</h2>
        </div>
        <div className="h-32 flex items-center justify-center text-xs text-muted-foreground">Loading...</div>
      </div>
    )
  }

  const heatmap = data?.heatmap || []
  const weekLabels = data?.weekLabels || []
  const allCounts = heatmap.flatMap((h) => h.weeks)
  const maxCount = Math.max(...allCounts, 1)

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.15 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Team Sourcing Activity</h2>
        </div>
        <span className="text-xs text-muted-foreground">Last 8 weeks</span>
      </div>

      <div className="space-y-2">
        {/* Header row */}
        <div className="flex items-center gap-2">
          <div className="w-16 shrink-0" />
          {weekLabels.map((label, i) => (
            <div key={i} className="flex-1 text-center text-[9px] text-muted-foreground">
              {label}
            </div>
          ))}
          <div className="w-8 shrink-0 text-center text-[9px] text-muted-foreground">Total</div>
        </div>

        {/* Team rows */}
        {heatmap.map((row) => {
          const total = row.weeks.reduce((a, b) => a + b, 0)
          return (
            <div key={row.member} className="flex items-center gap-2">
              <div className="w-16 shrink-0 text-xs font-medium truncate">{row.member}</div>
              {row.weeks.map((count, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex-1 h-7 rounded flex items-center justify-center text-[10px] font-medium transition-colors",
                    getHeatColor(count, maxCount),
                    count > 0 ? "text-foreground" : "text-muted-foreground/30"
                  )}
                >
                  {count > 0 ? count : ""}
                </div>
              ))}
              <div className="w-8 shrink-0 text-center text-xs font-semibold">{total}</div>
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 mt-3 justify-end">
        <span className="text-[9px] text-muted-foreground">Less</span>
        <div className="flex gap-1">
          <div className="w-3 h-3 rounded-sm bg-muted/30" />
          <div className="w-3 h-3 rounded-sm bg-primary/25" />
          <div className="w-3 h-3 rounded-sm bg-primary/50" />
          <div className="w-3 h-3 rounded-sm bg-primary/80" />
        </div>
        <span className="text-[9px] text-muted-foreground">More</span>
      </div>
    </motion.div>
  )
}
