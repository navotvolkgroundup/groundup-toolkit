import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { withFreshness } from "@/lib/withFreshness"
import { readFileSync, existsSync } from "fs"
import { join } from "path"

const limiter = rateLimit({ interval: 60_000, limit: 20 })
const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT || "/root/groundup-toolkit"
const SEEN_PATH = join(TOOLKIT_ROOT, "data", "thesis-news-seen.json")
const THESIS_PATH = join(TOOLKIT_ROOT, "skills", "founder-scout", "thesis.yaml")

function parseThesisAreas(): string[] {
  try {
    const content = readFileSync(THESIS_PATH, "utf-8")
    const names: string[] = []
    for (const line of content.split("\n")) {
      const match = line.match(/^\s+- name:\s*"(.+)"/)
      if (match) names.push(match[1])
    }
    return names
  } catch { return [] }
}

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const areas = parseThesisAreas()
  let lastUpdated: string | null = null
  let totalSeen = 0

  try {
    if (existsSync(SEEN_PATH)) {
      const raw = JSON.parse(readFileSync(SEEN_PATH, "utf-8"))
      totalSeen = raw.seen?.length || 0
      lastUpdated = raw.updated || null
    }
  } catch { /* ignore */ }

  return NextResponse.json(
    withFreshness(
      { areas, totalSeen, lastUpdated },
      lastUpdated,
      "thesis-scanner",
      86400,
      false
    )
  )
}
