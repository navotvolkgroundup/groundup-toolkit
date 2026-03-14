/**
 * Rate limiter for API routes with optional Redis backend.
 *
 * When REDIS_URL is set and ioredis is installed, uses a Redis sliding window
 * counter. Otherwise falls back to in-memory rate limiting.
 *
 * Usage:
 *   const limiter = rateLimit({ interval: 60_000, limit: 30 })
 *   export async function POST(req) {
 *     const { ok } = await limiter.check(req)
 *     if (!ok) return new Response("Too Many Requests", { status: 429 })
 *     ...
 *   }
 */

interface RateLimitOptions {
  interval: number // Window in milliseconds
  limit: number    // Max requests per window per IP
}

interface RateLimitResult {
  ok: boolean
  remaining: number
}

// ---------------------------------------------------------------------------
// In-memory backend (fallback)
// ---------------------------------------------------------------------------

interface TokenBucket {
  count: number
  resetAt: number
}

const buckets = new Map<string, TokenBucket>()

// Clean up stale entries every 5 minutes
setInterval(() => {
  const now = Date.now()
  for (const [key, bucket] of buckets) {
    if (bucket.resetAt < now) {
      buckets.delete(key)
    }
  }
}, 5 * 60 * 1000)

function checkInMemory(
  ip: string,
  options: RateLimitOptions,
): RateLimitResult {
  const now = Date.now()
  const bucket = buckets.get(ip)

  if (!bucket || bucket.resetAt < now) {
    buckets.set(ip, { count: 1, resetAt: now + options.interval })
    return { ok: true, remaining: options.limit - 1 }
  }

  bucket.count++
  if (bucket.count > options.limit) {
    return { ok: false, remaining: 0 }
  }
  return { ok: true, remaining: options.limit - bucket.count }
}

// ---------------------------------------------------------------------------
// Redis backend (optional)
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let redisClient: any = null
let redisAttempted = false
let redisAvailable = false

async function getRedis(): Promise<any> {
  if (redisAttempted) return redisAvailable ? redisClient : null
  redisAttempted = true

  const url = process.env.REDIS_URL
  if (!url) return null

  try {
    // Dynamic import so the module is optional – won't break builds if
    // ioredis is not installed. The variable indirection prevents TypeScript
    // from resolving the module at compile time.
    const mod = "ioredis"
    const { default: Redis } = await import(/* webpackIgnore: true */ mod)
    const client = new Redis(url, {
      maxRetriesPerRequest: 1,
      connectTimeout: 3000,
      lazyConnect: true,
    })

    await client.connect()
    redisClient = client
    redisAvailable = true

    client.on("error", () => {
      // Connection lost after initial success – fall back silently.
      redisAvailable = false
    })

    return client
  } catch {
    console.warn("[rate-limit] Redis unavailable – using in-memory fallback")
    return null
  }
}

async function checkRedis(
  redis: any, // eslint-disable-line @typescript-eslint/no-explicit-any
  ip: string,
  options: RateLimitOptions,
): Promise<RateLimitResult> {
  const key = `rl:${ip}`
  const intervalSec = Math.ceil(options.interval / 1000)

  try {
    // Simple fixed-window counter with TTL, matching the in-memory behaviour.
    const count = await redis.incr(key)
    if (count === 1) {
      await redis.expire(key, intervalSec)
    }

    if (count > options.limit) {
      return { ok: false, remaining: 0 }
    }
    return { ok: true, remaining: options.limit - count }
  } catch {
    // Redis error mid-request – fall back to in-memory for this call.
    redisAvailable = false
    return checkInMemory(ip, options)
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function getIp(req: Request): string {
  return (
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.headers.get("x-real-ip") ||
    "unknown"
  )
}

export function rateLimit(options: RateLimitOptions) {
  return {
    async check(req: Request): Promise<RateLimitResult> {
      const ip = getIp(req)

      const redis = await getRedis()
      if (redis && redisAvailable) {
        return checkRedis(redis, ip, options)
      }

      return checkInMemory(ip, options)
    },
  }
}
