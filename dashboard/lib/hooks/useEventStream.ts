"use client"

import { useEffect, useRef, useCallback } from "react"
import { useQueryClient } from "@tanstack/react-query"

interface SSEEvent {
  type: string
  [key: string]: unknown
}

/**
 * Subscribe to the SSE event stream and auto-invalidate React Query caches
 * when new data arrives. Falls back gracefully if SSE is unavailable.
 */
export function useEventStream() {
  const queryClient = useQueryClient()
  const eventSourceRef = useRef<EventSource | null>(null)
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (eventSourceRef.current) return

    const es = new EventSource("/api/events")
    eventSourceRef.current = es

    es.onmessage = (e) => {
      try {
        const data: SSEEvent = JSON.parse(e.data)

        switch (data.type) {
          case "new_signals":
          case "signal_update":
            queryClient.invalidateQueries({ queryKey: ["signals"] })
            queryClient.invalidateQueries({ queryKey: ["leads"] })
            queryClient.invalidateQueries({ queryKey: ["stats"] })
            break

          case "service_activity":
            queryClient.invalidateQueries({ queryKey: ["service-health"] })
            // Specific service refreshes
            if (data.service === "email-to-deal") {
              queryClient.invalidateQueries({ queryKey: ["pipeline"] })
              queryClient.invalidateQueries({ queryKey: ["deal-flow"] })
            }
            if (data.service === "meeting-bot" || data.service === "meeting-auto-join") {
              queryClient.invalidateQueries({ queryKey: ["meetings"] })
            }
            break

          case "init":
            // Initial state — no action needed
            break
        }
      } catch {
        // Ignore parse errors (heartbeats, etc.)
      }
    }

    es.onerror = () => {
      es.close()
      eventSourceRef.current = null
      // Reconnect with backoff
      retryTimeoutRef.current = setTimeout(connect, 5000)
    }
  }, [queryClient])

  useEffect(() => {
    connect()

    return () => {
      if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current)
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [connect])
}
