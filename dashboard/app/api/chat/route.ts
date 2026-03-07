import { NextRequest } from "next/server"
import { auth } from "@/lib/auth"
import { rateLimit } from "@/lib/rate-limit"
import { execFile } from "child_process"

const MAX_MESSAGE_LENGTH = 10000
const AGENT_TIMEOUT = 60_000

const limiter = rateLimit({ interval: 60_000, limit: 20 })

function runAgent(sessionId: string, message: string): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      "/usr/bin/openclaw",
      [
        "agent",
        "--session-id", sessionId,
        "--message", message,
        "--json",
      ],
      {
        timeout: AGENT_TIMEOUT,
        maxBuffer: 1024 * 1024,
        env: { ...process.env, HOME: "/root", PATH: "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" },
      },
      (error, stdout, stderr) => {
        if (error) {
          console.error("[chat] openclaw error:", error.message, stderr)
          return reject(new Error("Agent failed"))
        }
        try {
          const result = JSON.parse(stdout)
          const payloads = result?.result?.payloads
          if (payloads?.length > 0) {
            const text = payloads.map((p: { text: string }) => p.text).join("\n\n")
            resolve(text)
          } else {
            resolve("Sorry, I didn't get a response. Try again?")
          }
        } catch {
          console.error("[chat] Failed to parse agent output:", stdout.slice(0, 500))
          reject(new Error("Failed to parse agent response"))
        }
      }
    )
  })
}

export async function POST(req: NextRequest) {
  const { ok } = limiter.check(req)
  if (!ok) {
    return new Response("Too Many Requests", { status: 429 })
  }

  const session = await auth()
  if (!session?.user?.email) {
    return new Response("Unauthorized", { status: 401 })
  }

  let body
  try {
    body = await req.json()
  } catch {
    return new Response("Bad Request", { status: 400 })
  }

  const { message, context } = body
  if (typeof message !== "string" || message.length > MAX_MESSAGE_LENGTH) {
    return new Response("Bad Request", { status: 400 })
  }

  // Build the message with optional service context
  const contextPrefix = context && typeof context === "string"
    ? `[The user is asking about the "${context}" service in the dashboard.]\n\n`
    : ""
  const fullMessage = contextPrefix + message

  // Session ID per user for conversation persistence
  const sessionId = `dashboard:${session.user.email}`

  try {
    const responseText = await runAgent(sessionId, fullMessage)

    // Stream response word-by-word for typing effect
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      async start(controller) {
        const words = responseText.split(" ")
        for (let i = 0; i < words.length; i++) {
          const chunk = (i === 0 ? "" : " ") + words[i]
          controller.enqueue(encoder.encode(chunk))
          await new Promise((r) => setTimeout(r, 20 + Math.random() * 25))
        }
        controller.close()
      },
    })

    return new Response(stream, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Transfer-Encoding": "chunked",
      },
    })
  } catch {
    return new Response("Agent unavailable", { status: 502 })
  }
}
