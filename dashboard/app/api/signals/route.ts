import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { withFreshness } from "@/lib/withFreshness"
import { execSync, execFileSync } from "child_process"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

interface Signal {
  id: string
  name: string
  company: string
  signal: string
  strength: "high" | "medium" | "low"
  timestamp: string
  source: string
  linkedinUrl: string | null
  githubUrl: string | null
  approached: boolean
  outcome: string | null
  compositeScore: number | null
  classification: string | null
  thesisMatch: string | null
  introPath: string | null
  scoreTrend: number[]
}

function parseSignals(): Signal[] {
  // Primary: read from founder-scout database (has LinkedIn URLs + scores + enrichment)
  try {
    const dbResult = execSync(
      `python3 -c "
import sqlite3, json, os, sys
conn = sqlite3.connect('/root/.openclaw/data/founder-scout.db')
cols = [row[1] for row in conn.execute('PRAGMA table_info(tracked_people)').fetchall()]
approached_col = ', p.approached' if 'approached' in cols else ', 0'
outcome_col = ', p.outcome' if 'outcome' in cols else ', NULL'
q = 'SELECT p.id, p.name, p.linkedin_url, p.signal_tier, p.last_signal, p.last_scanned, p.headline, p.github_url' + approached_col + outcome_col + ''' FROM tracked_people p WHERE p.status = \\\"active\\\" AND p.last_signal IS NOT NULL ORDER BY p.last_scanned DESC LIMIT 20'''
rows = conn.execute(q).fetchall()
results = []
# Check if person_scores table exists
score_tables = [r[0] for r in conn.execute(\\\"SELECT name FROM sqlite_master WHERE type='table'\\\").fetchall()]
has_scores = 'person_scores' in score_tables
for r in rows:
    d = dict(id=r[0], name=r[1], linkedin_url=r[2], signal_tier=r[3], last_signal=r[4], last_scanned=r[5], headline=r[6], github_url=r[7], approached=r[8], outcome=r[9], composite_score=None, classification=None, score_trend=[])
    if has_scores:
        scores = conn.execute('SELECT composite_score, classification FROM person_scores WHERE person_id = ? ORDER BY calculated_at DESC LIMIT 1', (r[0],)).fetchone()
        if scores:
            d['composite_score'] = scores[0]
            d['classification'] = scores[1]
        trend = conn.execute('SELECT composite_score FROM person_scores WHERE person_id = ? ORDER BY calculated_at DESC LIMIT 4', (r[0],)).fetchall()
        d['score_trend'] = [t[0] for t in reversed(trend)]
    results.append(d)
print(json.dumps(results))
" 2>/dev/null`,
      { encoding: "utf-8", timeout: 5000 }
    ).trim()

    // Enrichment: thesis matching + intro paths (separate call, best-effort)
    let enrichment: Record<string, { thesis: string | null; intro: string | null }> = {}
    try {
      const enrichResult = execSync(
        `python3 -c "
import sqlite3, json, os, sys
sys.path.insert(0, '/root/groundup-toolkit')
sys.path.insert(0, '/root/groundup-toolkit/skills/founder-scout')
conn = sqlite3.connect('/root/.openclaw/data/founder-scout.db')
cols = [row[1] for row in conn.execute('PRAGMA table_info(tracked_people)').fetchall()]
q = 'SELECT id, headline, last_signal, linkedin_url, name FROM tracked_people WHERE status = \\\"active\\\" AND last_signal IS NOT NULL ORDER BY last_scanned DESC LIMIT 20'
rows = conn.execute(q).fetchall()
result = {}
# Thesis matching
try:
    import yaml
    with open('/root/groundup-toolkit/skills/founder-scout/thesis.yaml') as f:
        thesis = yaml.safe_load(f)
    from modules.scoring import apply_thesis_matching
    for r in rows:
        pid = str(r[0])
        profile = (r[1] or '') + ' ' + (r[2] or '')
        _, match = apply_thesis_matching(50, profile, thesis)
        if match and not match.startswith('Anti'):
            result.setdefault(pid, {})['thesis'] = match
except: pass
# Relationship graph
try:
    from lib.relationship_graph import RelationshipGraph
    g = RelationshipGraph()
    for r in rows:
        pid = str(r[0])
        identifier = r[3] or r[4]
        conns = g.get_connections(identifier, limit=2)
        if conns:
            parts = []
            for c in conns[:2]:
                p = c.get('person', {})
                parts.append(p.get('name', '?') + ' (' + c.get('rel_type', '').replace('_', ' ') + ')')
            result.setdefault(pid, {})['intro'] = ', '.join(parts)
except: pass
print(json.dumps(result))
" 2>/dev/null`,
        { encoding: "utf-8", timeout: 5000 }
      ).trim()
      if (enrichResult) enrichment = JSON.parse(enrichResult)
    } catch {
      // Enrichment is best-effort
    }

    if (dbResult) {
      const rows = JSON.parse(dbResult) as Array<{
        id: number; name: string; linkedin_url: string | null; signal_tier: string
        last_signal: string; last_scanned: string; headline: string | null; github_url: string | null
        approached: number; outcome: string | null
        composite_score: number | null; classification: string | null; score_trend: number[]
      }>
      return rows.map((r) => {
        const enrich = enrichment[r.id.toString()] || {}
        return {
          id: r.id.toString(),
          name: r.name,
          company: extractCompany(r.last_signal, r.headline),
          signal: r.last_signal.slice(0, 200),
          strength: (r.signal_tier === "high" ? "high" : r.signal_tier === "medium" ? "medium" : "low") as Signal["strength"],
          timestamp: new Date(r.last_scanned).toISOString(),
          source: r.linkedin_url ? "LinkedIn" : r.github_url ? "GitHub" : "LinkedIn",
          linkedinUrl: r.linkedin_url || null,
          githubUrl: r.github_url || null,
          approached: !!r.approached,
          outcome: r.outcome || null,
          compositeScore: r.composite_score,
          classification: r.classification,
          thesisMatch: enrich.thesis || null,
          introPath: enrich.intro || null,
          scoreTrend: r.score_trend || [],
        }
      })
    }
  } catch {
    // Fall through to log-based parsing
  }

  // Fallback: parse log files (no LinkedIn URLs available)
  const signals: Signal[] = []
  try {
    const lines = execSync('tail -n 500 /var/log/founder-scout.log 2>/dev/null || true', {
      encoding: "utf-8",
      timeout: 3000,
    }).split("\n")

    let currentTimestamp: string | null = null
    let currentVisitName: string | null = null

    for (const line of lines) {
      const tsMatch = line.match(/^\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})/)
      if (tsMatch) {
        currentTimestamp = new Date(tsMatch[1].replace(" ", "T") + "Z").toISOString()
        currentVisitName = null
        continue
      }

      if (!currentTimestamp) continue
      const trimmed = line.trim()

      const visitMatch = trimmed.match(/^\[\d+\/\d+\] Visiting (.+?)\.\.\./)
      if (visitMatch) { currentVisitName = visitMatch[1]; continue }

      const relevantMatch = trimmed.match(/^RELEVANT:\s*(.+)/)
      if (relevantMatch && currentVisitName) {
        const description = relevantMatch[1]
        signals.push({
          id: Math.abs(hashCode(currentVisitName + currentTimestamp)).toString(36),
          name: currentVisitName,
          company: extractCompany(description),
          signal: description.slice(0, 200),
          strength: getStrength(description),
          timestamp: currentTimestamp,
          source: "LinkedIn",
          linkedinUrl: null,
          githubUrl: null,
          approached: false,
          outcome: null,
          compositeScore: null,
          classification: null,
          thesisMatch: null,
          introPath: null,
          scoreTrend: [],
        })
        continue
      }

      const keptMatch = trimmed.match(/^Kept \(positive signal\):\s*(.+?)\s*—\s*(.+)/)
      if (keptMatch) {
        signals.push({
          id: Math.abs(hashCode(keptMatch[1] + currentTimestamp)).toString(36),
          name: keptMatch[1],
          company: extractCompany(keptMatch[2]),
          signal: keptMatch[2].slice(0, 200),
          strength: getStrength(keptMatch[2]),
          timestamp: currentTimestamp,
          source: "LinkedIn",
          linkedinUrl: null,
          githubUrl: null,
          approached: false,
          outcome: null,
          compositeScore: null,
          classification: null,
          thesisMatch: null,
          introPath: null,
          scoreTrend: [],
        })
        continue
      }
    }
  } catch {
    // Ignore errors
  }

  const byName = new Map<string, Signal>()
  for (const s of signals) {
    const existing = byName.get(s.name)
    if (!existing || s.timestamp > existing.timestamp) byName.set(s.name, s)
  }

  return Array.from(byName.values())
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    .slice(0, 20)
}

