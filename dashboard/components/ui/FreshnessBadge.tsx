"use client"

import { cn } from "@/lib/utils"
import type { FreshnessMeta } from "@/lib/withFreshness"

function formatAge(seconds: number): string {
  if (seconds < 60) return "just now"
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

interface FreshnessBadgeProps {
  meta: FreshnessMeta | undefined
  className?: string
}

export function FreshnessBadge({ meta, className }: FreshnessBadgeProps) {
  if (!meta) return null

  const isStale = meta.stale
  const ageText = formatAge(meta.dataAge)

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[10px] font-mono",
        isStale ? "text-amber-400" : "text-zinc-500",
        className
      )}
      title={`Source: ${meta.source} | Fetched: ${meta.fetchedAt}${meta.cacheHit ? " (cached)" : ""}`}
    >
      <span className={cn(
        "h-1.5 w-1.5 rounded-full",
        isStale ? "bg-amber-400" : "bg-emerald-500"
      )} />
      {ageText}
    </span>
  )
}
