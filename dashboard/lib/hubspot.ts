const MATON_BASE = "https://gateway.maton.ai/hubspot"
const MATON_API_KEY = process.env.MATON_API_KEY || ""

interface HubSpotSearchResult {
  results: Array<{ id: string; properties: Record<string, string | null> }>
  total: number
  paging?: { next?: { after: string } }
}

export async function hubspotSearch(
  objectType: string,
  filters: Array<{ propertyName: string; operator: string; value?: string; values?: string[] }>,
  properties: string[],
  sorts?: Array<{ propertyName: string; direction: string }>,
  limit = 100,
  after?: string
): Promise<HubSpotSearchResult> {
  const body: Record<string, unknown> = {
    filterGroups: [{ filters }],
    properties,
    limit,
  }
  if (sorts) body.sorts = sorts
  if (after) body.after = after

  const res = await fetch(`${MATON_BASE}/crm/v3/objects/${objectType}/search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${MATON_API_KEY}`,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  })

  if (!res.ok) {
    throw new Error(`HubSpot search ${objectType} failed: ${res.status}`)
  }
  return res.json()
}

export async function hubspotSearchAll(
  objectType: string,
  filters: Array<{ propertyName: string; operator: string; value?: string; values?: string[] }>,
  properties: string[],
  sorts?: Array<{ propertyName: string; direction: string }>
): Promise<HubSpotSearchResult["results"]> {
  const all: HubSpotSearchResult["results"] = []
  let after: string | undefined

  for (let i = 0; i < 10; i++) {
    const result = await hubspotSearch(objectType, filters, properties, sorts, 100, after)
    all.push(...result.results)
    if (!result.paging?.next?.after) break
    after = result.paging.next.after
  }

  return all
}
