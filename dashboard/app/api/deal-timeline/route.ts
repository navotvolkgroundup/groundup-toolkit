import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT || "/root/groundup-toolkit"

export interface TimelineEvent {
  type: "note" | "deal_created" | "signal" | "email"
  date: string
  summary: string
  source: string
}

export interface TimelineResponse {
  company: string
  companyId: string | null
  events: TimelineEvent[]
}

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const company = req.nextUrl.searchParams.get("company")
  const dealId = req.nextUrl.searchParams.get("dealId")

  if (!company && !dealId) {
    return NextResponse.json({ error: "Must provide company or dealId" }, { status: 400 })
  }

  try {
    const args = company
      ? `--company "${company.replace(/"/g, '\\"')}"`
      : `--deal-id ${dealId}`

    const result = execSync(
      `python3 ${TOOLKIT_ROOT}/scripts/deal_timeline.py ${args}`,
      { encoding: "utf-8", timeout: 15000 }
    ).trim()

    const timeline = JSON.parse(result) as TimelineResponse
    return NextResponse.json(timeline)
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error"
    console.error("Timeline error:", message)
    return NextResponse.json(
      { company: company || "", companyId: null, events: [] },
      { status: 200 }
    )
  }
}
