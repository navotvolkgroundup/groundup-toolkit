import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { execSync } from "child_process"

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
  const session = await auth()
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const person = req.nextUrl.searchParams.get("person")
  const from = req.nextUrl.searchParams.get("from")
  const to = req.nextUrl.searchParams.get("to")
  const action = req.nextUrl.searchParams.get("action") || "connections"

  try {
    if (action === "intro-path" && from && to) {
      const result = execSync(
        `python3 ${TOOLKIT_ROOT}/scripts/relationship_query.py --json intro-path "${from.replace(/"/g, "")}" "${to.replace(/"/g, "")}"`,
        { encoding: "utf-8", timeout: 5000 }
      ).trim()

      const path: IntroPathStep[] = result ? JSON.parse(result) : []
      return NextResponse.json({ path })
    }

    if (action === "stats") {
      const result = execSync(
        `python3 ${TOOLKIT_ROOT}/scripts/relationship_query.py --json stats`,
        { encoding: "utf-8", timeout: 5000 }
      ).trim()

      const stats = result ? JSON.parse(result) : { people: 0, relationships: 0, by_type: {} }
      return NextResponse.json(stats)
    }

    // Default: connections
    if (!person) {
      return NextResponse.json({ error: "Missing 'person' parameter" }, { status: 400 })
    }

    const result = execSync(
      `python3 ${TOOLKIT_ROOT}/scripts/relationship_query.py --json connections "${person.replace(/"/g, "")}"`,
      { encoding: "utf-8", timeout: 5000 }
    ).trim()

    const connections: Connection[] = result ? JSON.parse(result) : []
    return NextResponse.json({ connections })
  } catch (error) {
    console.error("Relationship query error:", error)
    return NextResponse.json({ connections: [], path: [], error: "Query failed" })
  }
}
