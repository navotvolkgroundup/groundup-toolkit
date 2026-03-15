"use client"

import { AppShell } from "@/components/layout/AppShell"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { Greeting } from "@/components/dashboard/Greeting"
import { StatsBar } from "@/components/dashboard/StatsBar"
import { PipelineFunnel } from "@/components/dashboard/PipelineFunnel"
import { QuickActions } from "@/components/dashboard/QuickActions"
import { DealFlowChart } from "@/components/dashboard/DealFlowChart"
import { TeamHeatmap } from "@/components/dashboard/TeamHeatmap"
import { DealMovements } from "@/components/dashboard/DealMovements"
import { StaleDeals } from "@/components/dashboard/StaleDeals"
import { SignalFeed } from "@/components/dashboard/SignalFeed"
import { LeadsPanel } from "@/components/dashboard/LeadsPanel"
import { DealSources } from "@/components/dashboard/DealSources"
import { ResponseTime } from "@/components/dashboard/ResponseTime"
import { SignalConversion } from "@/components/dashboard/SignalConversion"
import { ScoringInsights } from "@/components/dashboard/ScoringInsights"
import { RelationshipGraph } from "@/components/dashboard/RelationshipGraph"
import { ThesisNewsFeed } from "@/components/dashboard/ThesisNewsFeed"
import { PortfolioSummary } from "@/components/dashboard/PortfolioSummary"
import { ServiceGrid } from "@/components/services/ServiceGrid"
import { KeyboardShortcuts } from "@/components/dashboard/KeyboardShortcuts"
import { WhatsNewBanner } from "@/components/dashboard/WhatsNewBanner"
import { useEventStream } from "@/lib/hooks/useEventStream"

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-4 mt-2">
      {children}
    </h2>
  )
}

export default function DashboardPage() {
  useEventStream()

  return (
    <AppShell>
      <KeyboardShortcuts />
      <ErrorBoundary>
        <Greeting />
      </ErrorBoundary>
      <ErrorBoundary>
        <WhatsNewBanner />
      </ErrorBoundary>
      <ErrorBoundary>
        <StatsBar />
      </ErrorBoundary>
      <ErrorBoundary>
        <QuickActions />
      </ErrorBoundary>

      {/* Pipeline */}
      <ErrorBoundary>
        <PipelineFunnel />
      </ErrorBoundary>

      {/* Analytics */}
      <SectionHeader>Analytics</SectionHeader>
      <ErrorBoundary>
        <div className="grid gap-6 lg:grid-cols-2 mb-8">
          <DealFlowChart />
          <TeamHeatmap />
        </div>
      </ErrorBoundary>

      {/* Activity & Pipeline Health */}
      <SectionHeader>Activity & Pipeline Health</SectionHeader>
      <ErrorBoundary>
        <div className="grid gap-6 lg:grid-cols-2 mb-8">
          <DealMovements />
          <StaleDeals />
        </div>
      </ErrorBoundary>

      {/* Portfolio Overview */}
      <SectionHeader>Portfolio</SectionHeader>
      <ErrorBoundary>
        <div className="mb-8">
          <PortfolioSummary />
        </div>
      </ErrorBoundary>

      {/* Metrics + Scoring Insights */}
      <SectionHeader>Metrics & Insights</SectionHeader>
      <ErrorBoundary>
        <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-4 mb-8">
          <DealSources />
          <ResponseTime />
          <SignalConversion />
          <ScoringInsights />
        </div>
      </ErrorBoundary>

      {/* Scouting + Thesis */}
      <SectionHeader>Scouting & Market Intelligence</SectionHeader>
      <ErrorBoundary>
        <div className="grid gap-6 lg:grid-cols-2 mb-4">
          <SignalFeed />
          <LeadsPanel />
        </div>
      </ErrorBoundary>
      <ErrorBoundary>
        <div className="mb-8">
          <ThesisNewsFeed />
        </div>
      </ErrorBoundary>

      {/* Network */}
      <SectionHeader>Network</SectionHeader>
      <ErrorBoundary>
        <RelationshipGraph />
      </ErrorBoundary>

      {/* Services */}
      <SectionHeader>Services</SectionHeader>
      <ErrorBoundary>
        <ServiceGrid />
      </ErrorBoundary>
    </AppShell>
  )
}
