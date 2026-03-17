"use client"

import { useState, useCallback, useMemo, useEffect, useRef } from "react"
import { motion } from "framer-motion"
import { Radar, ExternalLink, Check, MoreHorizontal, Plus, Link2, Sparkles } from "lucide-react"
import { useSignals } from "@/lib/hooks/useDashboardData"
import { FreshnessBadge } from "@/components/ui/FreshnessBadge"
import { useQueryClient } from "@tanstack/react-query"
import { cn } from "@/lib/utils"
import { DealTimeline } from "./DealTimeline"

const classificationColors: Record<string, string> = {
  CRITICAL: "text-red-400 bg-red-500/20 border-red-500/30",
  HIGH: "text-orange-400 bg-orange-500/20 border-orange-500/30",
  MEDIUM: "text-amber-400 bg-amber-500/20 border-amber-500/30",
  LOW: "text-blue-400 bg-blue-500/20 border-blue-500/30",
  WATCHING: "text-zinc-400 bg-zinc-500/20 border-zinc-500/30",
}

const outcomeConfig: Record<string, { label: string; color: string }> = {
  met: { label: "Met", color: "text-blue-400 bg-blue-500/10 border-blue-500/20" },
  invested: { label: "Invested", color: "text-green-400 bg-green-500/10 border-green-500/20" },
  passed: { label: "Passed", color: "text-zinc-400 bg-zinc-500/10 border-zinc-500/20" },
  noise: { label: "Noise", color: "text-red-400 bg-red-500/10 border-red-500/20" },
}

