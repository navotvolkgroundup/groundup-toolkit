"use client"

import { motion } from "framer-motion"
import { TrendingUp } from "lucide-react"
import { useDealFlow } from "@/lib/hooks/useDashboardData"
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

export function DealFlowChart() {
  const { data, isLoading } = useDealFlow()

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Deal Flow</h2>
        </div>
        <div className="h-40 flex items-center justify-center text-xs text-muted-foreground">Loading...</div>
      </div>
    )
  }

  const weeks = data?.weeks || []

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.1 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Weekly Deal Flow</h2>
        </div>
        <span className="text-xs text-muted-foreground">Last 12 weeks</span>
      </div>

      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={weeks}>
            <defs>
              <linearGradient id="dealGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#818cf8" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#818cf8" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                background: "#1c1c2e",
                border: "1px solid #2e2e3e",
                borderRadius: "8px",
                fontSize: "12px",
                color: "#e5e7eb",
              }}
              labelFormatter={(label) => `Week of ${label}`}
              formatter={(value) => [`${value} deals`, "Deals"]}
            />
            <Area
              type="monotone"
              dataKey="count"
              stroke="#818cf8"
              fill="url(#dealGradient)"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </motion.div>
  )
}
