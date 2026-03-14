// In-memory cache with TTL for reducing redundant API / log-parsing calls
const cache = new Map<string, { data: unknown; expires: number }>()
export const CACHE_TTL = 5 * 60 * 1000 // 5 minutes

export function getCached<T>(key: string): T | null {
  const entry = cache.get(key)
  if (entry && entry.expires > Date.now()) return entry.data as T
  if (entry) cache.delete(key)
  return null
}

export function setCache(key: string, data: unknown, ttl = CACHE_TTL) {
  cache.set(key, { data, expires: Date.now() + ttl })
}

// Cleanup stale entries every 10 minutes
setInterval(() => {
  const now = Date.now()
  for (const [key, entry] of cache) {
    if (entry.expires < now) cache.delete(key)
  }
}, 10 * 60 * 1000)
