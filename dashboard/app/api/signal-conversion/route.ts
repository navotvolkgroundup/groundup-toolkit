import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotSearchAll } from "@/lib/hubspot"
import { execSync } from "child_process"
import { withFreshness } from "@/lib/withFreshness"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    // Count signals detected from founder-scout logs (last 30 days)
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - 30)
    const cutoffStr = cutoff.toISOString().slice(0, 10)

    const lines = execSync('tail -n 2000 /var/log/founder-scout.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 5000,
    }).split("\n").filter((l) => l.trim())

    let signalsDetected = 0
    for (const line of lines) {
      if (!/Kept \(positive signal\)|RELEVANT:/i.test(line)) continue
      const dateMatch = line.match(/\d{4}-\d{2}-\d{2}/)
      if (dateMatch && dateMatch[0] >= cutoffStr) signalsDetected++
    }

    // Count deals created from scout/signal source (last 30 days)
    const deals = await hubspotSearchAll(
      "deals",
      [
        { propertyName: "pipeline", operator: "EQ", value: "default" },
        { propertyName: "createdate", operator: "GTE", value: cutoff.getTime().toString() },
      ],
      ["dealname", "groundup_source"],
    )

    const signalDeals = deals.filter((d) => {
      const src = (d.properties.groundup_source || "").toLowerCase()
      return src.includes("scout") || src.includes("linkedin") || src.includes("signal")
    })

    const conversionRate = signalsDetected > 0
      ? Math.round((signalDeals.length / signalsDetected) * 100)
      : 0

    return NextResponse.json(withFreshness({
      signalsDetected,
      dealsCreated: signalDeals.length,
      conversionRate,
      totalDeals: deals.length,
    }, null, "log_file"))
  } catch (e) {
    console.error("Signal conversion API error:", e)
    return NextResponse.json({ signalsDetected: 0, dealsCreated: 0, conversionRate: 0, totalDeals: 0 })
  }
}
