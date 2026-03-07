import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execSync } from "child_process"
import { statSync } from "fs"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

interface ServiceHealth {
  serviceId: string
  lastSuccess: string | null
  lastError: string | null
  lastRun: string | null
  status: "healthy" | "warning" | "error" | "unknown"
  recentErrors: number
}

const SERVICE_LOG_MAP: Record<string, { path: string; successPattern: RegExp; errorPattern: RegExp }> = {
  "founder-scout": {
    path: "/var/log/founder-scout.log",
    successPattern: /Scan complete|Email sent|WhatsApp sent/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "email-to-deal": {
    path: "/var/log/deal-automation.log",
    successPattern: /Created deal|Processed|Processing complete/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "meeting-reminders": {
    path: "/var/log/meeting-reminders.log",
    successPattern: /Sent \d+ notification|Check complete|No upcoming/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "meeting-bot": {
    path: "/var/log/meeting-bot.log",
    successPattern: /Joined meeting|Summary sent|No meetings/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "keep-on-radar": {
    path: "/var/log/keep-on-radar.log",
    successPattern: /deals reviewed|reply check complete/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "whatsapp-watchdog": {
    path: "/var/log/whatsapp-watchdog.log",
    successPattern: /OK|healthy|connected/i,
    errorPattern: /FAIL|RECOVERED|disconnected/i,
  },
  "health-check": {
    path: "/var/log/openclaw-health.log",
    successPattern: /Health check COMPLETE|All.*passed/i,
    errorPattern: /FAIL|not running|disconnected/i,
  },
}

function getServiceHealth(serviceId: string): ServiceHealth {
  const config = SERVICE_LOG_MAP[serviceId]
  if (!config) {
    return { serviceId, lastSuccess: null, lastError: null, lastRun: null, status: "unknown", recentErrors: 0 }
  }

  try {
    const lines = execSync(`tail -n 200 "${config.path}" 2>/dev/null || true`, {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n").filter((l) => l.trim())

    let lastSuccess: string | null = null
    let lastError: string | null = null
    let recentErrors = 0
    const oneDayAgo = new Date()
    oneDayAgo.setDate(oneDayAgo.getDate() - 1)

    for (const line of lines) {
      const tsMatch = line.match(/\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*)\]/)
      const timestamp = tsMatch ? new Date(tsMatch[1].replace(" ", "T") + (tsMatch[1].endsWith("Z") ? "" : "Z")).toISOString() : null

      if (config.successPattern.test(line) && timestamp) {
        if (!lastSuccess || timestamp > lastSuccess) lastSuccess = timestamp
      }
      if (config.errorPattern.test(line)) {
        if (timestamp) {
          if (!lastError || timestamp > lastError) lastError = timestamp
          if (new Date(timestamp) > oneDayAgo) recentErrors++
        }
      }
    }

    // Determine status
    let lastRun: string | null = null
    try {
      lastRun = statSync(config.path).mtime.toISOString()
    } catch { /* ignore */ }

    let status: ServiceHealth["status"] = "healthy"
    if (lastRun) {
      const mtime = new Date(lastRun)
      const hoursAgo = (Date.now() - mtime.getTime()) / (1000 * 60 * 60)
      if (hoursAgo > 24) status = "warning"
      if (hoursAgo > 48) status = "error"
    }
    if (recentErrors > 3) status = "warning"
    if (recentErrors > 10) status = "error"
    if (lastError && lastSuccess && lastError > lastSuccess) status = "warning"

    return { serviceId, lastSuccess, lastError, lastRun, status, recentErrors }
  } catch {
    return { serviceId, lastSuccess: null, lastError: null, lastRun: null, status: "unknown", recentErrors: 0 }
  }
}

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const healthData: Record<string, ServiceHealth> = {}
  for (const serviceId of Object.keys(SERVICE_LOG_MAP)) {
    healthData[serviceId] = getServiceHealth(serviceId)
  }

  return NextResponse.json({ services: healthData })
}
