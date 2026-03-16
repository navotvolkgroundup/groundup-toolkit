/**
 * Tests for the withFreshness response envelope wrapper.
 */

import { withFreshness } from "../lib/withFreshness"

describe("withFreshness", () => {
  it("wraps data with freshness metadata", () => {
    const data = { foo: "bar" }
    const result = withFreshness(data, null, "hubspot")

    expect(result.data).toEqual({ foo: "bar" })
    expect(result.meta).toBeDefined()
    expect(result.meta.source).toBe("hubspot")
    expect(result.meta.stale).toBe(false)
    expect(result.meta.cacheHit).toBe(false)
    expect(result.meta.fetchedAt).toBeTruthy()
    expect(result.meta.dataAge).toBe(0)
  })

  it("calculates data age from ISO timestamp", () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString()
    const result = withFreshness({ x: 1 }, fiveMinAgo, "sqlite")

    expect(result.meta.dataAge).toBeGreaterThanOrEqual(299)
    expect(result.meta.dataAge).toBeLessThanOrEqual(301)
  })

  it("calculates data age from epoch ms", () => {
    const tenMinAgo = Date.now() - 10 * 60 * 1000
    const result = withFreshness({ x: 1 }, tenMinAgo, "cache")

    expect(result.meta.dataAge).toBeGreaterThanOrEqual(599)
    expect(result.meta.dataAge).toBeLessThanOrEqual(601)
  })

  it("marks as stale when exceeding threshold", () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
    const result = withFreshness({ x: 1 }, twoHoursAgo, "hubspot", 3600)

    expect(result.meta.stale).toBe(true)
    expect(result.meta.dataAge).toBeGreaterThanOrEqual(7199)
  })

  it("respects custom stale threshold", () => {
    const threeMinAgo = new Date(Date.now() - 3 * 60 * 1000).toISOString()

    // 5 min threshold -> not stale
    const r1 = withFreshness({ x: 1 }, threeMinAgo, "log_file", 300)
    expect(r1.meta.stale).toBe(false)

    // 2 min threshold -> stale
    const r2 = withFreshness({ x: 1 }, threeMinAgo, "log_file", 120)
    expect(r2.meta.stale).toBe(true)
  })

  it("passes cacheHit flag through", () => {
    const result = withFreshness({ x: 1 }, null, "cache", 3600, true)
    expect(result.meta.cacheHit).toBe(true)
  })

  it("handles null sourceTimestamp gracefully", () => {
    const result = withFreshness({ x: 1 }, null, "unknown")
    expect(result.meta.dataAge).toBe(0)
    expect(result.meta.stale).toBe(false)
  })

  it("preserves complex data structures", () => {
    const data = {
      stages: [{ id: "1", label: "Stage 1", count: 5, deals: [] }],
      totalDeals: 42,
    }
    const result = withFreshness(data, null, "hubspot")
    expect(result.data).toEqual(data)
    expect(result.data.totalDeals).toBe(42)
  })
})
