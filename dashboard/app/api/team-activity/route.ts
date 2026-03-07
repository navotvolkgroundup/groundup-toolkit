import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearchAll } from "@/lib/hubspot"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

const TEAM_MEMBERS: Record<string, string> = {
  "navot": "Navot",
  "jordan": "Jordan",
  "cory": "Cory",
  "david": "David",
  "allie": "Allie",
}

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    const weeksBack = 8
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - weeksBack * 7)

    const deals = await hubspotSearchAll(
      "deals",
      [{ propertyName: "createdate", operator: "GTE", value: cutoff.getTime().toString() }],
      ["dealname", "createdate", "hubspot_owner_id", "groundup_source"],
      [{ propertyName: "createdate", direction: "ASCENDING" }]
    )

    // Build week labels
    const now = new Date()
    const weekLabels: string[] = []
    const weekStarts: Date[] = []
    for (let i = weeksBack - 1; i >= 0; i--) {
      const weekStart = new Date(now)
      weekStart.setDate(weekStart.getDate() - i * 7)
      weekStart.setHours(0, 0, 0, 0)
      const day = weekStart.getDay()
      weekStart.setDate(weekStart.getDate() - ((day + 6) % 7))
      weekStarts.push(weekStart)
      weekLabels.push(`${weekStart.getDate()}/${weekStart.getMonth() + 1}`)
    }

    // Group deals by team member and week
    // Use deal notes/description to try to identify which team member sourced it
    const heatmap: Array<{ member: string; weeks: number[] }> = []

    for (const [memberId, memberName] of Object.entries(TEAM_MEMBERS)) {
      const weekCounts = new Array(weeksBack).fill(0)

      for (const deal of deals) {
        const source = (deal.properties.groundup_source || "").toLowerCase()
        const owner = (deal.properties.hubspot_owner_id || "").toLowerCase()

        if (source.includes(memberId) || owner.includes(memberId) || source.includes(memberName.toLowerCase())) {
          const created = new Date(deal.properties.createdate || "")
          for (let w = 0; w < weekStarts.length; w++) {
            const weekEnd = new Date(weekStarts[w])
            weekEnd.setDate(weekEnd.getDate() + 7)
            if (created >= weekStarts[w] && created < weekEnd) {
              weekCounts[w]++
              break
            }
          }
        }
      }

      heatmap.push({ member: memberName, weeks: weekCounts })
    }

    return NextResponse.json({ heatmap, weekLabels, totalDeals: deals.length })
  } catch (e) {
    console.error("Team activity API error:", e)
    return NextResponse.json({ heatmap: [], weekLabels: [], totalDeals: 0 })
  }
}
