"use client"

import { AppShell } from "@/components/layout/AppShell"
import { StatsBar } from "@/components/dashboard/StatsBar"
import { PipelineFunnel } from "@/components/dashboard/PipelineFunnel"
import { QuickActions } from "@/components/dashboard/QuickActions"
import { DealFlowChart } from "@/components/dashboard/DealFlowChart"
import { TeamHeatmap } from "@/components/dashboard/TeamHeatmap"
import { SignalFeed } from "@/components/dashboard/SignalFeed"
import { ServiceGrid } from "@/components/services/ServiceGrid"
import { ActivityFeed } from "@/components/dashboard/ActivityFeed"

export default function DashboardPage() {
  return (
    <AppShell>
      <StatsBar />
      <QuickActions />
      <PipelineFunnel />

      <div className="grid gap-6 lg:grid-cols-2 mb-8">
        <DealFlowChart />
        <TeamHeatmap />
      </div>

      <div className="mb-8">
        <SignalFeed />
      </div>

      <ServiceGrid />
      <ActivityFeed />
    </AppShell>
  )
}
