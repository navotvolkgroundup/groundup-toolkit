import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { execFileSync } from "child_process"
import { rateLimit } from "@/lib/rate-limit"
import { withFreshness } from "@/lib/withFreshness"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT || "/root/groundup-toolkit"

interface Connection {
  person: {
    name: string
    email: string | null
    company: string | null
    role: string | null
  }
  rel_type: string
  context: string | null
  source: string | null
  strength: number
  first_seen: string
  last_seen: string
}

interface IntroPathStep {
  person: {
    name: string
    email: string | null
    company: string | null
  }
  via_rel_type: string | null
  via_context: string | null
}

export async function GET(req: NextRequest) {
  // SECURITY FIX (H-1): Add rate limiting (was missing)
  const { ok: rateLimitOk } = await limiter.check(req)
  if (!rateLimitOk) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const person = req.nextUrl.searchParams.get("person")
  const from = req.nextUrl.searchParams.get("from")
  const to = req.nextUrl.searchParams.get("to")
  const action = req.nextUrl.searchParams.get("action") || "connections"

  // SECURITY FIX (C-3): Use execFileSync with argument arrays to prevent command injection.
  // Previously, from/to/person were interpolated into shell strings with only quote removal.
  try {
    if (action === "intro-path" && from && to) {
      const result = execFileSync(
        "python3",
        [`${TOOLKIT_ROOT}/scripts/relationship_query.py`, "--json", "intro-path", from, to],
        { encoding: "utf-8", timeout: 5000 }
      ).trim()

      const path: IntroPathStep[] = result ? JSON.parse(result) : []
      return NextResponse.json(withFreshness({ path }, null, "sqlite"))
    }

    if (action === "stats") {
      const result = execFileSync(
        "python3",
        [`${TOOLKIT_ROOT}/scripts/relationship_query.py`, "--json", "stats"],
        { encoding: "utf-8", timeout: 5000 }
      ).trim()

      const stats = result ? JSON.parse(result) : { people: 0, relationships: 0, by_type: {} }
      return NextResponse.json(withFreshness(stats, null, "sqlite"))
    }

    // Default: connections
    if (!person) {
      return NextResponse.json({ error: "Missing 'person' parameter" }, { status: 400 })
    }

    const result = execFileSync(
      "python3",
      [`${TOOLKIT_ROOT}/scripts/relationship_query.py`, "--json", "connections", person],
      { encoding: "utf-8", timeout: 5000 }
    ).trim()

    const connections: Connection[] = result ? JSON.parse(result) : []
    return NextResponse.json(withFreshness({ connections }, null, "sqlite"))
  } catch (error) {
    console.error("Relationship query error:", error)
    return NextResponse.json({ connections: [], path: [], error: "Query failed" })
  }
}
