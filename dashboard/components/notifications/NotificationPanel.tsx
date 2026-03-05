"use client"

import { useNotificationsStore } from "@/lib/store/notificationsStore"
import { useNotifications } from "@/lib/hooks/useNotifications"
import { Bell } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
import { NotificationItem } from "./NotificationItem"
import { motion, AnimatePresence } from "framer-motion"

export function NotificationPanel() {
  useNotifications()

  const notifications = useNotificationsStore((s) => s.notifications)
  const isOpen = useNotificationsStore((s) => s.isOpen)
  const togglePanel = useNotificationsStore((s) => s.togglePanel)
  const closePanel = useNotificationsStore((s) => s.closePanel)
  const unreadCount = useNotificationsStore((s) => s.unreadCount)
  const count = unreadCount()

  return (
    <DropdownMenu
      open={isOpen}
      onOpenChange={(open) => (open ? togglePanel() : closePanel())}
    >
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative h-9 w-9 text-muted-foreground hover:text-foreground"
        >
          <Bell className="h-4 w-4" />
          <AnimatePresence>
            {count > 0 && (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
                className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[9px] font-bold text-primary-foreground"
              >
                {count > 9 ? "9+" : count}
              </motion.span>
            )}
          </AnimatePresence>
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-[380px] p-0" sideOffset={8}>
        <div className="flex items-center justify-between px-4 py-3">
          <DropdownMenuLabel className="p-0 text-sm font-semibold">
            Notifications
          </DropdownMenuLabel>
          {count > 0 && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              {count} new
            </Badge>
          )}
        </div>
        <DropdownMenuSeparator className="m-0" />

        <ScrollArea className="h-[400px]">
          {notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Bell className="h-8 w-8 mb-2 opacity-30" />
              <p className="text-xs">No notifications yet</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {notifications.map((notification, i) => (
                <NotificationItem
                  key={notification.id}
                  notification={notification}
                  index={i}
                />
              ))}
            </div>
          )}
        </ScrollArea>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
