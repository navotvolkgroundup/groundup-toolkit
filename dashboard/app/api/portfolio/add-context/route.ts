import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { hubspotCreateObject, hubspotCreateAssociation } from "@/lib/hubspot"
import { execFileSync } from "child_process"
import { writeFileSync, readFileSync, unlinkSync } from "fs"

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY

// SECURITY FIX (H-1): Add rate limiting (was missing)
const limiter = rateLimit({ interval: 60_000, limit: 5 })

export async function POST(request: NextRequest) {
  const { ok } = await limiter.check(request)
  if (!ok) return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const data = await request.json()
  const { companyName, companyId, type, content, url, file, fileName } = data

  if (!companyName || !type) {
    return NextResponse.json({ error: "Missing required fields" }, { status: 400 })
  }

  try {
    const sourceLabel: Record<string, string> = { email: "Email Update", whatsapp: "WhatsApp", granola: "Meeting Notes", deck: "Board Deck" }
    const label = sourceLabel[type] || "Update"

    let extractionContent = content || ""

    // For deck uploads, extract PDF text first
    if (type === "deck" && file) {
      const base64Data = file.split(",")[1] || file
      const tmpPdfPath = `/tmp/deck_${Date.now()}.pdf`
      const tmpTextPath = `/tmp/deck_${Date.now()}.txt`

      try {
        writeFileSync(tmpPdfPath, Buffer.from(base64Data, "base64"))

        // SECURITY FIX (M-2): Use execFileSync with argument array instead of inline Python template.
        // Previously, tmpPdfPath was interpolated into a Python code string.
        execFileSync(
          "python3",
          ["-c", `import sys; import pdfplumber\nwith pdfplumber.open(sys.argv[1]) as pdf:\n    text = '\\n'.join(page.extract_text() or '' for page in pdf.pages)\nwith open(sys.argv[2], 'w') as f:\n    f.write(text[:50000])`, tmpPdfPath, tmpTextPath],
          { timeout: 30000 }
        )

        extractionContent = readFileSync(tmpTextPath, "utf-8")
      } catch (pdfErr) {
        console.error("PDF extraction failed:", pdfErr)
        extractionContent = `[PDF uploaded: ${fileName || "board_deck.pdf"} - text extraction failed]`
      } finally {
        try { unlinkSync(tmpPdfPath) } catch {}
        try { unlinkSync(tmpTextPath) } catch {}
      }
    }

    const extractionPrompt = type === "deck"
      ? `Analyze this board deck / investor update for ${companyName}.

DOCUMENT CONTENT:
${extractionContent.slice(0, 30000)}

Extract and return JSON:
{
  "health": "GREEN|YELLOW|RED",
  "summary": "2-3 sentence summary of key takeaways",
  "arr": "value or N/A",
  "mrr": "value or N/A",
  "mom_growth": "value or N/A",
  "runway": "value or N/A",
  "headcount": "value or N/A",
  "burn_rate": "value or N/A",
  "good_news": ["bullet1", "bullet2"],
  "red_flags": ["bullet1"]
}
Use N/A for metrics not found in the document.`
      : `Extract portfolio monitoring metrics from this ${label} for ${companyName}:\n\n${extractionContent}\n\nReturn JSON with: health (GREEN/YELLOW/RED), summary (2-3 sentences), arr, mrr, mom_growth, runway, headcount, good_news (array), red_flags (array). Use N/A for unknown fields.`

    const aiRes = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY!, "anthropic-version": "2023-06-01" },
      body: JSON.stringify({ model: "claude-haiku-4-5-20251001", max_tokens: 500, messages: [{ role: "user", content: extractionPrompt }] }),
    })
    const aiData = await aiRes.json()
    const aiText = aiData.content?.[0]?.text || "{}"

    let metrics: any = {}
    try {
      const jsonMatch = aiText.match(/\{[\s\S]*\}/)
      if (jsonMatch) metrics = JSON.parse(jsonMatch[0])
    } catch { /* fallback */ }

    const now = new Date()
    const dateStr = now.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    const noteBody = [
      `PORTFOLIO UPDATE: ${companyName}`,
      `Date: ${dateStr}`,
      `Health: ${metrics.health || "GREEN"}`,
      `Summary: ${metrics.summary || "Manual context added via dashboard."}`,
      `ARR: ${metrics.arr || "N/A"}`, `MRR: ${metrics.mrr || "N/A"}`,
      `MoM Growth: ${metrics.mom_growth || "N/A"}`, `Runway: ${metrics.runway || "N/A"}`, `Headcount: ${metrics.headcount || "N/A"}`,
      `Good news:`, ...(metrics.good_news || []).map((g: string) => `+ ${g}`),
      `RED FLAGS:`, ...(metrics.red_flags || []).map((r: string) => `\u26a0 ${r}`),
      `Suggested actions:`, `\u2192 Review manually`,
      `\u2500\u2500\u2500`, `Source: ${label}`, `Logged by Christina (AI) \u2014 ${label}`,
    ].join("\n")

    const noteData = await hubspotCreateObject("notes", {
      hs_note_body: noteBody,
      hs_timestamp: now.getTime().toString(),
    })
    const noteId = noteData?.id

    if (companyId && noteId) {
      await hubspotCreateAssociation("notes", noteId, "companies", companyId, "202")
    }

    return NextResponse.json({ success: true, noteId, health: metrics.health })
  } catch (err: any) {
    console.error("Add context error:", err)
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}
