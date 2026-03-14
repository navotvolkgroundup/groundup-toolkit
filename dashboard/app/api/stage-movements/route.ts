import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearchAll } from "@/lib/hubspot"
import { STAGE_LABELS, OWNER_NAMES, CLOSED_STAGES } from "@/lib/constants"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    // Get deals modified in the last 7 days
    const weekAgo = new Date()
    weekAgo.setDate(weekAgo.getDate() - 7)

    const deals = await hubspotSearchAll(
      "deals",
      [
        { propertyName: "pipeline", operator: "EQ", value: "default" },
        { propertyName: "hs_lastmodifieddate", operator: "GTE", value: weekAgo.getTime().toString() },
      ],
      ["dealname", "dealstage", "hs_deal_stage_probability", "hubspot_owner_id", "hs_lastmodifieddate", "amount"],
      [{ propertyName: "hs_lastmodifieddate", direction: "DESCENDING" }]
    )

    // Also get deals that are stale (>30 days in same stage)
    const thirtyDaysAgo = new Date()
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)

    // Find stale deals: active stages, not modified recently
    const allActiveDeals = await hubspotSearchAll(
      "deals",
      [
        { propertyName: "pipeline", operator: "EQ", value: "default" },
        { propertyName: "hs_lastmodifieddate", operator: "LTE", value: thirtyDaysAgo.getTime().toString() },
      ],
      ["dealname", "dealstage", "hubspot_owner_id", "hs_lastmodifieddate", "amount"],
      [{ propertyName: "hs_lastmodifieddate", direction: "ASCENDING" }]
    )

    // Filter stale deals to active pipeline stages only (not passed/closed)
    const staleDeals = allActiveDeals
      .filter((d) => !CLOSED_STAGES.has(d.properties.dealstage || ""))
      .slice(0, 10)
      .map((d) => ({
        id: d.id,
        name: d.properties.dealname || "Unnamed",
        stage: STAGE_LABELS[d.properties.dealstage || ""] || d.properties.dealstage || "Unknown",
        owner: OWNER_NAMES[d.properties.hubspot_owner_id || ""] || null,
        lastModified: d.properties.hs_lastmodifieddate,
        daysStale: Math.floor((Date.now() - new Date(d.properties.hs_lastmodifieddate || "").getTime()) / (1000 * 60 * 60 * 24)),
      }))

    // Recent movements: deals modified this week (potential stage changes)
    const movements = deals.slice(0, 15).map((d) => ({
      id: d.id,
      name: d.properties.dealname || "Unnamed",
      stage: STAGE_LABELS[d.properties.dealstage || ""] || d.properties.dealstage || "Unknown",
      owner: OWNER_NAMES[d.properties.hubspot_owner_id || ""] || null,
      lastModified: d.properties.hs_lastmodifieddate,
      amount: d.properties.amount,
    }))

    return NextResponse.json({ movements, staleDeals })
  } catch (e) {
    console.error("Stage movements API error:", e)
    return NextResponse.json({ movements: [], staleDeals: [] })
  }
}
