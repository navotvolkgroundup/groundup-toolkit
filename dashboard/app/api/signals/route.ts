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
    const lines = execSync('tail -n 300 /var/log/founder-scout.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n")

    for (const line of lines) {
      if (!line.trim()) continue

      // Extract timestamp
      const tsMatch = line.match(/\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*)\]/)
      const timestamp = tsMatch ? new Date(tsMatch[1].replace(" ", "T") + (tsMatch[1].endsWith("Z") ? "" : "Z")).toISOString() : null
      if (!timestamp) continue

      // Determine signal strength
      let strength: Signal["strength"] = "low"
      const upper = line.toUpperCase()
      if (upper.includes("HIGH") || upper.includes("STEALTH") || upper.includes("LEFT ROLE") || upper.includes("FOUNDING")) {
        strength = "high"
      } else if (upper.includes("MEDIUM") || upper.includes("EXPLORING") || upper.includes("OPEN TO")) {
        strength = "medium"
      }

      // Try to extract name and signal description
      // Pattern: "Signal: Name - description" or "Detected: Name at Company"
      let name = "Unknown"
      let company = ""
      let signal = line

      const nameMatch = line.match(/(?:Signal|Detected|Profile|Found)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)/i)
      if (nameMatch) name = nameMatch[1]

      const companyMatch = line.match(/(?:at|from|ex-|formerly)\s+([A-Z][A-Za-z0-9 ]+?)(?:\s*[-,.]|\s*$)/i)
      if (companyMatch) company = companyMatch[1].trim()

      // Clean up signal text
      signal = line
        .replace(/^\[\d{4}-\d{2}-\d{2}[^\]]*\]\s*/, "")
        .replace(/^[A-Za-z ]+:\s*/, "")
        .trim()

      if (signal.length < 10) continue

      // Only include relevant signal lines
      if (!/signal|detect|profile|found|scout|stealth|left|founding|exploring/i.test(line)) continue

      signals.push({
        id: Math.abs(hashCode(line)).toString(36),
        name,
        company,
        signal: signal.slice(0, 200),
        strength,
        timestamp,
        source: "LinkedIn",
      })
    }
  } catch {
    // Ignore errors
  }

  return signals.sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 20)
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
