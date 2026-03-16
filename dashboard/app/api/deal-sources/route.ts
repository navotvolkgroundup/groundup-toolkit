import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearchAll } from "@/lib/hubspot"
import { withFreshness } from "@/lib/withFreshness"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    // Get deals from last 90 days
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - 90)

    const deals = await hubspotSearchAll(
      "deals",
      [
        { propertyName: "pipeline", operator: "EQ", value: "default" },
        { propertyName: "createdate", operator: "GTE", value: cutoff.getTime().toString() },
      ],
      ["dealname", "groundup_source", "createdate"],
    )

    // Categorize by source
    const sources: Record<string, number> = {
      "Email Forward": 0,
      "Founder Scout": 0,
      "Manual": 0,
      "Referral": 0,
      "Other": 0,
    }

    for (const deal of deals) {
      const src = (deal.properties.groundup_source || "").toLowerCase()
      if (src.includes("email") || src.includes("forward") || src.includes("inbox")) {
        sources["Email Forward"]++
      } else if (src.includes("scout") || src.includes("linkedin") || src.includes("signal")) {
        sources["Founder Scout"]++
      } else if (src.includes("referral") || src.includes("intro")) {
        sources["Referral"]++
      } else if (src.includes("manual") || src.includes("direct")) {
        sources["Manual"]++
      } else if (src) {
        sources["Other"]++
      } else {
        sources["Manual"]++ // No source = manual entry
      }
    }

    const breakdown = Object.entries(sources)
      .map(([name, count]) => ({ name, count }))
      .filter((s) => s.count > 0)
      .sort((a, b) => b.count - a.count)

    return NextResponse.json(withFreshness({ sources: breakdown, total: deals.length }, null, "hubspot"))
  } catch (e) {
    console.error("Deal sources API error:", e)
    return NextResponse.json({ sources: [], total: 0 })
  }
}
