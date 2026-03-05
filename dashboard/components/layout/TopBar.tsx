"use client"

import { Sun, Moon, Search, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useTheme } from "@/lib/hooks/useTheme"
import { useServicesStore } from "@/lib/store/servicesStore"
import { NotificationPanel } from "@/components/notifications/NotificationPanel"
import { signOut } from "next-auth/react"

export function TopBar() {
  const { theme, toggleTheme } = useTheme()
  const setSearchQuery = useServicesStore((s) => s.setSearchQuery)
  const searchQuery = useServicesStore((s) => s.searchQuery)

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-background/80 backdrop-blur-xl px-6">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold tracking-tight">Dashboard</h1>
      </div>

      <div className="flex items-center gap-3">
        {/* Search */}
        <div className="relative hidden sm:block">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search services..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-64 pl-9 h-9 bg-muted/50 border-none text-sm"
          />
        </div>

        {/* Notifications */}
        <NotificationPanel />

        {/* Theme toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          className="h-9 w-9 text-muted-foreground hover:text-foreground"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>

        {/* Sign out */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="h-9 w-9 text-muted-foreground hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
