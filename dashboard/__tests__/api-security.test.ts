/**
 * Security tests — verify API routes use execFileSync (not execSync),
 * have auth checks, and have rate limiting.
 */

import { readFileSync, readdirSync, statSync } from "fs"
import { join } from "path"

const API_DIR = join(__dirname, "..", "app", "api")

function getAllRouteFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      files.push(...getAllRouteFiles(full))
    } else if (entry === "route.ts") {
      files.push(full)
    }
  }
  return files
}

// Routes that are exempt from certain checks
const AUTH_EXEMPT = ["auth/[...nextauth]"] // NextAuth handler
const RATE_LIMIT_EXEMPT = ["auth/[...nextauth]", "events"] // auth handler, SSE stream

describe("API route security", () => {
  const routeFiles = getAllRouteFiles(API_DIR)

  it("finds at least 20 route files", () => {
    expect(routeFiles.length).toBeGreaterThanOrEqual(20)
  })

  describe("no execSync with user input", () => {
    const CRITICAL_ROUTES = [
      "actions/route.ts",
      "deal-timeline/route.ts",
      "relationships/route.ts",
    ]

    for (const route of CRITICAL_ROUTES) {
      it(`${route} uses execFileSync, not execSync`, () => {
        const file = routeFiles.find((f) => f.includes(route))
        expect(file).toBeDefined()
        const content = readFileSync(file!, "utf-8")

        // Should import execFileSync
        expect(content).toContain("execFileSync")
        // Should NOT import execSync (plain)
        expect(content).not.toMatch(/import\s*\{[^}]*\bexecSync\b/)
      })
    }
  })

  describe("auth checks", () => {
    for (const file of routeFiles) {
      const relative = file.replace(API_DIR + "/", "")
      const isExempt = AUTH_EXEMPT.some((e) => relative.includes(e))

      if (!isExempt) {
        it(`${relative} has auth check`, () => {
          const content = readFileSync(file, "utf-8")
          expect(content).toMatch(/auth\(\)/)
        })
      }
    }
  })

  describe("rate limiting", () => {
    for (const file of routeFiles) {
      const relative = file.replace(API_DIR + "/", "")
      const isExempt = RATE_LIMIT_EXEMPT.some((e) => relative.includes(e))

      if (!isExempt) {
        it(`${relative} has rate limiting`, () => {
          const content = readFileSync(file, "utf-8")
          // Should either import rateLimit or be a sub-route of a rate-limited parent
          expect(content).toMatch(/rateLimit|limiter/)
        })
      }
    }
  })

  describe("security headers configured", () => {
    it("next.config.ts has security headers", () => {
      const config = readFileSync(
        join(__dirname, "..", "next.config.ts"),
        "utf-8"
      )
      expect(config).toContain("X-Frame-Options")
      expect(config).toContain("X-Content-Type-Options")
      expect(config).toContain("Referrer-Policy")
    })
  })

  describe("no hardcoded secrets", () => {
    for (const file of routeFiles) {
      const relative = file.replace(API_DIR + "/", "")
      it(`${relative} has no hardcoded API keys`, () => {
        const content = readFileSync(file, "utf-8")
        // Check for common secret patterns
        expect(content).not.toMatch(/sk-ant-[A-Za-z0-9]{10,}/)
        expect(content).not.toMatch(/sk-[A-Za-z0-9]{20,}/)
        expect(content).not.toMatch(/GOCSPX-[A-Za-z0-9]+/)
      })
    }
  })
})
