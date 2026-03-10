"use client"

import { motion } from "framer-motion"
import { Radar, ArrowUpRight, ArrowRight, ArrowDownRight, ExternalLink } from "lucide-react"
import { useSignals } from "@/lib/hooks/useDashboardData"
import { cn } from "@/lib/utils"

const strengthConfig = {
  high: { label: "High", color: "text-red-400 bg-red-500/15 border-red-500/20", icon: ArrowUpRight },
  medium: { label: "Med", color: "text-amber-400 bg-amber-500/15 border-amber-500/20", icon: ArrowRight },
  low: { label: "Low", color: "text-blue-400 bg-blue-500/15 border-blue-500/20", icon: ArrowDownRight },
}

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime()
  const hours = Math.floor(diff / (1000 * 60 * 60))
  if (hours < 1) return "just now"
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function SignalFeed() {
  const { data, isLoading } = useSignals()

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <Radar className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Founder Signals</h2>
        </div>
        <div className="h-32 flex items-center justify-center text-xs text-muted-foreground">Loading signals...</div>
      </div>
    )
  }

  const signals = data?.signals || []

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.2 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Radar className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Founder Signals</h2>
        </div>
        <span className="text-xs text-muted-foreground">{signals.length} recent</span>
      </div>

      {signals.length === 0 ? (
        <div className="text-center py-6 text-xs text-muted-foreground">
          No recent signals detected. Founder Scout runs daily at 7 AM.
        </div>
      ) : (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {signals.map((signal) => {
            const config = strengthConfig[signal.strength]
            const Icon = config.icon

            return (
              <div
                key={signal.id}
                className="flex items-start gap-3 p-2.5 rounded-lg hover:bg-muted/30 transition-colors"
              >
                <div className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded border text-[10px] font-bold", config.color)}>
                  <Icon className="h-3 w-3" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    {signal.linkedinUrl ? (
                      <a
                        href={signal.linkedinUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-medium truncate hover:text-primary transition-colors inline-flex items-center gap-1"
                      >
                        {signal.name}
                        <ExternalLink className="h-2.5 w-2.5 opacity-50" />
                      </a>
                    ) : (
                      <span className="text-xs font-medium truncate">{signal.name}</span>
                    )}
                    {signal.company && (
                      <span className="text-[10px] text-muted-foreground truncate">@ {signal.company}</span>
                    )}
                  </div>
                  <p className="text-[10px] text-muted-foreground leading-relaxed mt-0.5 line-clamp-2">
                    {signal.signal}
                  </p>
                </div>
                <span className="text-[9px] text-muted-foreground shrink-0">{timeAgo(signal.timestamp)}</span>
              </div>
            )
          })}
        </div>
      )}
    </motion.div>
  )
}
