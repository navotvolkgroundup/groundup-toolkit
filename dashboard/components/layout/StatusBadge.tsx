"use client"

import { cn } from "@/lib/utils"
import { ServiceStatus } from "@/lib/types"

const statusConfig: Record<ServiceStatus, { color: string; label: string }> = {
  active: { color: "bg-green-500", label: "Active" },
  inactive: { color: "bg-gray-500", label: "Inactive" },
  degraded: { color: "bg-amber-500", label: "Degraded" },
  disabled: { color: "bg-zinc-400", label: "Disabled" },
}

export function StatusBadge({
  status,
  size = "sm",
}: {
  status: ServiceStatus
  size?: "sm" | "lg"
}) {
  const config = statusConfig[status]
  return (
    <div className="flex items-center gap-1.5">
      <div
        className={cn(
          "rounded-full",
          config.color,
          status === "degraded" && "animate-pulse",
          size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5"
        )}
      />
      <span
        className={cn(
          "text-muted-foreground",
          size === "sm" ? "text-xs" : "text-sm"
        )}
      >
        {config.label}
      </span>
    </div>
  )
}

export function OnlineDot({ online = true }: { online?: boolean }) {
  return (
    <div
      className={cn(
        "h-2.5 w-2.5 rounded-full",
        online ? "bg-green-500" : "bg-gray-500"
      )}
    />
  )
}
