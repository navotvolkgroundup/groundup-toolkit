import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { defaultServices } from "@/lib/data/services"
import * as fs from "fs"
import * as path from "path"

// Security: rate limit services API to 60 requests per minute per IP
const limiter = rateLimit({ interval: 60_000, limit: 60 })

// Persist service toggle state to JSON file
const STATE_DIR = path.join(process.cwd(), "data")
const STATE_FILE = path.join(STATE_DIR, "service-toggles.json")

type ToggleState = Record<string, boolean>

function loadToggleState(): ToggleState {
  try {
    if (fs.existsSync(STATE_FILE)) {
      return JSON.parse(fs.readFileSync(STATE_FILE, "utf-8"))
    }
  } catch {
    // Fall back to defaults on parse error
  }
  return {}
}

function saveToggleState(state: ToggleState) {
  try {
    if (!fs.existsSync(STATE_DIR)) fs.mkdirSync(STATE_DIR, { recursive: true })
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2))
  } catch (e) {
    console.error("Failed to save service toggle state:", e)
  }
}

// Apply persisted state to defaultServices on startup
const toggleState = loadToggleState()
for (const service of defaultServices) {
  if (service.canToggle && service.id in toggleState) {
    service.enabledForUser = toggleState[service.id]
    service.status = toggleState[service.id] ? "active" : "inactive"
  }
}

export async function GET(req: NextRequest) {
  // Security: rate limiting
  const { ok } = await limiter.check(req)
  if (!ok) {
    return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })
  }

  // Security: explicit auth check (defense-in-depth beyond middleware)
  const session = await auth()
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  return NextResponse.json(defaultServices)
}

export async function PATCH(req: NextRequest) {
  // Security: rate limiting
  const { ok: rl } = await limiter.check(req)
  if (!rl) {
    return NextResponse.json({ error: "Too Many Requests" }, { status: 429 })
  }

  // Security: explicit auth check (defense-in-depth beyond middleware)
  const session = await auth()
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  // Security: validate input
  let body
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: "Bad Request" }, { status: 400 })
  }

  const { serviceId, enabled } = body
  if (typeof serviceId !== "string" || typeof enabled !== "boolean") {
    return NextResponse.json({ error: "Invalid input" }, { status: 400 })
  }

  const service = defaultServices.find((s) => s.id === serviceId)
  if (!service) {
    return NextResponse.json({ error: "Service not found" }, { status: 404 })
  }
  if (!service.canToggle) {
    return NextResponse.json({ error: "Service cannot be toggled" }, { status: 400 })
  }

  service.enabledForUser = enabled
  service.status = enabled ? "active" : "inactive"

  // Persist toggle state
  const state = loadToggleState()
  state[serviceId] = enabled
  saveToggleState(state)

  return NextResponse.json(service)
}
