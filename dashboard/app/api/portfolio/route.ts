import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { readFileSync } from "fs"
import { join } from "path"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

const MATON_API_KEY = process.env.MATON_API_KEY!
const BASE = "https://gateway.maton.ai/hubspot"
const HEADERS = {
  Authorization: `Bearer ${MATON_API_KEY}`,
  "Content-Type": "application/json",
}

const CACHE_TTL_MS = 15 * 60 * 1000
let _cache: { data: unknown; ts: number } | null = null

// Shared notes cache — reused by per-company route to avoid duplicate searches
export const notesCache: { notes: RawNote[]; ts: number } = { notes: [], ts: 0 }
const NOTES_CACHE_TTL = 15 * 60 * 1000

type RawNote = { id: string; properties: { hs_note_body?: string; hs_timestamp?: string } }

// Load portfolio companies from the single-source-of-truth JSON file
type PortfolioCompany = { name: string; domain: string; fund: "I" | "II" }
const PORTFOLIO_JSON_PATH = join(process.cwd(), "..", "data", "portfolio-companies.json")

function loadPortfolioCompanies(): PortfolioCompany[] {
  const raw = readFileSync(PORTFOLIO_JSON_PATH, "utf-8")
  return JSON.parse(raw) as PortfolioCompany[]
}

const ALL_COMPANIES = loadPortfolioCompanies()

// Build lookup: normalized name → company definition
const NAME_MAP = new Map(
  ALL_COMPANIES.map((c) => [c.name.toLowerCase(), c])
)

async function hsFetch(method: "GET" | "POST", path: string, body?: unknown, retries = 3): Promise<Record<string, unknown> | null> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(`${BASE}${path}`, {
        method,
        headers: HEADERS,
        body: body ? JSON.stringify(body) : undefined,
        cache: "no-store",
      })
      if (res.status === 429) {
        const wait = Math.pow(2, attempt) * 1000 // 1s, 2s, 4s
        console.log(`[portfolio] 429 on ${path}, waiting ${wait}ms (attempt ${attempt + 1}/${retries})`)
        await new Promise((r) => setTimeout(r, wait))
        continue
      }
      if (!res.ok) { console.error(`hs${method} ${path} → ${res.status}`); return null }
      return res.json()
    } catch (e) {
      console.error(`hs${method} ${path} error:`, e)
      return null
    }
  }
  return null
}

const hsPost = (path: string, body: unknown) => hsFetch("POST", path, body)
const hsGet  = (path: string)               => hsFetch("GET",  path)

function parseHealth(body: string): "GREEN" | "YELLOW" | "RED" | null {
  const m = body.match(/Health:\s*(GREEN|YELLOW|RED)/i)
  return m ? (m[1].toUpperCase() as "GREEN" | "YELLOW" | "RED") : null
}

function parseMetric(body: string, key: string): string | null {
  const m = body.match(new RegExp(`${key}:\\s*(.+)`, "i"))
  return m ? m[1].split("\n")[0].trim() : null
}

function parseList(body: string, section: string): string[] {
  const m = body.match(new RegExp(`${section}:[\\s\\S]*?(?=\\n[A-Za-z ]+:|\\n---|$)`, "i"))
  if (!m) return []
  return m[0].split("\n").slice(1)
    .map((l) => l.replace(/^\s*[+\-•⚠→]\s*/, "").trim())
    .filter((l) => l.length > 0 && l.length < 200)
    .slice(0, 3)
}

