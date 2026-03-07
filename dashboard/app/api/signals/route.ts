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
}

function parseSignals(): Signal[] {
  const signals: Signal[] = []

  try {
    const lines = execSync('tail -n 500 /var/log/founder-scout.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n")

    let currentTimestamp: string | null = null
    let currentVisitName: string | null = null

    for (const line of lines) {
      // Track timestamp from header lines: [2026-03-05 07:00:01.756856]
      const tsMatch = line.match(/^\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})/)
      if (tsMatch) {
        currentTimestamp = new Date(tsMatch[1].replace(" ", "T") + "Z").toISOString()
        currentVisitName = null
        continue
      }

      if (!currentTimestamp) continue
      const trimmed = line.trim()

      // Track "Visiting Name..." lines for RELEVANT context
      const visitMatch = trimmed.match(/^\[\d+\/\d+\] Visiting (.+?)\.\.\./)
      if (visitMatch) {
        currentVisitName = visitMatch[1]
        continue
      }

      // "RELEVANT: description" — confirmed relevant profile
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
        })
        continue
      }

      // "Kept (positive signal): Name — description"
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
        })
        continue
      }

      // "Email sent to" or "WhatsApp sent" with relevant count
      const resultMatch = trimmed.match(/^Scan complete: .+?(\d+) relevant/)
      if (resultMatch) {
        // Skip — summary line, not a signal
        continue
      }
    }
  } catch {
    // Ignore errors
  }

  return signals.sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 20)
}

function extractCompany(text: string): string {
  // Look for "at Company" or "CEO of Company" patterns
  const match = text.match(/(?:at|of|@)\s+(?:a\s+)?([A-Z][A-Za-z0-9.]+(?:\s+[A-Z][A-Za-z0-9.]+)?)/i)
  if (match) return match[1].trim()
  // Look for "stealth" mentions
  if (/stealth/i.test(text)) return "Stealth"
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
