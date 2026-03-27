import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotPost, hubspotGetAssociations } from "@/lib/hubspot"
import { notesCache } from "../route"
import { readFileSync } from "fs"
import { join } from "path"

const limiter = rateLimit({ interval: 60_000, limit: 30 })
const NOTES_CACHE_TTL = 15 * 60 * 1000

type RawNote = { id: string; properties: { hs_note_body?: string; hs_timestamp?: string } }

type PortfolioCompany = { name: string; domain: string; fund: "I" | "II" }
const PORTFOLIO_JSON_PATH = join(process.cwd(), "..", "data", "portfolio-companies.json")

function loadPortfolioCompanies(): PortfolioCompany[] {
  return JSON.parse(readFileSync(PORTFOLIO_JSON_PATH, "utf-8")) as PortfolioCompany[]
}

function formatDate(ts: string | undefined, body: string): string | null {
  // Prefer Date: field in note body
  const m = body.match(/^Date:\s*(.+)$/m)
  if (m) {
    const d = new Date(m[1].trim())
    if (!isNaN(d.getTime())) {
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    }
    if (/[A-Za-z]/.test(m[1])) return m[1].trim()
  }
  if (!ts) return null
  const ms = isNaN(Number(ts)) ? new Date(ts).getTime() : Number(ts)
  return isNaN(ms) ? null : new Date(ms).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ name: string }> }) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { name } = await params
  const companyName = decodeURIComponent(name)

  // Validate company exists in portfolio
  const allCompanies = loadPortfolioCompanies()
  const company = allCompanies.find(c => c.name.toLowerCase() === companyName.toLowerCase())
  if (!company) {
    return NextResponse.json({ notes: [], touchpoints30d: 0, analysis: "" })
  }

  // Fetch all PORTFOLIO UPDATE notes (reuse shared cache)
  let notes: RawNote[] = []
  if (Date.now() - notesCache.ts < NOTES_CACHE_TTL && notesCache.notes.length > 0) {
    notes = notesCache.notes
  } else {
    const noteSearch = await hubspotPost("/crm/v3/objects/notes/search", {
      filterGroups: [{ filters: [{ propertyName: "hs_note_body", operator: "CONTAINS_TOKEN", value: "PORTFOLIO UPDATE" }] }],
      properties: ["hs_note_body", "hs_timestamp"],
      limit: 100,
    }) as { results?: RawNote[] } | null
    notes = noteSearch?.results ?? []
    if (notes.length > 0) { notesCache.notes = notes; notesCache.ts = Date.now() }
  }

  // Find notes associated with this company by matching company name in note body
  // (More reliable than association lookup since there can be duplicate company records)
  const companyNotes: { id: string; body: string; date: string | null; ts: number }[] = []
  const thirtyDaysAgo = Date.now() - 30 * 24 * 60 * 60 * 1000

  for (const note of notes) {
    const body = note.properties.hs_note_body ?? ""
    // Match "PORTFOLIO UPDATE: CompanyName" at the start of the note
    const headerMatch = body.match(/^PORTFOLIO UPDATE:\s*(.+?)[\s—\-]+/m)
    if (!headerMatch) continue

    const noteName = headerMatch[1].trim().toLowerCase()
    if (noteName !== company.name.toLowerCase()) continue

    const raw = note.properties.hs_timestamp
    const ts = raw ? (isNaN(Number(raw)) ? new Date(raw).getTime() : Number(raw)) : Date.now()
    companyNotes.push({
      id: note.id,
      body,
      date: formatDate(note.properties.hs_timestamp, body),
      ts,
    })
  }

  // Sort newest first
  companyNotes.sort((a, b) => b.ts - a.ts)

  const touchpoints30d = companyNotes.filter(n => n.ts >= thirtyDaysAgo).length

  // Use the latest note's summary as analysis
  const latestBody = companyNotes[0]?.body ?? ""
  const summaryMatch = latestBody.match(/^Summary:\s*(.+)$/m)
  const analysis = summaryMatch ? summaryMatch[1].trim() : ""

  return NextResponse.json({
    notes: companyNotes.map(n => ({ id: n.id, body: n.body, date: n.date })),
    touchpoints30d,
    analysis,
  })
}
