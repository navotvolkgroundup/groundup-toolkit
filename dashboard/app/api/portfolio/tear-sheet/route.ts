import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@/lib/auth'
import { rateLimit } from '@/lib/rate-limit'
import { execSync } from 'child_process'
import { writeFileSync, readFileSync, unlinkSync } from 'fs'

// SECURITY FIX (H-1): Add rate limiting (was missing)
const limiter = rateLimit({ interval: 60_000, limit: 5 })

export async function POST(request: NextRequest) {
  const { ok } = await limiter.check(request)
  if (!ok) return NextResponse.json({ error: 'Too Many Requests' }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { companyName, description, investments, fund, health, metrics } = await request.json()

  if (!companyName) {
    return NextResponse.json({ error: 'Missing company name' }, { status: 400 })
  }

  try {
    const dataPath = `/tmp/tearsheet_${Date.now()}.json`
    const outPath = `/tmp/tearsheet_${Date.now()}.pdf`

    writeFileSync(dataPath, JSON.stringify({
      companyName,
      description: description || '',
      fund: fund || '',
      health: health || '',
      metrics: metrics || {},
      investments: investments || [],
    }))

    execSync(
      `python3 /root/.openclaw/scripts/generate_tearsheet.py "${dataPath}" "${outPath}"`,
      { timeout: 30000 }
    )

    const pdfBuffer = readFileSync(outPath)

    try { unlinkSync(dataPath) } catch {}
    try { unlinkSync(outPath) } catch {}

    return new NextResponse(pdfBuffer, {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': `attachment; filename="${companyName.replace(/[^a-zA-Z0-9]/g, '_')}_Tear_Sheet.pdf"`,
      },
    })
  } catch (err: any) {
    console.error('Tear sheet error:', err)
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}
