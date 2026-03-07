"use client"

import { motion } from "framer-motion"
import { Zap, Radar, Mail, CalendarCheck, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useState } from "react"

interface ActionConfig {
  id: string
  label: string
  icon: typeof Radar
  action: string
  color: string
}

const actions: ActionConfig[] = [
  { id: "scout", label: "Run Founder Scout", icon: Radar, action: "founder-scout-scan", color: "text-violet-400 hover:bg-violet-500/10" },
  { id: "email", label: "Process Emails", icon: Mail, action: "email-to-deal", color: "text-blue-400 hover:bg-blue-500/10" },
  { id: "meeting", label: "Check Meetings", icon: CalendarCheck, action: "meeting-check", color: "text-amber-400 hover:bg-amber-500/10" },
]

export function QuickActions() {
  const [running, setRunning] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  async function runAction(action: ActionConfig) {
    setRunning(action.id)
    setFeedback(null)

    try {
      const res = await fetch("/api/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action.action }),
      })
      const data = await res.json()
      if (data.ok) {
        setFeedback(`${action.label} triggered`)
      } else {
        setFeedback(`Failed: ${data.error}`)
      }
    } catch {
      setFeedback("Network error")
    } finally {
      setRunning(null)
      setTimeout(() => setFeedback(null), 3000)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5 mb-8"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Quick Actions</h2>
        </div>
        {feedback && (
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-[10px] text-green-400"
          >
            {feedback}
          </motion.span>
        )}
      </div>

      <div className="flex gap-2 flex-wrap">
        {actions.map((action) => (
          <Button
            key={action.id}
            variant="ghost"
            size="sm"
            disabled={running !== null}
            onClick={() => runAction(action)}
            className={`h-8 text-xs gap-1.5 border border-border ${action.color}`}
          >
            {running === action.id ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <action.icon className="h-3 w-3" />
            )}
            {action.label}
          </Button>
        ))}
      </div>
    </motion.div>
  )
}