type FilterMode = "all" | "critical" | "high" | "thesis" | "unactioned"

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime()
  const hours = Math.floor(diff / (1000 * 60 * 60))
  if (hours < 1) return "just now"
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function MiniSparkline({ data }: { data: number[] }) {
  if (data.length < 2) return null
  const max = Math.max(...data, 1)
  const min = Math.min(...data, 0)
  const range = max - min || 1
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * 28
    const y = 12 - ((v - min) / range) * 10
    return `${x},${y}`
  }).join(" ")
  const trending = data[data.length - 1] >= data[0]
  return (
    <svg width="28" height="14" className="overflow-visible shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke={trending ? "#22c55e" : "#ef4444"}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function SignalFeed() {
  const { data: envelope, isLoading } = useSignals()
  const data = envelope?.data
  const meta = envelope?.meta
  const queryClient = useQueryClient()
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [timelineCompany, setTimelineCompany] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterMode>("all")
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu on outside click (use mousedown to avoid interfering with button onClick)
  useEffect(() => {
    if (!openMenuId) return
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && menuRef.current.contains(e.target as Node)) return
      setOpenMenuId(null)
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [openMenuId])

  const markOutcome = useCallback(async (signalId: string, outcome: string) => {
    setOpenMenuId(null)
    try {
      await fetch("/api/signals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signalId, outcome }),
      })
      queryClient.invalidateQueries({ queryKey: ["signals"] })
    } catch {
      // Silently fail — will refresh on next poll
    }
  }, [queryClient])

  const markApproached = useCallback(async (signalId: string) => {
    setOpenMenuId(null)
    try {
      await fetch("/api/signals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signalId, action: "approach" }),
      })
      queryClient.invalidateQueries({ queryKey: ["signals"] })
    } catch {
      // Silently fail
    }
  }, [queryClient])

  const createDeal = useCallback(async (personId: string) => {
    setOpenMenuId(null)
    try {
      const res = await fetch("/api/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "signal-to-deal", personId }),
      })
      const data = await res.json()
      if (data.ok) {
        queryClient.invalidateQueries({ queryKey: ["signals"] })
        queryClient.invalidateQueries({ queryKey: ["pipeline"] })
        queryClient.invalidateQueries({ queryKey: ["stats"] })
      }
    } catch {
      // Silently fail
    }
  }, [queryClient])

  const allSignals = data?.signals || []

  const signals = useMemo(() => {
    switch (filter) {
      case "critical": return allSignals.filter(s => s.classification === "CRITICAL")
      case "high": return allSignals.filter(s => s.classification === "CRITICAL" || s.classification === "HIGH")
      case "thesis": return allSignals.filter(s => s.thesisMatch)
      case "unactioned": return allSignals.filter(s => !s.outcome && !s.approached)
      default: return allSignals
    }
  }, [allSignals, filter])

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

  const filters: { key: FilterMode; label: string }[] = [
    { key: "all", label: "All" },
    { key: "critical", label: "Critical" },
    { key: "high", label: "High+" },
    { key: "thesis", label: "Thesis" },
    { key: "unactioned", label: "New" },
  ]

  return (
    <div className="space-y-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.2 }}
        className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
      >
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold">Founder Signals</h2>
          </div>
          <div className="flex items-center gap-2">
            {meta && <FreshnessBadge meta={meta} />}
            <span className="text-xs text-muted-foreground">{signals.length}{filter !== "all" ? `/${allSignals.length}` : ""} recent</span>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-1 mb-3">
          {filters.map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "text-[10px] px-2 py-0.5 rounded-full border transition-colors",
                filter === f.key
                  ? "bg-primary/15 text-primary border-primary/30"
                  : "text-muted-foreground border-transparent hover:border-border"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        {signals.length === 0 ? (
          <div className="text-center py-6 text-xs text-muted-foreground">
            {filter !== "all" ? "No signals match this filter." : "No recent signals detected. Founder Scout runs daily at 7 AM."}
          </div>
        ) : (
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {signals.map((signal) => {
              const scoreColor = signal.classification ? classificationColors[signal.classification] || "" : ""
              const outcome = signal.outcome ? outcomeConfig[signal.outcome] : null

              return (
                <div
                  key={signal.id}
                  className="group flex items-start gap-3 p-2.5 rounded-lg hover:bg-muted/30 transition-colors"
                >
                  {/* Score badge (replaces strength icon) */}
                  {signal.compositeScore != null ? (
                    <div className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded border text-[10px] font-bold tabular-nums", scoreColor)} title={`${signal.classification} (${signal.compositeScore})`}>
                      {signal.compositeScore}
                    </div>
                  ) : (
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-border text-[10px] text-muted-foreground">
                      ?
                    </div>
                  )}

                  <div className="flex-1 min-w-0">
                    {/* Name row */}
                    <div className="flex items-center gap-1.5 flex-wrap">
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
                      {signal.approached && (
                        <span className="inline-flex items-center gap-0.5 text-[9px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-1.5 py-0.5">
                          <Check className="h-2.5 w-2.5" />
                          pinged
                        </span>
                      )}
                      {outcome && (
                        <span className={cn("text-[9px] rounded px-1.5 py-0.5 border", outcome.color)}>
                          {outcome.label}
                        </span>
                      )}
                      {signal.thesisMatch && (
                        <span className="text-[9px] text-violet-400 bg-violet-500/10 border border-violet-500/20 rounded px-1.5 py-0.5 inline-flex items-center gap-0.5">
                          <Sparkles className="h-2 w-2" />
                          {signal.thesisMatch}
                        </span>
                      )}
                      {signal.githubUrl && (
                        <a
                          href={signal.githubUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-0.5 text-[9px] text-muted-foreground hover:text-foreground bg-muted/50 border border-border rounded px-1.5 py-0.5 transition-colors"
                          title="GitHub profile"
                        >
                          <svg className="h-2.5 w-2.5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
                          GH
                        </a>
                      )}
                      {signal.company && (
                        <button
                          onClick={() => setTimelineCompany(signal.company)}
                          className="text-[10px] text-muted-foreground truncate hover:text-primary transition-colors cursor-pointer"
                          title="View timeline"
                        >
                          @ {signal.company}
                        </button>
                      )}
                    </div>

                    {/* Signal description */}
                    <p className="text-[10px] text-muted-foreground leading-relaxed mt-0.5 line-clamp-2">
                      {signal.signal}
                    </p>

                    {/* Intro path (if available) */}
                    {signal.introPath && (
                      <p className="text-[10px] text-cyan-400/70 mt-0.5 inline-flex items-center gap-1 truncate">
                        <Link2 className="h-2.5 w-2.5 shrink-0" />
                        {signal.introPath}
                      </p>
                    )}
                  </div>

                  {/* Right column: sparkline + time + menu */}
                  <div className="flex items-center gap-1.5 shrink-0">
                    {signal.scoreTrend && signal.scoreTrend.length >= 2 && (
                      <MiniSparkline data={signal.scoreTrend} />
                    )}
                    <span className="text-[9px] text-muted-foreground">{timeAgo(signal.timestamp)}</span>
                    <div className="relative" ref={openMenuId === signal.id ? menuRef : undefined}>
                      <button
                        onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === signal.id ? null : signal.id) }}
                        className="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-muted/50 transition-all"
                        title="Actions"
                      >
                        <MoreHorizontal className="h-3 w-3 text-muted-foreground" />
                      </button>
                      {openMenuId === signal.id && (
                        <div
                          className="absolute right-0 top-5 z-10 rounded-lg border border-border bg-card shadow-lg p-1 min-w-[120px]"
                          onMouseDown={(e) => e.stopPropagation()}
                        >
                          <button
                            onClick={() => createDeal(signal.id)}
                            className="w-full text-left text-[10px] px-2 py-1 rounded hover:bg-muted/50 transition-colors text-emerald-400 flex items-center gap-1"
                          >
                            <Plus className="h-2.5 w-2.5" />
                            Create Deal
                          </button>
                          {!signal.approached && (
                            <button
                              onClick={() => markApproached(signal.id)}
                              className="w-full text-left text-[10px] px-2 py-1 rounded hover:bg-muted/50 transition-colors text-green-400 flex items-center gap-1"
                            >
                              <Check className="h-2.5 w-2.5" />
                              Pinged
                            </button>
                          )}
                          <div className="h-px bg-border my-0.5" />
                          {(["met", "invested", "passed", "noise"] as const).map((o) => (
                            <button
                              key={o}
                              onClick={() => markOutcome(signal.id, o)}
                              className={cn(
                                "w-full text-left text-[10px] px-2 py-1 rounded hover:bg-muted/50 transition-colors",
                                outcomeConfig[o].color
                              )}
                            >
                              {outcomeConfig[o].label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </motion.div>

      {timelineCompany && (
        <DealTimeline
          company={timelineCompany}
          onClose={() => setTimelineCompany(null)}
        />
      )}
    </div>
  )
}
