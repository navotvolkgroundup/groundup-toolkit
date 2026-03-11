"use client"

import { motion } from "framer-motion"
import { Users, ExternalLink, Check, ArrowUpRight, ArrowRight, ArrowDownRight } from "lucide-react"
import { useLeads } from "@/lib/hooks/useDashboardData"
import { cn } from "@/lib/utils"

const tierConfig = {
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

export function LeadsPanel() {
  const { data, isLoading } = useLeads()

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <Users className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Scout Leads</h2>
        </div>
        <div className="h-32 flex items-center justify-center text-xs text-muted-foreground">Loading leads...</div>
      </div>
    )
  }

  const leads = data?.leads || []
  const stats = data?.stats

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.25 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Scout Leads</h2>
        </div>
        {stats && (
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            <span>{stats.total} total</span>
            <span className="text-red-400">{stats.high} high</span>
            <span className="text-green-400">{stats.approached} approached</span>
          </div>
        )}
      </div>

      {leads.length === 0 ? (
        <div className="text-center py-6 text-xs text-muted-foreground">
          No leads yet. Founder Scout runs daily at 7 AM.
        </div>
      ) : (
        <div className="space-y-1.5 max-h-72 overflow-y-auto">
          {leads.map((lead) => {
            const tier = lead.signalTier && tierConfig[lead.signalTier]
            const TierIcon = tier?.icon || ArrowDownRight

            return (
              <div
                key={lead.id}
                className="flex items-start gap-3 p-2.5 rounded-lg hover:bg-muted/30 transition-colors"
              >
                {tier ? (
                  <div className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded border text-[10px] font-bold", tier.color)}>
                    <TierIcon className="h-3 w-3" />
                  </div>
                ) : (
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-border text-[10px] text-muted-foreground">
                    ?
                  </div>
                )}

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    {lead.linkedinUrl ? (
                      <a
                        href={lead.linkedinUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-medium truncate hover:text-primary transition-colors inline-flex items-center gap-1"
                      >
                        {lead.name}
                        <ExternalLink className="h-2.5 w-2.5 opacity-50" />
                      </a>
                    ) : (
                      <span className="text-xs font-medium truncate">{lead.name}</span>
                    )}
                    {lead.approached && (
                      <span className="inline-flex items-center gap-0.5 text-[9px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-1.5 py-0.5">
                        <Check className="h-2.5 w-2.5" />
                        approached
                      </span>
                    )}
                    {lead.hubspotContactId && (
                      <span className="text-[9px] text-orange-400 bg-orange-500/10 border border-orange-500/20 rounded px-1.5 py-0.5">
                        HS
                      </span>
                    )}
                  </div>
                  {lead.lastSignal && (
                    <p className="text-[10px] text-muted-foreground leading-relaxed mt-0.5 line-clamp-1">
                      {lead.lastSignal}
                    </p>
                  )}
                </div>

                <span className="text-[9px] text-muted-foreground shrink-0">
                  {timeAgo(lead.addedAt)}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </motion.div>
  )
}
