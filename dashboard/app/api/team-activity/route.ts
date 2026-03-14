import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearchAllCached } from "@/lib/hubspot"
import { OWNER_NAMES } from "@/lib/constants"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    const weeksBack = 8
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - weeksBack * 7)

    const deals = await hubspotSearchAllCached(
      "deals",
      [{ propertyName: "createdate", operator: "GTE", value: cutoff.getTime().toString() }],
      ["dealname", "createdate", "hubspot_owner_id", "groundup_source"],
      [{ propertyName: "createdate", direction: "ASCENDING" }]
    )

    // Build week buckets starting from this Monday, going back
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    const todayDay = now.getDay()
    const thisMonday = new Date(now)
    thisMonday.setDate(thisMonday.getDate() - ((todayDay + 6) % 7))

    const weekLabels: string[] = []
    const weekStarts: Date[] = []
    for (let i = weeksBack - 1; i >= 0; i--) {
      const weekStart = new Date(thisMonday)
      weekStart.setDate(weekStart.getDate() - i * 7)
      weekStarts.push(weekStart)
      weekLabels.push(`${weekStart.getDate()}/${weekStart.getMonth() + 1}`)
    }

    // Group deals by team member (owner ID) and week
    const heatmap: Array<{ member: string; weeks: number[] }> = []

    for (const [ownerId, memberName] of Object.entries(OWNER_NAMES)) {
      const weekCounts = new Array(weeksBack).fill(0)

      for (const deal of deals) {
        const dealOwner = deal.properties.hubspot_owner_id || ""
        const source = (deal.properties.groundup_source || "").toLowerCase()

        if (dealOwner === ownerId || source.includes(memberName.toLowerCase())) {
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
