import { NextRequest } from "next/server"
import { auth } from "@/lib/auth"

const MAX_MESSAGE_LENGTH = 10000

const responses: Record<string, string> = {
  default: `Hey! I'm Christina, your AI assistant at GroundUp. I can help you with deal sourcing, meeting prep, portfolio monitoring, and more.

What would you like to know?`,
  "deal-sourcing": `The **Deal Sourcing Radar** is tracking 847 profiles across Israeli tech.

Recent signals I've picked up:
- 3 ex-Wiz engineers with stealth LinkedIn updates
- 2 former Unit 8200 operators who just finished vesting
- 1 repeat founder who quietly registered a new company

Want me to dive deeper into any of these?`,
  "meeting-monitor": `The **Meeting Attendance Monitor** is running smoothly.

Today's stats:
- 4 meetings tracked
- 2 WhatsApp reminders sent
- 0 escalations needed

Everyone showed up on time today!`,
  "deck-analyzer": `The **Deck Analyzer** has processed 12 decks this week.

Top scoring decks:
1. **NovaTech** — 7.2/10 (Strong team, unclear GTM)
2. **DataForge** — 6.8/10 (Good TAM, weak moat)
3. **CyberShield** — 8.1/10 (Exceptional team + market timing)

Want me to pull the full report on any of these?`,
}

export async function POST(req: NextRequest) {
  // Security: explicit auth check (defense-in-depth beyond middleware)
  const session = await auth()
  if (!session) {
    return new Response("Unauthorized", { status: 401 })
  }

  // Security: validate input
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

  const responseText = context && typeof context === "string" && responses[context]
    ? responses[context]
    : generateResponse(message)

  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    async start(controller) {
      const words = responseText.split(" ")
      for (let i = 0; i < words.length; i++) {
        const chunk = (i === 0 ? "" : " ") + words[i]
        controller.enqueue(encoder.encode(chunk))
        await new Promise((r) => setTimeout(r, 30 + Math.random() * 40))
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
}

function generateResponse(message: string): string {
  const lower = message.toLowerCase()

  if (lower.includes("deal") || lower.includes("source") || lower.includes("founder")) {
    return responses["deal-sourcing"]
  }
  if (lower.includes("meeting") || lower.includes("calendar") || lower.includes("schedule")) {
    return responses["meeting-monitor"]
  }
  if (lower.includes("deck") || lower.includes("pitch") || lower.includes("analyze")) {
    return responses["deck-analyzer"]
  }
  if (lower.includes("portfolio") || lower.includes("company") || lower.includes("monitor")) {
    return `I'm keeping an eye on all portfolio companies. Recent highlights:\n\n- **PortCo Alpha**: Series B announced, $25M raised\n- **PortCo Beta**: New CTO hired from Google\n- **PortCo Gamma**: Featured in Forbes 30 Under 30\n\nWant me to set up custom alerts for any company?`
  }
  if (lower.includes("health") || lower.includes("status") || lower.includes("system")) {
    return `All systems are running smoothly:\n\n- Gateway: **Active**\n- WhatsApp: **Connected**\n- All 6 agents: **Online**\n- Disk: **42% used**\n- Memory: **58% used**\n\nNo issues detected in the last 24 hours.`
  }
  if (lower.includes("help") || lower.includes("what can you")) {
    return responses.default
  }

  // Security: don't echo raw user input back in response
  return `I can help with:\n- **Deal Sourcing** — tracking founders and pre-founding signals\n- **Meeting Management** — reminders, briefs, attendance\n- **Portfolio Monitoring** — news, signals, alerts\n- **Deck Analysis** — AI-powered pitch deck scoring\n- **System Health** — infrastructure monitoring\n\nWhat would you like to explore?`
}
