"use client"

import { motion } from "framer-motion"
import { Briefcase, FileSearch, Video, Mail, Radar, TrendingUp } from "lucide-react"
import { useStats } from "@/lib/hooks/useDashboardData"

export function StatsBar() {
  const { data, isLoading } = useStats()

  const stats = [
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
    <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 mb-8">
      {stats.map((stat, i) => (
        <motion.div
          key={stat.label}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: i * 0.04 }}
          className="flex items-center gap-3 rounded-xl border border-border bg-card/50 backdrop-blur-sm p-3"
        >
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${stat.bg}`}>
            <stat.icon className={`h-4 w-4 ${stat.color}`} />
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground leading-tight">{stat.label}</p>
            <p className="text-lg font-semibold tracking-tight">{stat.value}</p>
          </div>
        </motion.div>
      ))}
    </div>
  )
}
