import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { SERVICE_LOG_PATHS } from "@/lib/constants"
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
  dailyActivity: number[]
}

const SERVICE_LOG_MAP: Record<string, { path: string; successPattern: RegExp; errorPattern: RegExp }> = {
  "founder-scout": {
    path: SERVICE_LOG_PATHS["founder-scout"],
    successPattern: /Scan complete|Email sent|WhatsApp sent/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "email-to-deal": {
    path: SERVICE_LOG_PATHS["email-to-deal"],
    successPattern: /Created deal|Processed|Processing complete/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "meeting-reminders": {
    path: SERVICE_LOG_PATHS["meeting-reminders"],
    successPattern: /Sent \d+ notification|Check complete|No upcoming/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "meeting-bot": {
    path: SERVICE_LOG_PATHS["meeting-bot"],
    successPattern: /Joined meeting|Summary sent|No meetings/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "keep-on-radar": {
    path: SERVICE_LOG_PATHS["keep-on-radar"],
    successPattern: /deals reviewed|reply check complete/i,
    errorPattern: /Error|FAIL|Exception/i,
  },
  "whatsapp-watchdog": {
    path: SERVICE_LOG_PATHS["whatsapp-watchdog"],
    successPattern: /OK|healthy|connected/i,
    errorPattern: /FAIL|RECOVERED|disconnected/i,
  },
  "health-check": {
    path: SERVICE_LOG_PATHS["health-check"],
    successPattern: /Health check COMPLETE|All.*passed/i,
    errorPattern: /FAIL|not running|disconnected/i,
  },
}

function getServiceHealth(serviceId: string): ServiceHealth {
  const config = SERVICE_LOG_MAP[serviceId]
  const emptyDaily = Array(7).fill(0)
  if (!config) {
    return { serviceId, lastSuccess: null, lastError: null, lastRun: null, status: "unknown", recentErrors: 0, dailyActivity: emptyDaily }
  }

  try {
    const lines = execSync(`tail -n 500 "${config.path}" 2>/dev/null || true`, {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n").filter((l) => l.trim())

    let lastSuccess: string | null = null
    let lastError: string | null = null
    let recentErrors = 0
    const oneDayAgo = new Date()
    oneDayAgo.setDate(oneDayAgo.getDate() - 1)

    // Track daily success counts for last 7 days
    const dailyActivity = Array(7).fill(0)
    const now = new Date()

    for (const line of lines) {
      const tsMatch = line.match(/\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*)\]/)
      const timestamp = tsMatch ? new Date(tsMatch[1].replace(" ", "T") + (tsMatch[1].endsWith("Z") ? "" : "Z")).toISOString() : null

      if (config.successPattern.test(line) && timestamp) {
        if (!lastSuccess || timestamp > lastSuccess) lastSuccess = timestamp
        // Bucket into daily activity
        const daysAgo = Math.floor((now.getTime() - new Date(timestamp).getTime()) / (1000 * 60 * 60 * 24))
        if (daysAgo >= 0 && daysAgo < 7) {
          dailyActivity[6 - daysAgo]++
        }
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

    return { serviceId, lastSuccess, lastError, lastRun, status, recentErrors, dailyActivity }
  } catch {
    return { serviceId, lastSuccess: null, lastError: null, lastRun: null, status: "unknown", recentErrors: 0, dailyActivity: emptyDaily }
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
