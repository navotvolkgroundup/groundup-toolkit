"use client"

import { motion } from "framer-motion"
import type { Notification, NotificationLevel } from "@/lib/types"
import { getIcon } from "@/lib/icons"
import { cn } from "@/lib/utils"
import { AlertTriangle, CheckCircle2, XCircle, Info } from "lucide-react"
import type { LucideIcon } from "lucide-react"

const levelConfig: Record<NotificationLevel, { icon: LucideIcon; color: string; bg: string }> = {
  info: { icon: Info, color: "text-blue-400", bg: "bg-blue-500/10" },
  success: { icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/10" },
  warning: { icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/10" },
  error: { icon: XCircle, color: "text-red-400", bg: "bg-red-500/10" },
}

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function NotificationItem({
  notification,
  index,
}: {
  notification: Notification
  index: number
}) {
  const ServiceIcon = getIcon(notification.serviceIcon)
  const level = levelConfig[notification.level]
  const LevelIcon = level.icon

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15, delay: index * 0.02 }}
      className={cn(
        "flex items-start gap-3 px-4 py-3 hover:bg-muted/30 transition-colors cursor-default",
        !notification.read && "bg-primary/[0.03]"
      )}
    >
      <div
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg mt-0.5",
          level.bg
        )}
      >
        <ServiceIcon className={cn("h-3.5 w-3.5", level.color)} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-foreground">
            {notification.serviceName}
          </span>
          {!notification.read && (
            <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
          )}
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed mt-0.5 line-clamp-2">
          {notification.message}
        </p>
        <span className="text-[10px] text-muted-foreground/60 mt-1 block">
          {timeAgo(notification.timestamp)}
        </span>
      </div>

      <LevelIcon className={cn("h-3.5 w-3.5 shrink-0 mt-1", level.color)} />
    </motion.div>
  )
}
