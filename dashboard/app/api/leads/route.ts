import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execSync } from "child_process"
import { withFreshness } from "@/lib/withFreshness"

const limiter = rateLimit({ interval: 60_000, limit: 30 })

interface Lead {
  id: number
  name: string
  linkedinUrl: string | null
  signalTier: "high" | "medium" | "low" | null
  lastSignal: string | null
  approached: boolean
  approachedAt: string | null
  hubspotContactId: string | null
  addedAt: string
}

function parseLeads(): Lead[] {
  try {
    const dbResult = execSync(
      `python3 -c "
import sqlite3, json
conn = sqlite3.connect('/root/.openclaw/data/founder-scout.db')
cols = [row[1] for row in conn.execute('PRAGMA table_info(tracked_people)').fetchall()]
has_approached = 'approached' in cols
has_hs = 'hubspot_contact_id' in cols
has_approached_at = 'approached_at' in cols
q = '''SELECT id, name, linkedin_url, signal_tier, last_signal, added_at'''
if has_approached: q += ', approached'
else: q += ', 0'
if has_approached_at: q += ', approached_at'
else: q += ', NULL'
if has_hs: q += ', hubspot_contact_id'
else: q += ', NULL'
q += ''' FROM tracked_people WHERE status = 'active' ORDER BY
  CASE signal_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
  added_at DESC LIMIT 100'''
rows = conn.execute(q).fetchall()
print(json.dumps([dict(id=r[0], name=r[1], linkedin_url=r[2], signal_tier=r[3], last_signal=r[4], added_at=r[5], approached=r[6], approached_at=r[7], hubspot_contact_id=r[8]) for r in rows]))
" 2>/dev/null`,
      { encoding: "utf-8", timeout: 5000 }
    ).trim()

    if (!dbResult) return []

    const rows = JSON.parse(dbResult) as Array<{
      id: number; name: string; linkedin_url: string | null; signal_tier: string | null
      last_signal: string | null; added_at: string; approached: number
      approached_at: string | null; hubspot_contact_id: string | null
    }>

    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      linkedinUrl: r.linkedin_url || null,
      signalTier: (r.signal_tier as Lead["signalTier"]) || null,
      lastSignal: r.last_signal ? r.last_signal.slice(0, 200) : null,
      approached: !!r.approached,
      approachedAt: r.approached_at || null,
      hubspotContactId: r.hubspot_contact_id || null,
      addedAt: r.added_at,
    }))
  } catch {
    return []
  }
}

export async function GET(req: NextRequest) {
  const { ok } = await limiter.check(req)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const leads = parseLeads()
  const stats = {
    total: leads.length,
    approached: leads.filter((l) => l.approached).length,
    high: leads.filter((l) => l.signalTier === "high").length,
    medium: leads.filter((l) => l.signalTier === "medium").length,
    inHubspot: leads.filter((l) => l.hubspotContactId).length,
  }

  return NextResponse.json(withFreshness({ leads, stats }, null, "sqlite"))
}
