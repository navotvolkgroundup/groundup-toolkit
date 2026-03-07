"use client"

import { motion } from "framer-motion"
import { GitBranch, ChevronDown, ChevronUp } from "lucide-react"
import { usePipeline } from "@/lib/hooks/useDashboardData"
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
  const { data, isLoading } = usePipeline()
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
  // Active stages = not passed/not pursuing
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
        <span className="text-xs text-muted-foreground">{data?.totalDeals || 0} total deals</span>
      </div>

      <div className="flex gap-2 items-end">
        {activeStages.map((stage) => {
          const height = Math.max(20, (stage.count / maxCount) * 80)
          const isExpanded = expanded === stage.id

          return (
            <div key={stage.id} className="flex-1 min-w-0">
              <button
                onClick={() => setExpanded(isExpanded ? null : stage.id)}
                className="w-full group"
              >
                <div className="text-center mb-2">
                  <span className="text-lg font-bold">{stage.count}</span>
                </div>
                <div
                  className={cn(
                    "rounded-lg transition-all duration-300 group-hover:opacity-80",
                    stageColors[stage.id] || "bg-slate-500"
                  )}
                  style={{ height: `${height}px` }}
                />
                <div className="text-center mt-2 flex items-center justify-center gap-1">
                  <span className="text-[10px] text-muted-foreground truncate">{stage.label}</span>
                  {stage.count > 0 && (
                    isExpanded
                      ? <ChevronUp className="h-2.5 w-2.5 text-muted-foreground" />
                      : <ChevronDown className="h-2.5 w-2.5 text-muted-foreground" />
                  )}
                </div>
              </button>

              {isExpanded && stage.deals.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  className="mt-2 space-y-1"
                >
                  {stage.deals.map((deal, i) => (
                    <div key={i} className="text-[10px] text-muted-foreground truncate px-1 py-0.5 rounded bg-muted/50">
                      {deal.name}
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
