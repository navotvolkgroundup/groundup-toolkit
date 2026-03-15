"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Sidebar } from "./Sidebar"
import { TopBar } from "./TopBar"
import { ChatWindow } from "@/components/chat/ChatWindow"
import { ChatFAB } from "@/components/chat/ChatFAB"
import { Providers } from "@/components/providers"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useEventStream } from "@/lib/hooks/useEventStream"

function EventStreamListener() {
  useEventStream()
  return null
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <Providers>
      <EventStreamListener />
      <TooltipProvider delayDuration={0}>
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
        <div
          className={cn(
            "min-h-screen transition-all duration-300",
            collapsed ? "ml-16" : "ml-60"
          )}
        >
          <TopBar />
          <main className="p-6">{children}</main>
        </div>
        <ChatWindow />
        <ChatFAB />
      </TooltipProvider>
    </Providers>
  )
}
