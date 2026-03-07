"use client"

import { motion } from "framer-motion"
import { MessageSquare, HelpCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { Service } from "@/lib/types"
import { getIcon } from "@/lib/icons"
import { ServiceToggle } from "./ServiceToggle"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useChatStore } from "@/lib/store/chatStore"
import { useServicesStore } from "@/lib/store/servicesStore"

const categoryColors: Record<string, string> = {
  "Deal Sourcing": "bg-violet-500/15 text-violet-400 border-violet-500/20",
  "Portfolio Monitoring": "bg-blue-500/15 text-blue-400 border-blue-500/20",
  "Scheduling": "bg-amber-500/15 text-amber-400 border-amber-500/20",
  "Content & Comms": "bg-pink-500/15 text-pink-400 border-pink-500/20",
  "Internal Ops": "bg-slate-500/15 text-slate-400 border-slate-500/20",
}

interface HealthInfo {
  serviceId: string
  lastSuccess: string | null
  lastError: string | null
  lastRun: string | null
  status: "healthy" | "warning" | "error" | "unknown"
  recentErrors: number
}

const healthColors: Record<string, string> = {
  healthy: "bg-green-500",
  warning: "bg-amber-500",
  error: "bg-red-500",
  unknown: "bg-slate-500",
}

function formatHealthTime(ts: string | null): string {
  if (!ts) return "never"
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function ServiceCard({
  service,
  index,
  health,
}: {
  service: Service
  index: number
  health?: HealthInfo
}) {
  const Icon = getIcon(service.icon)
  const openChat = useChatStore((s) => s.openChat)
  const openHelp = useServicesStore((s) => s.openHelp)
  const isActive = service.status === "active"

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className={cn(
        "group relative rounded-xl border bg-card/50 backdrop-blur-sm p-5 transition-all duration-200",
        isActive
          ? "border-primary/20 hover:border-primary/40 hover:shadow-[0_0_20px_rgba(99,102,241,0.08)]"
          : "border-border opacity-60 hover:opacity-80"
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors",
              isActive ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold leading-tight">{service.name}</h3>
            <Badge
              variant="outline"
              className={cn("mt-1 text-[10px] px-1.5 py-0 border", categoryColors[service.category])}
            >
              {service.category}
            </Badge>
          </div>
        </div>
        <ServiceToggle
          serviceId={service.id}
          enabled={service.enabledForUser ?? false}
          canToggle={service.canToggle}
        />
      </div>

      {/* Description */}
      <p className="text-xs text-muted-foreground leading-relaxed mb-4">
        {service.description}
      </p>

      {/* Footer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {health ? (
            <>
              <div className="flex items-center gap-1.5">
                <div className={cn("h-1.5 w-1.5 rounded-full", healthColors[health.status])} />
                <span className="text-[10px] text-muted-foreground">
                  Last OK: {formatHealthTime(health.lastSuccess)}
                </span>
              </div>
              {health.recentErrors > 0 && (
                <span className="text-[10px] text-red-400">{health.recentErrors} errors (24h)</span>
              )}
            </>
          ) : (
            <>
              <span className="text-[10px] text-muted-foreground">{service.lastRun}</span>
              <StatusBadge status={service.status} />
            </>
          )}
        </div>
      </div>

      {/* Hover actions */}
      <div className="absolute inset-x-0 bottom-0 flex justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pb-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => openHelp(service)}
          className="h-7 text-xs text-muted-foreground hover:text-primary gap-1.5 bg-card/90 backdrop-blur-sm border border-border"
        >
          <HelpCircle className="h-3 w-3" />
          How to use
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => openChat(service.id, service.name)}
          className="h-7 text-xs text-muted-foreground hover:text-primary gap-1.5 bg-card/90 backdrop-blur-sm border border-border"
        >
          <MessageSquare className="h-3 w-3" />
          Chat
        </Button>
      </div>
    </motion.div>
  )
}
