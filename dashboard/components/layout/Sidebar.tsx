"use client"

import { cn } from "@/lib/utils"
import { LayoutDashboard, MessageSquare, Settings, ChevronLeft, ChevronRight } from "lucide-react"
import { ChristinaAvatar } from "@/components/ChristinaAvatar"
import { OnlineDot } from "./StatusBadge"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useChatStore } from "@/lib/store/chatStore"
import { useSession } from "next-auth/react"
import Image from "next/image"

const navItems = [
  { label: "Dashboard", icon: LayoutDashboard, href: "#" },
  { label: "Chat", icon: MessageSquare, href: "#chat" },
  { label: "Settings", icon: Settings, href: "#settings" },
]

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const openChat = useChatStore((s) => s.openChat)
  const { data: session } = useSession()

  const userName = session?.user?.name?.split(" ")[0] ?? "User"
  const userInitials = session?.user?.name
    ? session.user.name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : "?"
  const userImage = session?.user?.image

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-border bg-card/80 backdrop-blur-xl transition-all duration-300",
        collapsed ? "w-16" : "w-60"
      )}
    >
      {/* Logo area */}
      <div className="flex h-16 items-center gap-3 border-b border-border px-4">
        <ChristinaAvatar size="md" className="rounded-xl" />
        {!collapsed && (
          <div className="flex flex-col">
            <span className="text-sm font-semibold tracking-tight">Christina</span>
            <span className="text-[10px] text-muted-foreground">by GroundUp</span>
          </div>
        )}
      </div>

      {/* Online status */}
      <div className={cn("flex items-center gap-2 px-4 py-3", collapsed && "justify-center")}>
        <OnlineDot online />
        {!collapsed && <span className="text-xs text-muted-foreground">Online</span>}
      </div>

      {/* Nav items */}
      <nav className="flex flex-1 flex-col gap-1 px-2">
        {navItems.map((item) => {
          const content = (
            <Button
              key={item.label}
              variant="ghost"
              onClick={() => {
                if (item.label === "Chat") openChat()
              }}
              className={cn(
                "w-full justify-start gap-3 text-muted-foreground hover:text-foreground hover:bg-accent",
                collapsed && "justify-center px-0"
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="text-sm">{item.label}</span>}
            </Button>
          )

          if (collapsed) {
            return (
              <Tooltip key={item.label} delayDuration={0}>
                <TooltipTrigger asChild>{content}</TooltipTrigger>
                <TooltipContent side="right">{item.label}</TooltipContent>
              </Tooltip>
            )
          }
          return content
        })}
      </nav>

      {/* Team member */}
      <div
        className={cn(
          "flex items-center gap-3 border-t border-border p-4",
          collapsed && "justify-center"
        )}
      >
        {userImage ? (
          <Image
            src={userImage}
            alt={userName}
            width={32}
            height={32}
            className="h-8 w-8 shrink-0 rounded-full"
          />
        ) : (
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-medium text-primary">
            {userInitials}
          </div>
        )}
        {!collapsed && (
          <div className="flex flex-col">
            <span className="text-xs font-medium">{userName}</span>
            <span className="text-[10px] text-muted-foreground">{session?.user?.email}</span>
          </div>
        )}
      </div>

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        className="absolute -right-3 top-20 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronLeft className="h-3 w-3" />}
      </button>
    </aside>
  )
}
