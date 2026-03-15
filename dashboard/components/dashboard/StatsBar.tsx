"use client"

import { motion } from "framer-motion"
import { Briefcase, FileSearch, Video, Mail, Radar, TrendingUp } from "lucide-react"
import { useStats } from "@/lib/hooks/useDashboardData"
import { FreshnessBadge } from "@/components/ui/FreshnessBadge"

export function StatsBar() {
  const { data: envelope, isLoading } = useStats()
  const data = envelope?.data
  const meta = envelope?.meta

  const heroStats = [
    {
      label: "Deals This Week",
      value: isLoading ? "-" : (data?.dealsThisWeek ?? 0).toString(),
      icon: Briefcase,
      color: "text-primary",
      bg: "bg-primary/10",
    },
    {
      label: "Deals This Month",
      value: isLoading ? "-" : (data?.dealsThisMonth ?? 0).toString(),
      icon: TrendingUp,
      color: "text-emerald-500",
      bg: "bg-emerald-500/10",
    },
  ]

  const secondaryStats = [
    {
      label: "Decks Analyzed",
      value: isLoading ? "-" : (data?.decksAnalyzed ?? 0).toString(),
      icon: FileSearch,
      color: "text-violet-500",
      bg: "bg-violet-500/10",
    },
    {
      label: "Meetings Recorded",
      value: isLoading ? "-" : (data?.meetingsRecorded ?? 0).toString(),
      icon: Video,
      color: "text-amber-500",
      bg: "bg-amber-500/10",
    },
    {
      label: "Emails Processed",
      value: isLoading ? "-" : (data?.emailsProcessed ?? 0).toString(),
      icon: Mail,
      color: "text-blue-500",
      bg: "bg-blue-500/10",
    },
    {
      label: "Founder Signals",
      value: isLoading ? "-" : (data?.founderSignals ?? 0).toString(),
      icon: Radar,
      color: "text-pink-500",
      bg: "bg-pink-500/10",
    },
  ]

  return (
    <div className="mb-8 space-y-3">
      {meta && <div className="flex justify-end"><FreshnessBadge meta={meta} /></div>}
      {/* Hero metrics */}
      <div className="grid gap-3 grid-cols-2">
        {heroStats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.04 }}
            className="flex items-center gap-4 rounded-xl border border-border bg-card/50 backdrop-blur-sm p-4"
          >
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg ${stat.bg}`}>
              <stat.icon className={`h-5 w-5 ${stat.color}`} />
            </div>
            <div>
              <p className="text-xs text-muted-foreground leading-tight">{stat.label}</p>
              <p className="text-2xl font-bold tracking-tight">{stat.value}</p>
            </div>
          </motion.div>
        ))}
      </div>
      {/* Secondary metrics */}
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
        {secondaryStats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.08 + i * 0.04 }}
            className="flex items-center gap-3 rounded-xl border border-border bg-card/50 backdrop-blur-sm p-3"
          >
            <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${stat.bg}`}>
              <stat.icon className={`h-3.5 w-3.5 ${stat.color}`} />
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground leading-tight">{stat.label}</p>
              <p className="text-sm font-semibold tracking-tight">{stat.value}</p>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
