import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execFileSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 10 })

const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT || "/root/groundup-toolkit"

const ALLOWED_ACTIONS: Record<string, { command: string; description: string }> = {
  "founder-scout-scan": {
    command: ". /root/.env && python3 /root/.openclaw/skills/founder-scout/scout.py scan >> /var/log/founder-scout.log 2>&1 &",
    description: "Run Founder Scout scan",
  },
  "email-to-deal": {
    command: ". /root/.env && /root/email-to-deal-automation.py >> /var/log/deal-automation.log 2>&1 &",
    description: "Process emails now",
  },
  "meeting-check": {
    command: "/root/.openclaw/skills/meeting-reminders/meeting-reminders reminders >> /var/log/meeting-reminders.log 2>&1 &",
    description: "Check upcoming meetings",
  },
  "thesis-scanner": {
    command: `. /root/.env && python3 ${process.env.TOOLKIT_ROOT || "/root/groundup-toolkit"}/scripts/thesis_scanner.py >> /var/log/thesis-scanner.log 2>&1 &`,
    description: "Run thesis market scanner",
  },
}

// Actions that take parameters (handled separately)
const PARAM_ACTIONS = ["move-deal-stage", "mark-approached"] as const

export async function POST(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  let body
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: "Bad Request" }, { status: 400 })
  }

  const { action } = body
  if (typeof action !== "string") {
    return NextResponse.json({ error: "Invalid action" }, { status: 400 })
  }

  // SECURITY FIX (C-1): Use execFileSync with argument arrays to prevent command injection.
  // Previously, dealId/stageId/personId were interpolated into shell strings.
  if (action === "move-deal-stage") {
    const { dealId, stageId } = body as { dealId?: string; stageId?: string }
    if (!dealId || !stageId) {
      return NextResponse.json({ error: "dealId and stageId required" }, { status: 400 })
    }
    if (!/^\d+$/.test(dealId) || !/^\d+$/.test(stageId)) {
      return NextResponse.json({ error: "Invalid dealId or stageId" }, { status: 400 })
    }
    try {
      const result = execFileSync(
        "python3",
        [`${TOOLKIT_ROOT}/scripts/deal_action.py`, "move-stage", dealId, stageId],
        { encoding: "utf-8", timeout: 10000 }
      )
      return NextResponse.json({ ok: true, action: "Deal stage updated", result: JSON.parse(result) })
    } catch (err) {
      console.error("move-deal-stage error:", err)
      return NextResponse.json({ error: "Failed to update deal stage" }, { status: 500 })
    }
  }

  if (action === "signal-to-deal") {
    const { personId } = body as { personId?: string }
    if (!personId) {
      return NextResponse.json({ error: "personId required" }, { status: 400 })
    }
    if (!/^\d+$/.test(personId)) {
      return NextResponse.json({ error: "Invalid personId" }, { status: 400 })
    }
    try {
      const result = execFileSync(
        "python3",
        [`${TOOLKIT_ROOT}/scripts/signal_to_deal.py`, personId, "--json"],
        { encoding: "utf-8", timeout: 15000 }
      ).trim()
      return NextResponse.json({ ok: true, action: "Deal created from signal", result: JSON.parse(result) })
    } catch (err) {
      console.error("signal-to-deal error:", err)
      return NextResponse.json({ error: "Failed to create deal from signal" }, { status: 500 })
    }
  }

  if (action === "mark-approached") {
    const { personId } = body as { personId?: string }
    if (!personId) {
      return NextResponse.json({ error: "personId required" }, { status: 400 })
    }
    if (!/^\d+$/.test(personId)) {
      return NextResponse.json({ error: "Invalid personId" }, { status: 400 })
    }
    try {
      execFileSync(
        "python3",
        [`${TOOLKIT_ROOT}/skills/founder-scout/scout.py`, "approach-id", personId],
        { encoding: "utf-8", timeout: 5000 }
      )
      return NextResponse.json({ ok: true, action: "Marked as approached" })
    } catch (err) {
      console.error("mark-approached error:", err)
      return NextResponse.json({ error: "Failed to mark as approached" }, { status: 500 })
    }
  }

  // Simple fire-and-forget actions
  if (!ALLOWED_ACTIONS[action]) {
    return NextResponse.json({ error: "Invalid action" }, { status: 400 })
  }

  const actionConfig = ALLOWED_ACTIONS[action]

  try {
    execFileSync("bash", ["-c", actionConfig.command], { timeout: 5000, encoding: "utf-8" })
    return NextResponse.json({ ok: true, action: actionConfig.description })
  } catch {
    // Background processes will "fail" since they fork — that's expected
    return NextResponse.json({ ok: true, action: actionConfig.description, note: "Triggered in background" })
  }
}
