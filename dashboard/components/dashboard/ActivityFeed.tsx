"use client"

import { motion } from "framer-motion"
import { Clock } from "lucide-react"
import { useNotifications } from "@/lib/hooks/useNotifications"
import { useNotificationsStore } from "@/lib/store/notificationsStore"
import { getIcon } from "@/lib/icons"
import { cn } from "@/lib/utils"

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

const levelColors: Record<string, string> = {
  error: "text-red-400",
  warning: "text-amber-400",
  success: "text-green-400",
  info: "text-blue-400",
}

export function ActivityFeed() {
  const { isLoading } = useNotifications()
  const notifications = useNotificationsStore((s) => s.notifications)

  return (
    <div className="mt-8">
      <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
        <Clock className="h-4 w-4 text-muted-foreground" />
        Recent Activity
        {!isLoading && (
          <span className="text-[10px] text-muted-foreground font-normal ml-1">Live from server logs</span>
        )}
      </h2>
      <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm divide-y divide-border">
        {isLoading ? (
          <div className="px-4 py-8 text-center text-xs text-muted-foreground">Loading activity...</div>
        ) : notifications.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-muted-foreground">No recent activity</div>
        ) : (
          notifications.slice(0, 15).map((notification, i) => {
            const Icon = getIcon(notification.serviceIcon)
            return (
              <motion.div
                key={notification.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2, delay: i * 0.02 }}
                className="flex items-start gap-3 px-4 py-3 hover:bg-muted/30 transition-colors"
              >
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted mt-0.5">
                  <Icon className={cn("h-3.5 w-3.5", levelColors[notification.level] || "text-muted-foreground")} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs leading-relaxed">
                    <span className="font-medium text-foreground">{notification.serviceName}</span>
                    <span className="text-muted-foreground"> — {notification.message}</span>
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={cn("text-[10px]", levelColors[notification.level] || "text-muted-foreground")}>
                      {notification.level}
                    </span>
                    <span className="text-[10px] text-muted-foreground/50">·</span>
                    <span className="text-[10px] text-muted-foreground">{timeAgo(notification.timestamp)}</span>
                  </div>
                </div>
              </motion.div>
            )
          })
        )}
      </div>
    </div>
  )
}
