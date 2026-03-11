"use client"

import { AppShell } from "@/components/layout/AppShell"
import { Greeting } from "@/components/dashboard/Greeting"
import { StatsBar } from "@/components/dashboard/StatsBar"
import { PipelineFunnel } from "@/components/dashboard/PipelineFunnel"
import { QuickActions } from "@/components/dashboard/QuickActions"
import { DealFlowChart } from "@/components/dashboard/DealFlowChart"
import { TeamHeatmap } from "@/components/dashboard/TeamHeatmap"
import { DealMovements } from "@/components/dashboard/DealMovements"
import { MeetingPrep } from "@/components/dashboard/MeetingPrep"
import { SignalFeed } from "@/components/dashboard/SignalFeed"
import { LeadsPanel } from "@/components/dashboard/LeadsPanel"
import { DealSources } from "@/components/dashboard/DealSources"
import { ResponseTime } from "@/components/dashboard/ResponseTime"
import { SignalConversion } from "@/components/dashboard/SignalConversion"
import { ServiceGrid } from "@/components/services/ServiceGrid"
import { KeyboardShortcuts } from "@/components/dashboard/KeyboardShortcuts"

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-4 mt-2">
      {children}
    </h2>
  )
}

export default function DashboardPage() {
  return (
    <AppShell>
      <KeyboardShortcuts />
      <Greeting />
      <StatsBar />
      <QuickActions />

      {/* Pipeline */}
      <PipelineFunnel />

      {/* Analytics */}
      <SectionHeader>Analytics</SectionHeader>
      <div className="grid gap-6 lg:grid-cols-2 mb-8">
        <DealFlowChart />
        <TeamHeatmap />
      </div>

      {/* Activity & Schedule */}
      <SectionHeader>Activity & Schedule</SectionHeader>
      <div className="grid gap-6 lg:grid-cols-2 mb-8">
        <DealMovements />
        <MeetingPrep />
      </div>

      {/* Metrics */}
      <SectionHeader>Metrics</SectionHeader>
      <div className="grid gap-6 lg:grid-cols-3 mb-8">
        <DealSources />
        <ResponseTime />
        <SignalConversion />
      </div>

      {/* Signals & Leads */}
      <SectionHeader>Scouting</SectionHeader>
      <div className="grid gap-6 lg:grid-cols-2 mb-8">
        <SignalFeed />
        <LeadsPanel />
      </div>

      {/* Services */}
      <SectionHeader>Services</SectionHeader>
      <ServiceGrid />
    </AppShell>
  )
}