function extractCompany(text: string, headline?: string | null): string {
  // Try headline first (e.g. "CEO at Everywhen")
  const src = headline || text
  const match = src.match(/(?:at|of|@)\s+(?:a\s+)?([A-Z][A-Za-z0-9.]+(?:\s+[A-Z][A-Za-z0-9.]+)?)/i)
  if (match) return match[1].trim()
  if (/stealth/i.test(src)) return "Stealth"
  // Try text if headline didn't match
  if (headline && text !== headline) {
    const textMatch = text.match(/(?:at|of|@)\s+(?:a\s+)?([A-Z][A-Za-z0-9.]+(?:\s+[A-Z][A-Za-z0-9.]+)?)/i)
    if (textMatch) return textMatch[1].trim()
    if (/stealth/i.test(text)) return "Stealth"
  }
  return ""
}

function getStrength(text: string): Signal["strength"] {
  const lower = text.toLowerCase()
  if (lower.includes("stealth") || lower.includes("founding") || lower.includes("co-founder") || lower.includes("left") || lower.includes("exited")) {
    return "high"
  }
  if (lower.includes("exploring") || lower.includes("open to") || lower.includes("next chapter") || lower.includes("building")) {
    return "medium"
  }
  return "low"
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

  const signals = parseSignals()
  const latestTs = signals.length > 0 ? signals[0].timestamp : null
  return NextResponse.json(withFreshness({ signals }, latestTs, "sqlite", 3600))
}

export async function POST(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  const { signalId, outcome, action } = body as { signalId: string; outcome?: string; action?: string }

  if (!signalId || !/^\d+$/.test(signalId)) {
    return NextResponse.json({ error: "Invalid signalId" }, { status: 400 })
  }

  const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT || "/root/groundup-toolkit"
  const scoutPath = `${TOOLKIT_ROOT}/skills/founder-scout/scout.py`

  try {
    if (action === "approach") {
      execFileSync("python3", [scoutPath, "approach-id", signalId], {
        encoding: "utf-8", timeout: 10000,
      })
      return NextResponse.json({ ok: true, signalId, approached: true })
    }

    const validOutcomes = ["met", "invested", "passed", "noise"]
    if (!outcome || !validOutcomes.includes(outcome)) {
      return NextResponse.json(
        { error: `outcome must be one of: ${validOutcomes.join(", ")}` },
        { status: 400 }
      )
    }

    execFileSync("python3", [scoutPath, "outcome", signalId, outcome], {
      encoding: "utf-8", timeout: 5000,
    })
    return NextResponse.json({ ok: true, signalId, outcome })
  } catch (err) {
    return NextResponse.json({ error: "Action failed" }, { status: 500 })
  }
}
