"use client"

import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { useNotificationsStore } from "@/lib/store/notificationsStore"
import type { Notification } from "@/lib/types"

interface NotificationsResponse {
  notifications: Notification[]
  timestamp: string
}

export function useNotifications() {
  const setNotifications = useNotificationsStore((s) => s.setNotifications)
  const lastReadTimestamp = useNotificationsStore((s) => s.lastReadTimestamp)

  const { data, isLoading } = useQuery<NotificationsResponse>({
    queryKey: ["notifications"],
    queryFn: () =>
      fetch("/api/notifications").then((r) => {
        if (!r.ok) throw new Error("Failed to fetch notifications")
        return r.json()
      }),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
  })

  useEffect(() => {
    if (data?.notifications) {
      const notifications = data.notifications.map((n) => ({
        ...n,
        read: lastReadTimestamp ? n.timestamp <= lastReadTimestamp : false,
      }))
      setNotifications(notifications)
    }
  }, [data, lastReadTimestamp, setNotifications])

  return { isLoading }
}
