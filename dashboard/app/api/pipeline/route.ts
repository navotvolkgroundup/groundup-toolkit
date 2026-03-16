import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { withFreshness } from "@/lib/withFreshness"
import { hubspotSearchAllCached } from "@/lib/hubspot"
import { PIPELINE_STAGES } from "@/lib/constants"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    const allDeals = await hubspotSearchAllCached(
      "deals",
      [{ propertyName: "pipeline", operator: "EQ", value: "default" }],
      ["dealname", "dealstage", "amount", "hubspot_owner_id", "createdate", "closedate"],
      [{ propertyName: "createdate", direction: "DESCENDING" }]
    )

    const stageCounts: Record<string, { count: number; deals: Array<{ name: string; amount: string | null; owner: string | null; created: string | null }> }> = {}

    for (const stage of PIPELINE_STAGES) {
      stageCounts[stage.id] = { count: 0, deals: [] }
    }

    for (const deal of allDeals) {
      const stageId = deal.properties.dealstage || ""

      if (!stageCounts[stageId]) stageCounts[stageId] = { count: 0, deals: [] }
      stageCounts[stageId].count++
      stageCounts[stageId].deals.push({
        name: deal.properties.dealname || "Unnamed",
        amount: deal.properties.amount,
        owner: deal.properties.hubspot_owner_id,
        created: deal.properties.createdate,
      })
    }

    const stages = PIPELINE_STAGES.map((s) => ({
      ...s,
      count: stageCounts[s.id]?.count || 0,
      deals: (stageCounts[s.id]?.deals || []).slice(0, 10),
    }))

    return NextResponse.json(withFreshness({ stages, totalDeals: allDeals.length }, null, "hubspot"))
  } catch (e) {
    console.error("Pipeline API error:", e)
    return NextResponse.json({ error: "Failed to fetch pipeline" }, { status: 500 })
  }
}
