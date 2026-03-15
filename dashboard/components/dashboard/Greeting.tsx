"use client"

import { motion } from "framer-motion"
import { useSession } from "next-auth/react"
import { useStats, useMeetings, useSignals, useScoringInsights } from "@/lib/hooks/useDashboardData"

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return "Good morning"
  if (hour < 17) return "Good afternoon"
  return "Good evening"
}

export function Greeting() {
  const { data: session } = useSession()
  const { data: statsEnvelope } = useStats()
  const { data: meetingsData } = useMeetings()
  const { data: signalsEnvelope } = useSignals()
  const { data: insightsEnvelope } = useScoringInsights()

  const stats = statsEnvelope?.data
  const signalsData = signalsEnvelope?.data
  const insights = insightsEnvelope?.data
  const firstName = session?.user?.name?.split(" ")[0] || "there"
  const greeting = getGreeting()

  // Build summary parts
  const parts: string[] = []
  if (stats?.dealsThisWeek) parts.push(`${stats.dealsThisWeek} new deal${stats.dealsThisWeek > 1 ? "s" : ""} this week`)
  const meetingCount = meetingsData?.meetings?.length || 0
  if (meetingCount > 0) parts.push(`${meetingCount} meeting${meetingCount > 1 ? "s" : ""} coming up`)
  const signalCount = signalsData?.signals?.length || 0
  if (signalCount > 0) {
    const thesisMatched = signalsData?.signals?.filter(s => s.thesisMatch).length || 0
    const signalText = `${signalCount} founder signal${signalCount > 1 ? "s" : ""}`
    parts.push(thesisMatched > 0 ? `${signalText} (${thesisMatched} thesis-fit)` : signalText)
  }
  if (insights?.total_outcomes && insights.total_outcomes > 0 && insights.sufficient_data) {
    const criticalPrecision = insights.precision_by_tier?.CRITICAL
    if (criticalPrecision && criticalPrecision.total >= 3) {
      parts.push(`CRITICAL precision: ${Math.round(criticalPrecision.precision * 100)}%`)
    }
  }

  const summary = parts.length > 0 ? parts.join(" · ") : "All quiet — no new activity to report."

  // Stale data warnings
  const warnings: string[] = []
  if (statsEnvelope?.meta?.stale) warnings.push("Stats data is stale")
  if (signalsEnvelope?.meta?.stale) warnings.push("Signal data is stale")

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mb-6"
    >
      <h1 className="text-lg font-semibold tracking-tight">
        {greeting}, {firstName}
      </h1>
      <p className="text-xs text-muted-foreground mt-0.5">{summary}</p>
      {warnings.length > 0 && (
        <p className="text-[10px] text-amber-400 mt-1">
          {warnings.join(" · ")}
        </p>
      )}
    </motion.div>
  )
}
