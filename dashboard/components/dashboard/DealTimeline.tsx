"use client"

import { motion, AnimatePresence } from "framer-motion"
import { Clock, FileText, TrendingUp, Radar, Mail, X, Link2 } from "lucide-react"
import { useDealTimeline, useRelationships } from "@/lib/hooks/useDashboardData"
import { cn } from "@/lib/utils"

const typeConfig = {
  note: { label: "Note", icon: FileText, color: "text-blue-400 bg-blue-500/15 border-blue-500/20" },
  deal_created: { label: "Deal", icon: TrendingUp, color: "text-green-400 bg-green-500/15 border-green-500/20" },
  signal: { label: "Signal", icon: Radar, color: "text-amber-400 bg-amber-500/15 border-amber-500/20" },
  email: { label: "Email", icon: Mail, color: "text-purple-400 bg-purple-500/15 border-purple-500/20" },
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
  } catch {
    return dateStr
  }
}

interface DealTimelineProps {
  company: string
  onClose: () => void
}

export function DealTimeline({ company, onClose }: DealTimelineProps) {
  const { data, isLoading } = useDealTimeline(company)
  const { data: relData } = useRelationships(company)

  const connections = relData?.connections || []

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: 20 }}
        transition={{ duration: 0.2 }}
        className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
      >
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold truncate">Timeline: {company}</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-muted/50 transition-colors"
          >
            <X className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        </div>

        {/* Network connections for this company */}
        {connections.length > 0 && (
          <div className="mb-3 p-2 rounded-lg bg-cyan-500/5 border border-cyan-500/10">
            <div className="flex items-center gap-1.5 mb-1">
              <Link2 className="h-3 w-3 text-cyan-400" />
              <span className="text-[10px] font-medium text-cyan-400">
                Connected to {connections.length} {connections.length === 1 ? "person" : "people"}
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {connections.slice(0, 5).map((c, i) => (
                <span key={i} className="text-[10px] text-muted-foreground">
                  {c.person.name}
                  <span className="text-cyan-400/60 ml-0.5">
                    ({c.rel_type.replace(/_/g, " ")}{c.strength > 1 ? ` x${c.strength}` : ""})
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="h-32 flex items-center justify-center text-xs text-muted-foreground">
            Loading timeline...
          </div>
        ) : !data?.events?.length ? (
          <div className="text-center py-6 text-xs text-muted-foreground">
            No activity found for {company}.
          </div>
        ) : (
          <div className="space-y-1.5 max-h-80 overflow-y-auto">
            {data.events.map((event, i) => {
              const config = typeConfig[event.type] || typeConfig.note
              const Icon = config.icon

              return (
                <div
                  key={`${event.type}-${i}`}
                  className="flex items-start gap-3 p-2 rounded-lg hover:bg-muted/30 transition-colors"
                >
                  <div className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded border",
                    config.color
                  )}>
                    <Icon className="h-2.5 w-2.5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn("text-[9px] font-medium uppercase tracking-wide rounded px-1 py-0.5 border", config.color)}>
                        {config.label}
                      </span>
                      <span className="text-[9px] text-muted-foreground">{event.source}</span>
                    </div>
                    <p className="text-[10px] text-muted-foreground leading-relaxed mt-0.5 line-clamp-2">
                      {event.summary}
                    </p>
                  </div>
                  <span className="text-[9px] text-muted-foreground shrink-0 whitespace-nowrap">
                    {formatDate(event.date)}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  )
}
