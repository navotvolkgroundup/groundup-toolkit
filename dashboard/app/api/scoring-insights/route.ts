import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { withFreshness } from "@/lib/withFreshness"
import { execSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 10 })

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    const result = execSync(
      `cd /root/toolkit/skills/founder-scout && python3 scout.py calibrate --json 2>/dev/null`,
      { encoding: "utf-8", timeout: 10000 }
    ).trim()

    const report = JSON.parse(result)

    return NextResponse.json(
      withFreshness(report, new Date().toISOString(), "founder-scout-db", 3600, false)
    )
  } catch (err) {
    console.error("Scoring insights error:", err)
    return NextResponse.json(
      withFreshness(
        { dimensions: {}, precision_by_tier: {}, total_outcomes: 0, sufficient_data: false, current_weights: {} },
        new Date().toISOString(),
        "founder-scout-db",
        0,
        false
      )
    )
  }
}
