import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { getCached, setCache, CACHE_TTL } from "@/lib/cache"
import { hubspotSearch } from "@/lib/hubspot"
import { withFreshness } from "@/lib/withFreshness"
import { execSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

function countLogMatches(logFile: string, pattern: RegExp, daysBack: number): number {
  try {
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - daysBack)
    const cutoffStr = cutoff.toISOString().slice(0, 10)
    const lines = execSync(`tail -n 500 "${logFile}" 2>/dev/null || true`, {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n")

    return lines.filter((line) => {
      if (!pattern.test(line)) return false
      const dateMatch = line.match(/\d{4}-\d{2}-\d{2}/)
      if (!dateMatch) return true
      return dateMatch[0] >= cutoffStr
    }).length
  } catch {
    return 0
  }
}

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  try {
    const cacheKey = "stats:dashboard"
    const cached = getCached<Record<string, number>>(cacheKey)
    if (cached) return NextResponse.json(withFreshness(cached, Date.now(), "cache", 300, true))

    // Deals this week from HubSpot (VC Deal Flow pipeline only)
    const weekAgo = new Date()
    weekAgo.setDate(weekAgo.getDate() - 7)
    const weekResult = await hubspotSearch(
      "deals",
      [
        { propertyName: "createdate", operator: "GTE", value: weekAgo.getTime().toString() },
        { propertyName: "pipeline", operator: "EQ", value: "default" },
      ],
      ["dealname"],
    )
    const dealsThisWeek = weekResult.total

    // Deals this month from HubSpot (VC Deal Flow pipeline only)
    const monthAgo = new Date()
    monthAgo.setDate(monthAgo.getDate() - 30)
    const monthResult = await hubspotSearch(
      "deals",
      [
        { propertyName: "createdate", operator: "GTE", value: monthAgo.getTime().toString() },
        { propertyName: "pipeline", operator: "EQ", value: "default" },
      ],
      ["dealname"],
    )
    const dealsThisMonth = monthResult.total

    // Decks analyzed this month (from logs)
    const decksAnalyzed = countLogMatches(
      "/var/log/deal-automation.log",
      /Created deal|Analyzed|evaluation complete/i,
      30
    )

    // Meetings recorded this month
    const meetingsRecorded = countLogMatches(
      "/var/log/meeting-bot.log",
      /Joined meeting|Recording|Summary sent/i,
      30
    )

    // Emails processed this week
    const emailsProcessed = countLogMatches(
      "/var/log/deal-automation.log",
      /Processing email|Created deal|Processed.*\d+/i,
      7
    )

    // Founder signals this week
    const founderSignals = countLogMatches(
      "/var/log/founder-scout.log",
      /relevant profile|Signal detected/i,
      7
    )

    const stats = {
      dealsThisWeek,
      dealsThisMonth,
      decksAnalyzed,
      meetingsRecorded,
      emailsProcessed,
      founderSignals,
    }

    setCache(cacheKey, stats, CACHE_TTL)

    return NextResponse.json(withFreshness(stats, Date.now(), "hubspot", 300))
  } catch (e) {
    console.error("Stats API error:", e)
    return NextResponse.json({
      dealsThisWeek: 0,
      dealsThisMonth: 0,
      decksAnalyzed: 0,
      meetingsRecorded: 0,
      emailsProcessed: 0,
      founderSignals: 0,
    })
  }
}
