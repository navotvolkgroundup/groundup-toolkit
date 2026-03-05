"use client"

import { create } from "zustand"
import type { Notification } from "@/lib/types"

interface NotificationsState {
  notifications: Notification[]
  isOpen: boolean
  lastReadTimestamp: string | null

  setNotifications: (notifications: Notification[]) => void
  togglePanel: () => void
  closePanel: () => void
  markAllRead: () => void
  unreadCount: () => number
}

export const useNotificationsStore = create<NotificationsState>((set, get) => ({
  notifications: [],
  isOpen: false,
  lastReadTimestamp:
    typeof window !== "undefined"
      ? localStorage.getItem("notifications-last-read")
      : null,

  setNotifications: (notifications) => set({ notifications }),

  togglePanel: () => {
    const { isOpen } = get()
    if (isOpen) {
      set({ isOpen: false })
    } else {
      set({ isOpen: true })
      get().markAllRead()
    }
  },

  closePanel: () => set({ isOpen: false }),

  markAllRead: () => {
    const timestamp = new Date().toISOString()
    set((state) => ({
      lastReadTimestamp: timestamp,
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
    }))
    try {
      localStorage.setItem("notifications-last-read", timestamp)
    } catch {}
  },

  unreadCount: () => {
    return get().notifications.filter((n) => !n.read).length
  },
}))
