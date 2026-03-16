import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { getCached, setCache, CACHE_TTL } from "@/lib/cache"
import { SERVICE_LOG_PATHS } from "@/lib/constants"
import { execSync } from "child_process"
import { statSync } from "fs"
import type { Notification, NotificationLevel } from "@/lib/types"
import { withFreshness } from "@/lib/withFreshness"

const limiter = rateLimit({ interval: 60_000, limit: 120 })

interface LogSource {
  path: string
  serviceName: string
  serviceIcon: string
  includePatterns: RegExp[]
}

const LOG_SOURCES: LogSource[] = [
  {
    path: SERVICE_LOG_PATHS["whatsapp-watchdog"],
    serviceName: "WhatsApp Watchdog",
    serviceIcon: "Shield",
    includePatterns: [
      /FAIL/i,
      /RECOVERED/i,
      /Send.*failed/i,
      /Restarting/i,
      /Alert sent/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["health-check"],
    serviceName: "System Health Check",
    serviceIcon: "HeartPulse",
    includePatterns: [
      /Health check COMPLETE/i,
      /FAIL:/i,
      /WARN:/i,
      /RECOVERED/i,
      /not running/i,
      /disconnected/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["email-to-deal"],
    serviceName: "Email-to-Deal Logger",
    serviceIcon: "Inbox",
    includePatterns: [
      /Created deal/i,
      /Created company/i,
      /Assigned deal/i,
      /Sent confirmation/i,
      /new WhatsApp/i,
      /Error|FAIL/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["founder-scout"],
    serviceName: "Founder Scout",
    serviceIcon: "Radar",
    includePatterns: [
      /Scan complete/i,
      /relevant profile/i,
      /Email sent/i,
      /WhatsApp sent/i,
      /Signal detected/i,
      /Error|FAIL/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["keep-on-radar"],
    serviceName: "Keep on Radar",
    serviceIcon: "Eye",
    includePatterns: [
      /deals reviewed/i,
      /Reply processed/i,
      /reply check complete/i,
      /Error|FAIL/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["meeting-reminders"],
    serviceName: "Smart Meeting Briefs",
    serviceIcon: "CalendarClock",
    includePatterns: [
      /Sent \d+ notification/i,
      /WhatsApp failed/i,
      /Email fallback/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["meeting-bot"],
    serviceName: "Meeting Bot",
    serviceIcon: "Video",
    includePatterns: [
      /Joined meeting/i,
      /Recording/i,
      /Transcript/i,
      /Summary sent/i,
      /Action items/i,
      /Error|FAIL/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["meeting-auto-join"],
    serviceName: "Meeting Bot",
    serviceIcon: "Video",
    includePatterns: [
      /Joining.*meet/i,
      /Error|FAIL/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["christina"],
    serviceName: "Christina Processor",
    serviceIcon: "BrainCircuit",
    includePatterns: [
      /Processing:/i,
      /Detected/i,
      /Archived/i,
      /Error|FAIL/i,
    ],
  },
  {
    path: SERVICE_LOG_PATHS["daily-maintenance"],
    serviceName: "Daily Maintenance",
    serviceIcon: "Settings",
    includePatterns: [
      /UPDATED/i,
      /upgrade complete/i,
      /FAIL/i,
      /maintenance complete/i,
      /Reboot required/i,
    ],
  },
]

// Timestamp patterns found in actual logs
const TIMESTAMP_PATTERNS = [
  // [2026-03-05T19:50:01Z]
  /^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)\]/,
  // [2026-03-05 18:30:01.692983]
  /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]/,
  // [2026-03-05 20:00:01]
  /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]/,
]

function parseTimestamp(line: string): string | null {
  for (const pattern of TIMESTAMP_PATTERNS) {
    const match = line.match(pattern)
    if (match) {
      const raw = match[1]
      try {
        return new Date(raw.replace(" ", "T") + (raw.endsWith("Z") ? "" : "Z")).toISOString()
      } catch {
        return null
      }
    }
  }
  return null
}

function classifyLevel(line: string): NotificationLevel {
  const l = line.toUpperCase()
  if (l.includes("FAIL") || l.includes("ERROR") || l.includes("CRITICAL") || l.includes("DOWN"))
    return "error"
  if (l.includes("WARN") || l.includes("DEGRADED"))
    return "warning"
  if (l.includes("OK") || l.includes("PASSED") || l.includes("RECOVERED") || l.includes("HEALTHY") || l.includes("COMPLETE") || l.includes("SENT") || l.includes("CREATED"))
    return "success"
  return "info"
}

function cleanMessage(line: string): string {
  // Strip timestamp brackets
  let msg = line.replace(/^\[\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]\s*/, "")
  // Strip service name prefix (e.g. "WhatsApp Watchdog: ", "Daily Maintenance: ")
  msg = msg.replace(/^[A-Za-z ]+:\s*/, "")
  // Strip leading emoji
  msg = msg.replace(/^[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}✅❌⚠️ℹ️🔍🤖]+\s*/u, "")
  // Trim whitespace
  msg = msg.trim()
  // Capitalize first letter
  if (msg.length > 0) msg = msg[0].toUpperCase() + msg.slice(1)
  return msg
}

function simpleHash(str: string): string {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0
  }
  return Math.abs(hash).toString(36)
}

function readLastLines(filePath: string, count: number): string[] {
  try {
    const output = execSync(`tail -n ${count} "${filePath}"`, {
      encoding: "utf-8",
      timeout: 3000,
    })
    return output.split("\n").filter((l) => l.trim().length > 0)
  } catch {
    return []
  }
}

function getFileMtime(filePath: string): string | null {
  try {
    return statSync(filePath).mtime.toISOString()
  } catch {
    return null
  }
}

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) {
    return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })
  }

  const session = await auth()
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const cacheKey = "notifications:parsed"
  const cached = getCached<Notification[]>(cacheKey)
  if (cached) {
    return NextResponse.json(withFreshness({ notifications: cached, timestamp: new Date().toISOString() }, null, "log_file", 3600, true))
  }

  const notifications: Notification[] = []

  for (const source of LOG_SOURCES) {
    const lines = readLastLines(source.path, 100)
    const fileMtime = getFileMtime(source.path)

    for (const line of lines) {
      const matches = source.includePatterns.some((p) => p.test(line))
      if (!matches) continue

      const timestamp = parseTimestamp(line) || fileMtime || new Date().toISOString()
      const message = cleanMessage(line)
      if (message.length < 5) continue

      notifications.push({
        id: simpleHash(source.serviceName + timestamp + message),
        serviceName: source.serviceName,
        serviceIcon: source.serviceIcon,
        message,
        level: classifyLevel(line),
        timestamp,
        read: false,
      })
    }
  }

  // Sort by timestamp descending, take top 50
  notifications.sort((a, b) => b.timestamp.localeCompare(a.timestamp))
  const result = notifications.slice(0, 50)

  setCache(cacheKey, result, CACHE_TTL)

  return NextResponse.json(withFreshness({ notifications: result, timestamp: new Date().toISOString() }, null, "log_file"))
}
