import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    // Parse deal-automation.log for processing times
    // Look for pairs: "Processing email..." → "Created deal..."
    const lines = execSync('tail -n 1000 /var/log/deal-automation.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 5000,
    }).split("\n").filter((l) => l.trim())

    const processingTimes: number[] = []
    let lastProcessStart: Date | null = null

    for (const line of lines) {
      const tsMatch = line.match(/\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*)\]/)
      if (!tsMatch) continue
      const ts = new Date(tsMatch[1].replace(" ", "T") + (tsMatch[1].endsWith("Z") ? "" : "Z"))

      if (/Processing email|Checking email|New forward/i.test(line)) {
        lastProcessStart = ts
      } else if (/Created deal|Deal created/i.test(line) && lastProcessStart) {
        const diffMinutes = (ts.getTime() - lastProcessStart.getTime()) / (1000 * 60)
        // Only count reasonable times (< 60 min, > 0)
        if (diffMinutes > 0 && diffMinutes < 60) {
          processingTimes.push(diffMinutes)
        }
        lastProcessStart = null
      }
    }

    // Calculate stats
    const last30Days = processingTimes.slice(-30)
    const avgMinutes = last30Days.length > 0
      ? Math.round(last30Days.reduce((a, b) => a + b, 0) / last30Days.length)
      : 0
    const medianMinutes = last30Days.length > 0
      ? Math.round(last30Days.sort((a, b) => a - b)[Math.floor(last30Days.length / 2)])
      : 0

    return NextResponse.json({
      avgMinutes,
      medianMinutes,
      totalProcessed: last30Days.length,
      trend: processingTimes.slice(-10).map((t) => Math.round(t)),
    })
  } catch (e) {
    console.error("Response time API error:", e)
    return NextResponse.json({ avgMinutes: 0, medianMinutes: 0, totalProcessed: 0, trend: [] })
  }
}
