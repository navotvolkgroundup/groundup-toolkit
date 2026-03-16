"use client"

import { motion } from "framer-motion"
import { GitBranch, ChevronDown, ChevronUp } from "lucide-react"
import { usePipeline } from "@/lib/hooks/useDashboardData"
import { FreshnessBadge } from "@/components/ui/FreshnessBadge"
import { useState } from "react"
import { cn } from "@/lib/utils"

const stageColors: Record<string, string> = {
  qualifiedtobuy: "bg-blue-500",
  appointmentscheduled: "bg-indigo-500",
  presentationscheduled: "bg-violet-500",
  decisionmakerboughtin: "bg-purple-500",
  contractsent: "bg-fuchsia-500",
  closedwon: "bg-pink-500",
  "1112320899": "bg-emerald-500",
  "1112320900": "bg-green-500",
  "1008223160": "bg-teal-500",
  "1138024523": "bg-amber-500",
  closedlost: "bg-slate-500",
}

export function PipelineFunnel() {
  const { data: envelope, isLoading } = usePipeline()
  const data = envelope?.data
  const meta = envelope?.meta
  const [expanded, setExpanded] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5 mb-8">
        <div className="flex items-center gap-2 mb-4">
          <GitBranch className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Deal Pipeline</h2>
        </div>
        <div className="h-16 flex items-center justify-center text-xs text-muted-foreground">Loading pipeline...</div>
      </div>
    )
  }

  const stages = data?.stages || []
  const activeStages = stages.filter((s) => s.id !== "closedlost")
  const maxCount = Math.max(...activeStages.map((s) => s.count), 1)

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5 mb-8"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Deal Pipeline</h2>
        </div>
        <div className="flex items-center gap-2">
          {meta && <FreshnessBadge meta={meta} />}
          <span className="text-xs text-muted-foreground">{data?.totalDeals || 0} total deals</span>
        </div>
      </div>

      <div className="space-y-1.5">
        {activeStages.map((stage) => {
          const width = Math.max(8, (stage.count / maxCount) * 100)
          const isExpanded = expanded === stage.id

          return (
            <div key={stage.id}>
              <button
                onClick={() => setExpanded(isExpanded ? null : stage.id)}
                className="w-full group flex items-center gap-3"
              >
                <span className="text-xs text-muted-foreground w-28 shrink-0 text-right truncate">
                  {stage.label}
                </span>
                <div className="flex-1 flex items-center gap-2">
                  <div
                    className={cn(
                      "h-6 rounded transition-all duration-300 group-hover:opacity-80",
                      stageColors[stage.id] || "bg-slate-500"
                    )}
                    style={{ width: `${width}%` }}
                  />
                  <span className="text-xs font-semibold w-6 shrink-0">{stage.count}</span>
                  {stage.count > 0 && (
                    isExpanded
                      ? <ChevronUp className="h-3 w-3 text-muted-foreground shrink-0" />
                      : <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
                  )}
                </div>
              </button>

              {isExpanded && stage.deals.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  className="ml-[7.75rem] mt-1 mb-1 space-y-0.5"
                >
                  {stage.deals.map((deal, i) => (
                    <div key={i} className="text-[11px] text-muted-foreground truncate px-2 py-0.5 rounded bg-muted/50">
                      {deal.name}
                      {deal.owner && <span className="text-muted-foreground/50 ml-2">{deal.owner}</span>}
                    </div>
                  ))}
                </motion.div>
              )}
            </div>
          )
        })}
      </div>
    </motion.div>
  )
}
