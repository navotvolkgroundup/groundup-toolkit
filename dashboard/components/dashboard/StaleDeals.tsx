"use client"

import { motion } from "framer-motion"
import { AlertTriangle, ExternalLink } from "lucide-react"
import { useStageMovements } from "@/lib/hooks/useDashboardData"
import { cn } from "@/lib/utils"

const urgencyColor = (days: number) => {
  if (days >= 90) return "text-red-400 bg-red-500/15 border-red-500/20"
  if (days >= 60) return "text-amber-400 bg-amber-500/15 border-amber-500/20"
  return "text-blue-400 bg-blue-500/15 border-blue-500/20"
}

export function StaleDeals() {
  const { data, isLoading } = useStageMovements()

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Stale Deals</h2>
        </div>
        <div className="h-16 flex items-center justify-center text-xs text-muted-foreground">Loading...</div>
      </div>
    )
  }

  const stale = data?.staleDeals || []

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.05 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Stale Deals</h2>
        </div>
        <span className="text-xs text-muted-foreground">{stale.length} need attention</span>
      </div>

      {stale.length === 0 ? (
        <div className="text-center py-6 text-xs text-muted-foreground">
          No stale deals. Pipeline is moving.
        </div>
      ) : (
        <div className="space-y-1.5 max-h-64 overflow-y-auto">
          {stale.map((deal) => (
            <div
              key={deal.id}
              className="flex items-start gap-3 p-2.5 rounded-lg hover:bg-muted/30 transition-colors"
            >
              <div className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded border text-[9px] font-bold tabular-nums", urgencyColor(deal.daysStale))}>
                {deal.daysStale}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <a
                    href={`https://app.hubspot.com/contacts/49139382/record/0-3/${deal.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-medium truncate hover:text-primary transition-colors inline-flex items-center gap-1"
                  >
                    {deal.name}
                    <ExternalLink className="h-2.5 w-2.5 opacity-50" />
                  </a>
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="text-[10px] text-muted-foreground">{deal.stage}</span>
                  {deal.owner && (
                    <span className="text-[10px] text-muted-foreground">· {deal.owner}</span>
                  )}
                </div>
              </div>
              <span className="text-[9px] text-muted-foreground shrink-0">{deal.daysStale}d</span>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  )
}