function parseDate(ts: string | undefined): string | null {
  if (!ts) return null
  return new Date(Number(ts)).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

function parseDateFromBody(body: string, ts: string | undefined): string | null {
  // Prefer the Date: field in the note body (original communication date)
  const m = body.match(/^Date:\s*(.+)$/m)
  if (m) {
    const d = new Date(m[1].trim())
    if (!isNaN(d.getTime())) {
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    }
    // Return as-is if it's already formatted (e.g. "Mar 09, 2026")
    if (/[A-Za-z]/.test(m[1])) return m[1].trim()
  }
  return parseDate(ts)
}

async function fetchPortfolioData() {
  console.log("[portfolio] fetchPortfolioData starting, key present:", !!MATON_API_KEY)
  // ── Step 1: Search all portfolio update notes (with shared cache) ──────
  let notes: RawNote[] = []
  if (Date.now() - notesCache.ts < NOTES_CACHE_TTL && notesCache.notes.length > 0) {
    notes = notesCache.notes
    console.log(`[portfolio] notes from cache: ${notes.length}`)
  } else {
    const noteSearch = await hsPost("/crm/v3/objects/notes/search", {
      filterGroups: [{ filters: [{ propertyName: "hs_note_body", operator: "CONTAINS_TOKEN", value: "PORTFOLIO UPDATE" }] }],
      properties: ["hs_note_body", "hs_timestamp"],
      limit: 100,
    }) as { results?: RawNote[] } | null
    notes = noteSearch?.results ?? []
    if (notes.length > 0) { notesCache.notes = notes; notesCache.ts = Date.now() }
    console.log(`[portfolio] notes fetched: ${notes.length}`)
  }

  // ── Step 2: For each note get its associated company ID (v3, serial) ───
  type CompanyAssocV3 = { results?: { id: string; type: string }[] }
  const noteToCompany = new Map<string, string>() // noteId → companyId

  for (const note of notes) {
    const assoc = await hsGet(
      `/crm/v3/objects/notes/${note.id}/associations/companies`
    ) as CompanyAssocV3 | null
    const cid = assoc?.results?.[0]?.id
    if (cid) noteToCompany.set(note.id, cid)
  }
  console.log(`[portfolio] noteToCompany size: ${noteToCompany.size}`)

  // ── Step 3: Get company names for all associated company IDs ───────────
  const companyIds = [...new Set(noteToCompany.values())]
  console.log(`[portfolio] company IDs from notes: ${JSON.stringify(companyIds)}`)
  type CompanyResult = { id: string; properties: { name?: string } }
  const companyMap = new Map<string, string>() // companyId → name

  if (companyIds.length > 0) {
    console.log(`[portfolio] batch reading ${companyIds.length} companies...`)
    const chunks = []
    for (let i = 0; i < companyIds.length; i += 100) chunks.push(companyIds.slice(i, i + 100))
    for (const chunk of chunks) {
      const data = await hsPost("/crm/v3/objects/companies/batch/read", {
        inputs: chunk.map((id) => ({ id })),
        properties: ["name"],
      }) as { results?: CompanyResult[] } | null
      console.log(`[portfolio] batch chunk returned ${data?.results?.length ?? 0} results`)
      data?.results?.forEach((r) => companyMap.set(r.id, r.properties.name ?? ""))
    }
    console.log(`[portfolio] companyMap size: ${companyMap.size}`)
  }

  // ── Step 4: Build company → latest note mapping ───────────────────────
  type NoteSummary = {
    body: string; ts: string | undefined; updateCount: number
  }
  const companyNotes = new Map<string, NoteSummary>()

  for (const note of notes) {
    const cid = noteToCompany.get(note.id)
    if (!cid) continue
    const existing = companyNotes.get(cid)
    const ts = note.properties.hs_timestamp
    if (!existing || Number(ts) > Number(existing.ts ?? 0)) {
      companyNotes.set(cid, {
        body: note.properties.hs_note_body ?? "",
        ts,
        updateCount: (existing?.updateCount ?? 0) + 1,
      })
    } else {
      // Just increment count
      if (existing) existing.updateCount++
    }
  }

  // ── Step 5: Build final result list ───────────────────────────────────
  const results = ALL_COMPANIES.map((co) => {
    // Find the HubSpot company ID by matching name
    let matchedCid: string | null = null
    for (const [cid, name] of companyMap) {
      if (name.toLowerCase() === co.name.toLowerCase()) {
        matchedCid = cid; break
      }
    }

    const noteData = matchedCid ? companyNotes.get(matchedCid) : null

    if (noteData) {
      const body = noteData.body
      return {
        name: co.name,
        domain: co.domain,
        fund: co.fund,
        companyId: matchedCid,
        health: parseHealth(body),
        lastUpdate: parseDateFromBody(noteData.body, noteData.ts),
        summary: parseMetric(body, "Summary"),
        metrics: {
          arr: parseMetric(body, "ARR"),
          mrr: parseMetric(body, "MRR"),
          runway: parseMetric(body, "Runway"),
          headcount: parseMetric(body, "Headcount"),
          momGrowth: parseMetric(body, "MoM Growth"),
        },
        revenueMetric: (() => {
          const arr = parseMetric(body, "ARR")
          if (arr) return arr
          const mrr = parseMetric(body, "MRR")
          if (mrr) return mrr
          // Fallback: find first dollar amount in the summary line
          const summaryLine = body.split("\n").find(l => /^Summary:/i.test(l)) ?? ""
          const m = summaryLine.match(/\$[\d,.]+[KMBkmb]?(?:\s*(?:ARR|MRR|revenue|ARR\/yr))?/)
          return m ? m[0] : null
        })(),
        redFlags: parseList(body, "RED FLAGS"),
        goodNews: parseList(body, "Good news"),
        updateCount: noteData.updateCount,
      }
    }

    return {
      name: co.name,
      domain: co.domain,
      fund: co.fund,
      companyId: matchedCid,
      health: null,
      lastUpdate: null,
      summary: null,
      metrics: { arr: null, mrr: null, runway: null, headcount: null, momGrowth: null },
      revenueMetric: null,
      redFlags: [],
      goodNews: [],
      updateCount: 0,
    }
  })

  // Alphabetical
  results.sort((a, b) => a.name.localeCompare(b.name))
  const withData = results.filter(r => r.health !== null)
  console.log(`[portfolio] results built: ${results.length} total, ${withData.length} with data (${withData.map(r=>r.name).join(", ")})`)

  const summary = {
    total: results.length,
    green:  results.filter((r) => r.health === "GREEN").length,
    yellow: results.filter((r) => r.health === "YELLOW").length,
    red:    results.filter((r) => r.health === "RED").length,
    noData: results.filter((r) => !r.health).length,
  }

  return { companies: results, summary }
}

export async function GET(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  if (_cache && Date.now() - _cache.ts < CACHE_TTL_MS) {
    return NextResponse.json(_cache.data)
  }

  try {
    const data = await fetchPortfolioData()
    _cache = { data, ts: Date.now() }
    return NextResponse.json(data)
  } catch (e) {
    console.error("Portfolio API error:", e)
    if (_cache) return NextResponse.json(_cache.data)
    return NextResponse.json({
      companies: [...ALL_COMPANIES].sort((a, b) => a.name.localeCompare(b.name)).map((c) => ({
        ...c, health: null, lastUpdate: null, summary: null,
        metrics: {}, redFlags: [], goodNews: [], updateCount: 0,
      })),
      summary: { total: ALL_COMPANIES.length, green: 0, yellow: 0, red: 0, noData: ALL_COMPANIES.length },
    })
  }
}
