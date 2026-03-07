import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearchAll } from "@/lib/hubspot"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

// VC Deal Flow pipeline stages (HubSpot stage IDs → labels)
const PIPELINE_STAGES = [
  { id: "qualifiedtobuy", label: "Sourcing", order: 0 },
  { id: "appointmentscheduled", label: "Screening", order: 1 },
  { id: "presentationscheduled", label: "First Meeting", order: 2 },
  { id: "decisionmakerboughtin", label: "IC Review", order: 3 },
  { id: "contractsent", label: "Due Diligence", order: 4 },
  { id: "closedwon", label: "Term Sheet Offered", order: 5 },
  { id: "1112320899", label: "Term Sheet Signed", order: 6 },
  { id: "1112320900", label: "Investment Closed", order: 7 },
  { id: "1008223160", label: "Portfolio Monitoring", order: 8 },
  { id: "1138024523", label: "Keep on Radar", order: 9 },
  { id: "closedlost", label: "Passed", order: 10 },
]

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    const allDeals = await hubspotSearchAll(
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

    return NextResponse.json({ stages, totalDeals: allDeals.length })
  } catch (e) {
    console.error("Pipeline API error:", e)
    return NextResponse.json({ error: "Failed to fetch pipeline" }, { status: 500 })
  }
}
