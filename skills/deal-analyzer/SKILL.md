---
name: deal-analyzer
description: Deep investment evaluation — 12-section VC analysis from pitch decks with web research, parallel AI analysis, and multi-channel delivery.
version: 2.0.0
author: GroundUp VC
actions:
  - analyze
  - evaluate
  - log
  - test
---

# Deal Analyzer v2

AI-powered investment evaluation that transforms a pitch deck into a comprehensive 12-section VC analysis. Combines deck extraction, web research, and Claude analysis to deliver investment-grade due diligence in 3-5 minutes.

## Conversational Flow

**Via WhatsApp:**
1. User sends a deck URL → `analyze` runs quick extraction, sends summary, asks "Want the full 12-section investment report?"
2. User replies "full report" → `full-report` runs deep analysis from saved state, sends TL;DR + memo via WhatsApp + email, asks "Want me to log this to HubSpot?"
3. User replies "log to hubspot" → `log` searches HubSpot for the company and adds the analysis as a note

**Via Email (automatic):**
1. Team member emails a deck to the assistant's email → email pipeline extracts deck, creates company + deal in HubSpot
2. Sender receives WhatsApp with quick analysis + "Want the full 12-section investment report?"
3. Sender replies "full report" → same deep analysis flow as above

## When to Use This Skill

**WhatsApp triggers:**
- "analyze this deck: [URL]" → quick extraction
- "evaluate this deal: [URL]" → full 12-section analysis
- "review this pitch deck: [URL]"
- "run due diligence on [URL]"
- "full report" → runs full 12-section analysis from last extraction
- "log to hubspot" → logs last evaluation to HubSpot

## Actions

### analyze (quick — 5-15 seconds)
Extract key data from a pitch deck. Sends WhatsApp summary and asks about full report.

```bash
deal-analyzer analyze <deck-url> [phone] [sender-email]
```

### evaluate (deep — 3-5 minutes)
Full 12-section investment analysis with web research. Delivers TL;DR + WhatsApp summary + email report. Asks about HubSpot logging.

```bash
deal-analyzer evaluate <deck-url> <phone> [email]
```

### full-report (deep — 3-5 minutes)
Run full evaluation using saved state from a prior analyze or email extraction. No URL needed.

```bash
deal-analyzer full-report [phone] [email]
```

### log
Log the last analysis to HubSpot as a company note.

```bash
deal-analyzer log [phone]
```

### test
Run test evaluation with sample deck data (FleetPulse).

```bash
deal-analyzer test
```

## 12 Analysis Sections

1. **Market Sizing & TAM Analysis** — TAM/SAM/SOM, growth rates, market segments
2. **Competitive Landscape** — Direct/indirect competitors, moats, white space
3. **Founder Background Check** — Team experience, track record, red flags
4. **Unit Economics Deep Dive** — CAC, LTV, margins, burn multiple
5. **Product-Market Fit Assessment** — Retention, NPS, organic growth signals
6. **Traction & Growth Metrics** — Revenue growth, user metrics, sales efficiency
7. **Financial Model Review** — Projections, burn rate, scenario modeling
8. **Technology & IP Assessment** — Tech stack, defensibility, data moats
9. **GTM Strategy Evaluation** — Channels, sales model, pricing, efficiency
10. **Market Timing & Trends** — Why now, catalysts, regulatory tailwinds
11. **Exit Scenario & Return Analysis** — Acquirers, comparable exits, return math
12. **Investment Memo Summary** — Recommendation, thesis, risks, next steps

## Pipeline

```
Phase 1: EXTRACT  (Claude Haiku, ~10s)     — Structured data from deck
Phase 2: RESEARCH (Brave Search, ~10s)     — 8 market/competitor queries
Phase 3: ANALYZE  (Claude Sonnet x12, ~3m) — Sequential section analysis
Phase 4: TL;DR    (Claude Haiku, ~5s)      — Executive summary paragraph
Phase 5: DELIVER  (~10s)                   — WhatsApp + email + HubSpot prompt
```

## Delivery

- **WhatsApp**: TL;DR + executive summary + investment recommendation
- **Email**: Full ~15-page investment memo with TL;DR and all 12 sections
- **HubSpot**: Company note with TL;DR + investment memo (on user confirmation)

## Configuration

Uses shared `config.yaml` and `.env`. Required environment variables:
- `ANTHROPIC_API_KEY` — Claude AI for extraction and analysis
- `BRAVE_SEARCH_API_KEY` — Web research for market data and competitor intel
- `MATON_API_KEY` — HubSpot integration for logging evaluations
