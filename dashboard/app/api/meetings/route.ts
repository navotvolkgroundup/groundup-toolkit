import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execSync } from "child_process"
import { withFreshness } from "@/lib/withFreshness"

const limiter = rateLimit({ interval: 60_000, limit: 20 })

interface Meeting {
  id: string
  title: string
  start: string
  end: string
  attendees: string[]
  company: string | null
}

function parseMeetingLogs(): Meeting[] {
  const meetings: Meeting[] = []

  try {
    // Check meeting-reminders log for upcoming meetings
    const lines = execSync('tail -n 200 /var/log/meeting-reminders.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n")

    const now = new Date()
    const tomorrow = new Date(now)
    tomorrow.setDate(tomorrow.getDate() + 2)
    tomorrow.setHours(23, 59, 59, 999)

    for (const line of lines) {
      // Pattern: "Meeting: Title | 2026-03-07 10:00 | attendee1, attendee2"
      const meetingMatch = line.match(/Meeting:\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}[^|]*)\|?\s*(.*)/)
      if (meetingMatch) {
        const start = new Date(meetingMatch[2].trim().replace(" ", "T"))
        if (start >= now && start <= tomorrow) {
          const title = meetingMatch[1].trim()
          const attendeesStr = meetingMatch[3] || ""
          const attendees = attendeesStr.split(",").map((a) => a.trim()).filter(Boolean)

          // Try to extract company from title
          let company: string | null = null
          const companyMatch = title.match(/(?:with|@|-)?\s*([A-Z][A-Za-z0-9.]+(?:\s+[A-Z][A-Za-z0-9.]+)?)\s*(?:call|meeting|sync|intro|chat)?$/i)
          if (companyMatch) company = companyMatch[1].trim()

          meetings.push({
            id: Math.abs(hashCode(title + meetingMatch[2])).toString(36),
            title,
            start: start.toISOString(),
            end: new Date(start.getTime() + 30 * 60000).toISOString(),
            attendees,
            company,
          })
        }
      }

      // Also parse: "Upcoming: Title at 10:00 AM (in 2h)" format
      const upcomingMatch = line.match(/Upcoming:\s*(.+?)\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)/i)
      if (upcomingMatch) {
        const tsMatch = line.match(/\[(\d{4}-\d{2}-\d{2})/)
        if (tsMatch) {
          const dateStr = tsMatch[1]
          const title = upcomingMatch[1].trim()

          meetings.push({
            id: Math.abs(hashCode(title + dateStr)).toString(36),
            title,
            start: `${dateStr}T12:00:00Z`,
            end: `${dateStr}T12:30:00Z`,
            attendees: [],
            company: null,
          })
        }
      }
    }

    // Also check meeting-auto-join log for scheduled meetings
    const autoJoinLines = execSync('tail -n 100 /var/log/meeting-auto-join.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n")

    for (const line of autoJoinLines) {
      // "Next meeting: Title at 2026-03-07 10:00"
      const nextMatch = line.match(/Next meeting:\s*(.+?)\s+at\s+(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})/)
      if (nextMatch) {
        const start = new Date(nextMatch[2].trim().replace(" ", "T") + "Z")
        if (start >= now && start <= tomorrow) {
          meetings.push({
            id: Math.abs(hashCode(nextMatch[1] + nextMatch[2])).toString(36),
            title: nextMatch[1].trim(),
            start: start.toISOString(),
            end: new Date(start.getTime() + 30 * 60000).toISOString(),
            attendees: [],
            company: null,
          })
        }
      }
    }
  } catch {
    // Ignore errors
  }

  // Deduplicate by title
  const byTitle = new Map<string, Meeting>()
  for (const m of meetings) {
    if (!byTitle.has(m.title)) byTitle.set(m.title, m)
  }

  return Array.from(byTitle.values()).sort((a, b) => a.start.localeCompare(b.start))
}

function hashCode(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0
  }
  return hash
}

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const meetings = parseMeetingLogs()
  return NextResponse.json(withFreshness({ meetings }, null, "log_file"))
}
