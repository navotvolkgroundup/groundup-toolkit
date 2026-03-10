import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

interface Signal {
  id: string
  name: string
  company: string
  signal: string
  strength: "high" | "medium" | "low"
  timestamp: string
  source: string
  linkedinUrl: string | null
}

function parseSignals(): Signal[] {
  // Primary: read from founder-scout database (has LinkedIn URLs)
  try {
    const dbResult = execSync(
      `python3 -c "
import sqlite3, json
conn = sqlite3.connect('/root/.openclaw/data/founder-scout.db')
rows = conn.execute('''
  SELECT p.id, p.name, p.linkedin_url, p.signal_tier, p.last_signal, p.last_scanned, p.headline, p.github_url
  FROM tracked_people p
  WHERE p.status = 'active' AND p.last_signal IS NOT NULL
  ORDER BY p.last_scanned DESC
  LIMIT 20
''').fetchall()
print(json.dumps([dict(id=r[0], name=r[1], linkedin_url=r[2], signal_tier=r[3], last_signal=r[4], last_scanned=r[5], headline=r[6], github_url=r[7]) for r in rows]))
" 2>/dev/null`,
      { encoding: "utf-8", timeout: 5000 }
    ).trim()

    if (dbResult) {
      const rows = JSON.parse(dbResult) as Array<{
        id: number; name: string; linkedin_url: string | null; signal_tier: string
        last_signal: string; last_scanned: string; headline: string | null; github_url: string | null
      }>
      return rows.map((r) => ({
        id: r.id.toString(),
        name: r.name,
        company: extractCompany(r.last_signal, r.headline),
        signal: r.last_signal.slice(0, 200),
        strength: (r.signal_tier === "high" ? "high" : r.signal_tier === "medium" ? "medium" : "low") as Signal["strength"],
        timestamp: new Date(r.last_scanned).toISOString(),
        source: r.linkedin_url ? "LinkedIn" : r.github_url ? "GitHub" : "LinkedIn",
        linkedinUrl: r.linkedin_url || null,
      }))
    }
  } catch {
    // Fall through to log-based parsing
  }

  // Fallback: parse log files (no LinkedIn URLs available)
  const signals: Signal[] = []
  try {
    const lines = execSync('tail -n 500 /var/log/founder-scout.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n")

    let currentTimestamp: string | null = null
    let currentVisitName: string | null = null

    for (const line of lines) {
      const tsMatch = line.match(/^\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})/)
      if (tsMatch) {
        currentTimestamp = new Date(tsMatch[1].replace(" ", "T") + "Z").toISOString()
        currentVisitName = null
        continue
      }

      if (!currentTimestamp) continue
      const trimmed = line.trim()

      const visitMatch = trimmed.match(/^\[\d+\/\d+\] Visiting (.+?)\.\.\./)
      if (visitMatch) { currentVisitName = visitMatch[1]; continue }

      const relevantMatch = trimmed.match(/^RELEVANT:\s*(.+)/)
      if (relevantMatch && currentVisitName) {
        const description = relevantMatch[1]
        signals.push({
          id: Math.abs(hashCode(currentVisitName + currentTimestamp)).toString(36),
          name: currentVisitName,
          company: extractCompany(description),
          signal: description.slice(0, 200),
          strength: getStrength(description),
          timestamp: currentTimestamp,
          source: "LinkedIn",
          linkedinUrl: null,
        })
        continue
      }

      const keptMatch = trimmed.match(/^Kept \(positive signal\):\s*(.+?)\s*—\s*(.+)/)
      if (keptMatch) {
        signals.push({
          id: Math.abs(hashCode(keptMatch[1] + currentTimestamp)).toString(36),
          name: keptMatch[1],
          company: extractCompany(keptMatch[2]),
          signal: keptMatch[2].slice(0, 200),
          strength: getStrength(keptMatch[2]),
          timestamp: currentTimestamp,
          source: "LinkedIn",
          linkedinUrl: null,
        })
        continue
      }
    }
  } catch {
    // Ignore errors
  }

  const byName = new Map<string, Signal>()
  for (const s of signals) {
    const existing = byName.get(s.name)
    if (!existing || s.timestamp > existing.timestamp) byName.set(s.name, s)
  }

  return Array.from(byName.values())
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    .slice(0, 20)
}

function extractCompany(text: string, headline?: string | null): string {
  // Try headline first (e.g. "CEO at Everywhen")
  const src = headline || text
  const match = src.match(/(?:at|of|@)\s+(?:a\s+)?([A-Z][A-Za-z0-9.]+(?:\s+[A-Z][A-Za-z0-9.]+)?)/i)
  if (match) return match[1].trim()
  if (/stealth/i.test(src)) return "Stealth"
  // Try text if headline didn't match
  if (headline && text !== headline) {
    const textMatch = text.match(/(?:at|of|@)\s+(?:a\s+)?([A-Z][A-Za-z0-9.]+(?:\s+[A-Z][A-Za-z0-9.]+)?)/i)
    if (textMatch) return textMatch[1].trim()
    if (/stealth/i.test(text)) return "Stealth"
  }
  return ""
}

function getStrength(text: string): Signal["strength"] {
  const lower = text.toLowerCase()
  if (lower.includes("stealth") || lower.includes("founding") || lower.includes("co-founder") || lower.includes("left") || lower.includes("exited")) {
    return "high"
  }
  if (lower.includes("exploring") || lower.includes("open to") || lower.includes("next chapter") || lower.includes("building")) {
    return "medium"
  }
  return "low"
}

function hashCode(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0
  }
  return hash
}

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const signals = parseSignals()
  return NextResponse.json({ signals })
}
