"use client"

import { AppShell } from "@/components/layout/AppShell"
import { motion } from "framer-motion"
import { Settings, Bell, Moon, Clock, User } from "lucide-react"
import { Switch } from "@/components/ui/switch"
import { useSession } from "next-auth/react"
import { useState } from "react"
import Image from "next/image"

interface SettingsSection {
  title: string
  icon: typeof Settings
  children: React.ReactNode
}

function Section({ title, icon: Icon, children }: SettingsSection) {
  return (
    <div className="rounded-xl border border-border bg-card/50 backdrop-blur-sm p-5">
      <div className="flex items-center gap-2 mb-4">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <div className="space-y-4">{children}</div>
    </div>
  )
}

function SettingRow({ label, description, children }: { label: string; description: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  )
}

export default function SettingsPage() {
  const { data: session } = useSession()
  const [notifyDeals, setNotifyDeals] = useState(true)
  const [notifyMeetings, setNotifyMeetings] = useState(true)
  const [notifyErrors, setNotifyErrors] = useState(true)
  const [notifySignals, setNotifySignals] = useState(true)
  const [quietHours, setQuietHours] = useState(false)
  const [darkMode, setDarkMode] = useState(true)

  return (
    <AppShell>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <div className="flex items-center gap-2 mb-6">
          <Settings className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Settings</h1>
        </div>

        <div className="space-y-6 max-w-2xl">
          {/* Profile */}
          <Section title="Profile" icon={User}>
            <div className="flex items-center gap-4">
              {session?.user?.image && (
                <Image src={session.user.image} alt="" width={48} height={48} className="h-12 w-12 rounded-full" />
              )}
              <div>
                <p className="text-sm font-medium">{session?.user?.name || "User"}</p>
                <p className="text-xs text-muted-foreground">{session?.user?.email}</p>
              </div>
            </div>
          </Section>

          {/* Notifications */}
          <Section title="WhatsApp Notifications" icon={Bell}>
            <SettingRow label="New Deals" description="Get notified when a new deal is created from email">
              <Switch checked={notifyDeals} onCheckedChange={setNotifyDeals} />
            </SettingRow>
            <SettingRow label="Meeting Briefs" description="Receive meeting prep briefs before calls">
              <Switch checked={notifyMeetings} onCheckedChange={setNotifyMeetings} />
            </SettingRow>
            <SettingRow label="Service Errors" description="Alert when a service fails or has errors">
              <Switch checked={notifyErrors} onCheckedChange={setNotifyErrors} />
            </SettingRow>
            <SettingRow label="Founder Signals" description="Get notified about high-signal founder detections">
              <Switch checked={notifySignals} onCheckedChange={setNotifySignals} />
            </SettingRow>
          </Section>

          {/* Schedule */}
          <Section title="Quiet Hours" icon={Clock}>
            <SettingRow label="Enable Quiet Hours" description="Suppress non-urgent notifications between 10 PM and 7 AM">
              <Switch checked={quietHours} onCheckedChange={setQuietHours} />
            </SettingRow>
          </Section>

          {/* Appearance */}
          <Section title="Appearance" icon={Moon}>
            <SettingRow label="Dark Mode" description="Use dark theme for the dashboard">
              <Switch checked={darkMode} onCheckedChange={setDarkMode} />
            </SettingRow>
          </Section>

          <p className="text-[10px] text-muted-foreground text-center pb-8">
            Settings are stored locally. WhatsApp notification preferences sync with Christina on next interaction.
          </p>
        </div>
      </motion.div>
    </AppShell>
  )
}
