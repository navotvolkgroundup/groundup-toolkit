"use client"

import dynamic from "next/dynamic"

const Dashboard = dynamic(() => import("@/components/dashboard/DashboardPage"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-sm text-muted-foreground">Loading dashboard...</div>
    </div>
  ),
})

export default function Page() {
  return <Dashboard />
}
