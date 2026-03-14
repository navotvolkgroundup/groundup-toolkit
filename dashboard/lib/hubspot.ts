import { getCached, setCache, CACHE_TTL } from "./cache"

const MATON_BASE = "https://gateway.maton.ai/hubspot"
const MATON_API_KEY = process.env.MATON_API_KEY || ""

const AUTH_HEADERS = {
  Authorization: `Bearer ${MATON_API_KEY}`,
  "Content-Type": "application/json",
}

interface HubSpotSearchResult {
  results: Array<{ id: string; properties: Record<string, string | null> }>
  total: number
  paging?: { next?: { after: string } }
}

// ── Generic fetch with retry on 429 ─────────────────────────────────────────

export async function hubspotFetch(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  retries = 3
): Promise<Record<string, unknown> | null> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(`${MATON_BASE}${path}`, {
        method,
        headers: AUTH_HEADERS,
        body: body ? JSON.stringify(body) : undefined,
        cache: "no-store",
      })
      if (res.status === 429) {
        const wait = Math.pow(2, attempt) * 1000
        console.log(`[hubspot] 429 on ${path}, waiting ${wait}ms (attempt ${attempt + 1}/${retries})`)
        await new Promise((r) => setTimeout(r, wait))
        continue
      }
      if (!res.ok) {
        console.error(`[hubspot] ${method} ${path} → ${res.status}`)
        return null
      }
      return res.json()
    } catch (e) {
      console.error(`[hubspot] ${method} ${path} error:`, e)
      return null
    }
  }
  return null
}

export const hubspotGet = (path: string) => hubspotFetch("GET", path)
export const hubspotPost = (path: string, body: unknown) => hubspotFetch("POST", path, body)
export const hubspotPut = (path: string, body?: unknown) => hubspotFetch("PUT", path, body)

// ── Typed helpers ────────────────────────────────────────────────────────────

export async function hubspotBatchRead(
  objectType: string,
  ids: string[],
  properties: string[]
): Promise<Array<{ id: string; properties: Record<string, string | null> }>> {
  const chunks: string[][] = []
  for (let i = 0; i < ids.length; i += 100) chunks.push(ids.slice(i, i + 100))

  const results = await Promise.all(
    chunks.map((chunk) =>
      hubspotPost(`/crm/v3/objects/${objectType}/batch/read`, {
        inputs: chunk.map((id) => ({ id })),
        properties,
      }) as Promise<{ results?: Array<{ id: string; properties: Record<string, string | null> }> } | null>
    )
  )
  return results.flatMap((r) => r?.results ?? [])
}

export async function hubspotCreateObject(
  objectType: string,
  properties: Record<string, string>
): Promise<{ id: string; properties: Record<string, string | null> } | null> {
  const res = await hubspotPost(`/crm/v3/objects/${objectType}`, { properties })
  return res as { id: string; properties: Record<string, string | null> } | null
}

export async function hubspotGetAssociations(
  fromType: string,
  fromId: string,
  toType: string
): Promise<Array<{ id: string; type: string }>> {
  const res = await hubspotGet(`/crm/v3/objects/${fromType}/${fromId}/associations/${toType}`)
  return (res as { results?: Array<{ id: string; type: string }> } | null)?.results ?? []
}

export async function hubspotCreateAssociation(
  fromType: string,
  fromId: string,
  toType: string,
  toId: string,
  associationType: string | number
): Promise<void> {
  await hubspotPut(`/crm/v3/objects/${fromType}/${fromId}/associations/${toType}/${toId}/${associationType}`)
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
