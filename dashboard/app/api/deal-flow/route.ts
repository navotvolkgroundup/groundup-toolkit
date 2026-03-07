import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearchAll } from "@/lib/hubspot"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    // Get deals from last 12 weeks
    const weeksBack = 12
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - weeksBack * 7)

    const deals = await hubspotSearchAll(
      "deals",
      [{ propertyName: "createdate", operator: "GTE", value: cutoff.getTime().toString() }],
      ["dealname", "createdate"],
      [{ propertyName: "createdate", direction: "ASCENDING" }]
    )

    // Group by week — start from this Monday, step back in 7-day intervals
    const weeks: Array<{ week: string; label: string; count: number }> = []
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    const todayDay = now.getDay()
    const thisMonday = new Date(now)
    thisMonday.setDate(thisMonday.getDate() - ((todayDay + 6) % 7))

    for (let i = weeksBack - 1; i >= 0; i--) {
      const weekStart = new Date(thisMonday)
      weekStart.setDate(weekStart.getDate() - i * 7)

      const weekEnd = new Date(weekStart)
      weekEnd.setDate(weekEnd.getDate() + 7)

      const count = deals.filter((d) => {
        const created = new Date(d.properties.createdate || "")
        return created >= weekStart && created < weekEnd
      }).length

      const label = `${weekStart.getDate()}/${weekStart.getMonth() + 1}`
      weeks.push({ week: weekStart.toISOString().slice(0, 10), label, count })
    }

    return NextResponse.json({ weeks, totalDeals: deals.length })
  } catch (e) {
    console.error("Deal flow API error:", e)
    return NextResponse.json({ weeks: [], totalDeals: 0 })
  }
}
