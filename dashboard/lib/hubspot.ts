const MATON_BASE = "https://gateway.maton.ai/hubspot"
const MATON_API_KEY = process.env.MATON_API_KEY || ""

interface HubSpotSearchResult {
  results: Array<{ id: string; properties: Record<string, string | null> }>
  total: number
  paging?: { next?: { after: string } }
}

// In-memory cache with TTL for reducing redundant HubSpot API calls
const cache = new Map<string, { data: unknown; expires: number }>()
const CACHE_TTL = 5 * 60 * 1000 // 5 minutes

function getCached<T>(key: string): T | null {
  const entry = cache.get(key)
  if (entry && entry.expires > Date.now()) return entry.data as T
  if (entry) cache.delete(key)
  return null
}

function setCache(key: string, data: unknown, ttl = CACHE_TTL) {
  cache.set(key, { data, expires: Date.now() + ttl })
}

// Cleanup stale entries every 10 minutes
setInterval(() => {
  const now = Date.now()
  for (const [key, entry] of cache) {
    if (entry.expires < now) cache.delete(key)
  }
}, 10 * 60 * 1000)

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

  if (res.status === 429) {
    // Rate limited — wait and retry once
    await new Promise((r) => setTimeout(r, 2000))
    const retry = await fetch(`${MATON_BASE}/crm/v3/objects/${objectType}/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${MATON_API_KEY}`,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    })
    if (!retry.ok) {
      throw new Error(`HubSpot search ${objectType} failed: ${retry.status}`)
    }
    return retry.json()
  }

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

/**
 * Cached version of hubspotSearchAll. Uses a 5-minute in-memory cache
 * keyed on the query parameters to reduce redundant API calls.
 */
export async function hubspotSearchAllCached(
  objectType: string,
  filters: Array<{ propertyName: string; operator: string; value?: string; values?: string[] }>,
  properties: string[],
  sorts?: Array<{ propertyName: string; direction: string }>,
  ttl = CACHE_TTL
): Promise<HubSpotSearchResult["results"]> {
  const key = JSON.stringify({ objectType, filters, properties, sorts })
  const cached = getCached<HubSpotSearchResult["results"]>(key)
  if (cached) return cached

  const results = await hubspotSearchAll(objectType, filters, properties, sorts)
  setCache(key, results, ttl)
  return results
}
