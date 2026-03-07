import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearch } from "@/lib/hubspot"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

const PIPELINE_STAGES = [
  { id: "new", label: "New", order: 0 },
  { id: "meeting1", label: "Meeting 1", order: 1 },
  { id: "meeting2", label: "Meeting 2", order: 2 },
  { id: "dd", label: "Due Diligence", order: 3 },
  { id: "termsheet", label: "Term Sheet", order: 4 },
  { id: "closed", label: "Closed", order: 5 },
  { id: "keeponradar", label: "Keep on Radar", order: 6 },
  { id: "passed", label: "Passed", order: 7 },
]

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    const result = await hubspotSearch(
      "deals",
      [{ propertyName: "pipeline", operator: "HAS_PROPERTY" }],
      ["dealname", "dealstage", "amount", "hubspot_owner_id", "createdate", "closedate"],
      [{ propertyName: "createdate", direction: "DESCENDING" }]
    )

    const stageCounts: Record<string, { count: number; deals: Array<{ name: string; amount: string | null; owner: string | null; created: string | null }> }> = {}

    for (const stage of PIPELINE_STAGES) {
      stageCounts[stage.id] = { count: 0, deals: [] }
    }

    for (const deal of result.results) {
      const stageName = (deal.properties.dealstage || "").toLowerCase().replace(/[\s_-]+/g, "")
      // Map HubSpot stage names to our stage IDs
      let stageId = "new"
      if (stageName.includes("meeting") && stageName.includes("1")) stageId = "meeting1"
      else if (stageName.includes("meeting") && stageName.includes("2")) stageId = "meeting2"
      else if (stageName.includes("diligence") || stageName.includes("dd")) stageId = "dd"
      else if (stageName.includes("term")) stageId = "termsheet"
      else if (stageName.includes("closed") || stageName.includes("won")) stageId = "closed"
      else if (stageName.includes("radar") || stageName.includes("keep")) stageId = "keeponradar"
      else if (stageName.includes("pass") || stageName.includes("lost") || stageName.includes("dead")) stageId = "passed"
      else if (stageName.includes("new") || stageName.includes("qualify")) stageId = "new"

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

    return NextResponse.json({ stages, totalDeals: result.results.length })
  } catch (e) {
    console.error("Pipeline API error:", e)
    return NextResponse.json({ error: "Failed to fetch pipeline" }, { status: 500 })
  }
}
