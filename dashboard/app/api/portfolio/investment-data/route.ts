import { NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { hubspotPost, hubspotCreateObject, hubspotCreateAssociation } from "@/lib/hubspot"

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY

export async function GET(request: Request) {
  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { searchParams } = new URL(request.url)
  const companyName = searchParams.get("company")
  if (!companyName) return NextResponse.json({ error: "Missing company param" }, { status: 400 })

  try {
    const searchData = await hubspotPost("/crm/v3/objects/notes/search", {
      filterGroups: [{ filters: [{ propertyName: "hs_note_body", operator: "CONTAINS_TOKEN", value: "SOI_DATA" }] }],
      properties: ["hs_note_body", "hs_timestamp"], limit: 100,
    }) as { results?: Array<{ id: string; properties: Record<string, string | null> }> } | null
    const results = searchData?.results ?? []

    const investments: any[] = []
    for (const note of results) {
      const body = note.properties?.hs_note_body || ""
      if (!body.includes(`SOI_DATA: ${companyName}`)) continue
      try {
        const jsonStr = body.split("SOI_JSON:")[1]?.trim()
        if (jsonStr) {
          const parsed = JSON.parse(jsonStr)
          investments.push(...(Array.isArray(parsed) ? parsed : [parsed]))
        }
      } catch { /* skip */ }
    }

    return NextResponse.json({ investments })
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}

export async function POST(request: Request) {
  const session = await auth()
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const data = await request.json()
  const { companyName, companyId, content, file, fileName, entries } = data

  try {
    let parsedEntries = entries
    if (!parsedEntries && (content || file)) {
      const prompt = content
        ? `Parse this SOI data for ${companyName} into a JSON array. Each entry: asset, investmentDate, shares, cost, value, lastValuationDate, gainLoss, costPerShare, fmvPerShare, percentOfPartnersCapital, blendedMultiple. Use null for missing. Data:\n\n${content}\n\nReturn ONLY the JSON array.`
        : `File "${fileName}" uploaded for ${companyName}. Return empty array [].`

      const aiRes = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY!, "anthropic-version": "2023-06-01" },
        body: JSON.stringify({ model: "claude-haiku-4-5-20251001", max_tokens: 1000, messages: [{ role: "user", content: prompt }] }),
      })
      const aiData = await aiRes.json()
      const aiText = aiData.content?.[0]?.text || "[]"
      try {
        const jsonMatch = aiText.match(/\[[\s\S]*\]/)
        parsedEntries = jsonMatch ? JSON.parse(jsonMatch[0]) : []
      } catch { parsedEntries = [] }
    }

    const noteBody = [`SOI_DATA: ${companyName}`, `Updated: ${new Date().toISOString()}`, `SOI_JSON:${JSON.stringify(parsedEntries)}`].join("\n")

    const noteData = await hubspotCreateObject("notes", {
      hs_note_body: noteBody,
      hs_timestamp: Date.now().toString(),
    })

    if (companyId && noteData?.id) {
      await hubspotCreateAssociation("notes", noteData.id, "companies", companyId, "202")
    }

    return NextResponse.json({ success: true, entries: parsedEntries })
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}
