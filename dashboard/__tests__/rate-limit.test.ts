/**
 * Tests for the in-memory rate limiter.
 */

import { rateLimit } from "../lib/rate-limit"

function makeRequest(ip = "1.2.3.4"): Request {
  return new Request("http://localhost/api/test", {
    headers: { "x-forwarded-for": ip },
  })
}

describe("rateLimit", () => {
  it("allows requests under the limit", async () => {
    const limiter = rateLimit({ interval: 60_000, limit: 5 })
    const req = makeRequest()

    const r1 = await limiter.check(req)
    expect(r1.ok).toBe(true)
    expect(r1.remaining).toBe(4)

    const r2 = await limiter.check(req)
    expect(r2.ok).toBe(true)
    expect(r2.remaining).toBe(3)
  })

  it("blocks requests over the limit", async () => {
    const limiter = rateLimit({ interval: 60_000, limit: 2 })
    const req = makeRequest("10.0.0.1")

    await limiter.check(req) // 1
    await limiter.check(req) // 2
    const r3 = await limiter.check(req) // 3 -> blocked

    expect(r3.ok).toBe(false)
    expect(r3.remaining).toBe(0)
  })

  it("tracks IPs separately", async () => {
    const limiter = rateLimit({ interval: 60_000, limit: 1 })

    // Use unique IPs not used in other tests
    const r1 = await limiter.check(makeRequest("172.16.0.1"))
    expect(r1.ok).toBe(true)

    // Different IP should still be allowed
    const r2 = await limiter.check(makeRequest("172.16.0.2"))
    expect(r2.ok).toBe(true)

    // First IP should now be blocked
    const r3 = await limiter.check(makeRequest("172.16.0.1"))
    expect(r3.ok).toBe(false)
  })

  it("uses x-real-ip as fallback", async () => {
    const limiter = rateLimit({ interval: 60_000, limit: 1 })
    const req = new Request("http://localhost/api/test", {
      headers: { "x-real-ip": "192.168.1.1" },
    })

    const r1 = await limiter.check(req)
    expect(r1.ok).toBe(true)

    const r2 = await limiter.check(req)
    expect(r2.ok).toBe(false)
  })
})
