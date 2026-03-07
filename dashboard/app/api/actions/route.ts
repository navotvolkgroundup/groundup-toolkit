import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 10 })

const ALLOWED_ACTIONS: Record<string, { command: string; description: string }> = {
  "founder-scout-scan": {
    command: ". /root/.env && /root/.openclaw/skills/founder-scout/scout.py scan >> /var/log/founder-scout.log 2>&1 &",
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
}

export async function POST(req: NextRequest) {
  const { ok } = limiter.check(req)
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
  if (typeof action !== "string" || !ALLOWED_ACTIONS[action]) {
    return NextResponse.json({ error: "Invalid action" }, { status: 400 })
  }

  const actionConfig = ALLOWED_ACTIONS[action]

  try {
    execSync(actionConfig.command, { timeout: 5000, encoding: "utf-8" })
    return NextResponse.json({ ok: true, action: actionConfig.description })
  } catch {
    // Background processes will "fail" since they fork — that's expected
    return NextResponse.json({ ok: true, action: actionConfig.description, note: "Triggered in background" })
  }
}
