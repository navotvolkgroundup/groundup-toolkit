import { NextRequest } from "next/server"
import { auth } from "@/lib/auth"
import { execSync } from "child_process"
import { existsSync, statSync } from "fs"

const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT || "/root/groundup-toolkit"
const SCOUT_DB = process.env.SCOUT_DB || "/root/.openclaw/data/founder-scout.db"

// Polling interval for checking changes (ms)
const POLL_INTERVAL = 10_000

// Log files to watch for status changes
const WATCHED_LOGS: Record<string, string> = {
  "email-to-deal": "/var/log/deal-automation.log",
  "founder-scout": "/var/log/founder-scout.log",
  "meeting-bot": "/var/log/meeting-bot.log",
  "meeting-auto-join": "/var/log/meeting-auto-join.log",
}

function getLogMtimes(): Record<string, number> {
  const mtimes: Record<string, number> = {}
  for (const [name, path] of Object.entries(WATCHED_LOGS)) {
    try {
      if (existsSync(path)) {
        mtimes[name] = statSync(path).mtimeMs
      }
    } catch {
      // ignore
    }
  }
  return mtimes
}

function getSignalCount(): number {
  try {
    const result = execSync(
      `python3 -c "import sqlite3; conn = sqlite3.connect('${SCOUT_DB}'); print(conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = \"active\"').fetchone()[0])" 2>/dev/null`,
      { encoding: "utf-8", timeout: 3000 }
    ).trim()
    return parseInt(result, 10) || 0
  } catch {
    return -1
  }
}

function getLatestSignalTime(): string | null {
  try {
    const result = execSync(
      `python3 -c "import sqlite3; conn = sqlite3.connect('${SCOUT_DB}'); r = conn.execute('SELECT MAX(last_scanned) FROM tracked_people WHERE status = \"active\"').fetchone(); print(r[0] or '')" 2>/dev/null`,
      { encoding: "utf-8", timeout: 3000 }
    ).trim()
    return result || null
  } catch {
    return null
  }
}

export async function GET(req: NextRequest) {
  const session = await auth()
  if (!session) {
    return new Response("Unauthorized", { status: 401 })
  }

  const encoder = new TextEncoder()
  let closed = false

  const stream = new ReadableStream({
    async start(controller) {
      // Send initial state
      const initialData = {
        type: "init",
        signalCount: getSignalCount(),
        latestSignal: getLatestSignalTime(),
        logMtimes: getLogMtimes(),
      }
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(initialData)}\n\n`))

      // Track previous state for change detection
      let prevSignalCount = initialData.signalCount
      let prevLatestSignal = initialData.latestSignal
      let prevLogMtimes = initialData.logMtimes

      const interval = setInterval(() => {
        if (closed) {
          clearInterval(interval)
          return
        }

        try {
          const events: Array<{ type: string; [key: string]: unknown }> = []

          // Check for new signals
          const currentCount = getSignalCount()
          const currentLatest = getLatestSignalTime()

          if (currentCount > prevSignalCount) {
            events.push({
              type: "new_signals",
              count: currentCount - prevSignalCount,
              total: currentCount,
            })
          }

          if (currentLatest && currentLatest !== prevLatestSignal) {
            events.push({
              type: "signal_update",
              latestSignal: currentLatest,
            })
          }

          prevSignalCount = currentCount
          prevLatestSignal = currentLatest

          // Check for log activity
          const currentMtimes = getLogMtimes()
          for (const [name, mtime] of Object.entries(currentMtimes)) {
            if (prevLogMtimes[name] && mtime > prevLogMtimes[name]) {
              events.push({
                type: "service_activity",
                service: name,
                timestamp: new Date(mtime).toISOString(),
              })
            }
          }
          prevLogMtimes = currentMtimes

          // Send events or heartbeat
          if (events.length > 0) {
            for (const event of events) {
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
            }
          } else {
            // Heartbeat every poll cycle to keep connection alive
            controller.enqueue(encoder.encode(`: heartbeat\n\n`))
          }
        } catch {
          // Swallow errors to keep stream alive
        }
      }, POLL_INTERVAL)

      // Handle client disconnect
      req.signal.addEventListener("abort", () => {
        closed = true
        clearInterval(interval)
        controller.close()
      })
    },
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  })
}
