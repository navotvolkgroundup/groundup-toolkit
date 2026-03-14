# GroundUp Toolkit — Architecture Diagrams

> Generated: 2026-03-14

## 1. High-Level System Architecture

```mermaid
graph TB
    subgraph Users["Users"]
        WA[WhatsApp]
        Email[Email/Gmail]
        Dash[Dashboard]
    end

    subgraph Gateway["OpenClaw Gateway"]
        OC[OpenClaw v0.24]
        Agents[6 Agents]
    end

    subgraph Skills["Skills Layer"]
        FS[Founder Scout]
        DA[Deal Analyzer]
        ETD[Email-to-Deal]
        MR[Meeting Reminders]
        MB[Meeting Bot]
        KOR[Keep on Radar]
        CW[Content Writer]
        PT[Ping Teammate]
        VA[VC Automation]
    end

    subgraph SharedLibs["Shared Libraries"]
        LC[lib/claude.py]
        LH[lib/hubspot.py]
        LG[lib/gws.py]
        LW[lib/whatsapp.py]
        LB[lib/brave.py]
        LE[lib/email.py]
        LSU[lib/safe_url.py]
        LSL[lib/safe_log.py]
        LCF[lib/config.py]
    end

    subgraph External["External APIs"]
        Claude[Claude API]
        HubSpot[HubSpot via Maton]
        Google[Google Workspace]
        Brave[Brave Search]
        Twilio[Twilio Voice]
        LinkedIn[LinkedIn Browser]
    end

    subgraph Storage["Data Layer"]
        SQLite[(SQLite DBs)]
        Logs[/Log Files/]
        JSON[JSON State]
    end

    WA --> OC
    Email --> ETD
    Dash --> |Next.js API| Skills

    OC --> Agents
    Agents --> Skills

    Skills --> SharedLibs
    SharedLibs --> External

    Skills --> Storage

    LC --> Claude
    LH --> HubSpot
    LG --> Google
    LW --> OC
    LB --> Brave
```

## 2. Data Flow: Deal Sourcing Pipeline

```mermaid
flowchart LR
    subgraph Sources["Deal Sources"]
        LI[LinkedIn Signals]
        GM[Gmail Inbox]
        WA[WhatsApp Messages]
        DD[Deck URLs]
    end

    subgraph Processing["Processing"]
        FS[Founder Scout]
        ETD[Email-to-Deal]
        DL[Deal Logger]
        DA[Deal Analyzer]
    end

    subgraph CRM["HubSpot CRM"]
        Contact[Contact/Lead]
        Company[Company]
        Deal[Deal]
        Note[Note]
    end

    subgraph Output["Notifications"]
        WAOut[WhatsApp Alert]
        EmailOut[Email Report]
        DashOut[Dashboard]
    end

    LI --> FS
    GM --> ETD
    WA --> DL
    DD --> DA

    FS -->|Create lead| Contact
    FS -->|Weekly briefing| EmailOut

    ETD -->|Create company| Company
    ETD -->|Create deal| Deal
    ETD -->|Uncertain?| WAOut

    DA -->|12-section memo| Note
    DA -->|Score + summary| WAOut
    DA -->|Full report| EmailOut
    DA -->|Log deal| Deal

    Contact --> DashOut
    Deal --> DashOut
```

## 3. Meeting Lifecycle

```mermaid
sequenceDiagram
    participant Cal as Google Calendar
    participant MR as Meeting Reminders
    participant MB as Meeting Bot
    participant WA as WhatsApp
    participant Drive as Google Drive
    participant Claude as Claude API
    participant Email as Gmail

    Note over Cal: Meeting in 10 min

    MR->>Cal: Check calendar (*/5 min)
    Cal-->>MR: Meeting found
    MR->>MR: Enrich attendees (LinkedIn, Crunchbase, GitHub)
    MR->>WA: Send prep brief

    Note over Cal: Meeting starting

    MB->>Cal: Check calendar (*/3 min)
    Cal-->>MB: Meeting with Meet link
    MB->>MB: Launch Camofox browser
    MB->>MB: Join Google Meet (muted)

    Note over MB: Meeting in progress (up to 2h)

    MB->>MB: Meeting ends / attendees leave

    Note over Drive: Recording available

    MB->>Drive: Find recording
    Drive-->>MB: Transcript file
    MB->>Claude: Extract action items
    Claude-->>MB: Summary + decisions + TODOs
    MB->>Email: Send summary to attendees
    MB->>WA: Send brief to team
```

## 4. Email-to-Deal Pipeline

```mermaid
flowchart TD
    Start[Gmail Search: newer_than:24h] --> Filter{Team member sender?}
    Filter -->|No| Skip[Skip email]
    Filter -->|Yes| Extract[Extract company name]

    Extract --> Method1[Subject regex parsing]
    Extract --> Method2[Email domain extraction]
    Extract --> Method3[Claude AI extraction]

    Method1 --> Classify{Classify intent}
    Method2 --> Classify
    Method3 --> Classify

    Classify -->|DEAL| Portfolio{Portfolio company?}
    Classify -->|PORTFOLIO| HandlePortfolio[Route to portfolio_monitor]
    Classify -->|UNCERTAIN| AskSender[Ask sender via WhatsApp + email]

    Portfolio -->|Yes| HandlePortfolio
    Portfolio -->|No| SearchHS{Company in HubSpot?}

    SearchHS -->|Yes| ExistingCo[Use existing company]
    SearchHS -->|No| CreateCo[Create company]

    ExistingCo --> CreateDeal[Create deal]
    CreateCo --> CreateDeal

    CreateDeal --> Associate[Associate deal + company]
    Associate --> Label[Label email: HubSpot-Processed]
    Label --> Done[Done]

    AskSender --> WaitReply[Wait for reply]
```

## 5. Founder Scout Workflow

```mermaid
flowchart TD
    subgraph Daily["Daily Scan (7am UTC)"]
        Search[8 LinkedIn keyword searches]
        Search --> Filter[Two-phase filtering]
        Filter --> Visit[Full profile visit]
        Visit --> Analyze[Claude signal analysis]
        Analyze --> Score[Composite scoring]
        Score --> Store[(SQLite DB)]
        Store --> HS[Push leads to HubSpot]
        HS --> Alert[WhatsApp + email alerts]
    end

    subgraph Weekly["Weekly Briefing (Sun 8am)"]
        Compile[Compile week's findings]
        Compile --> Rank[Rank by signal tier]
        Rank --> Brief[Generate briefing email]
        Brief --> Send[Send to team]
    end

    subgraph Watchlist["Watchlist Re-scan (Wed+Sat)"]
        Load[Load tracked people]
        Load --> Revisit[Revisit LinkedIn profiles]
        Revisit --> Detect[Detect changes]
        Detect --> Update[Update DB + alert]
    end

    subgraph Modules["11 Intelligence Modules"]
        IDF[IDF Classifier]
        GH[GitHub Monitor]
        REG[Companies Registrar]
        DOM[Domain Monitor]
        EVT[Event Tracker]
        RET[Retention Clock]
        SOC[Social Graph]
        COMP[Competitive Intel]
        DARK[Going Dark]
        ADV[Advisor Tracker]
        SCR[Composite Scoring]
    end

    Analyze --> Modules
    Modules --> Score
```

## 6. Dashboard Architecture

```mermaid
graph TB
    subgraph Client["Browser (React 19)"]
        Pages[Pages: /, /portfolio, /settings, /login]
        Widgets[18 Dashboard Widgets]
        Chat[Chat Window]
        Store[Zustand Stores]
        RQ[TanStack React Query]
    end

    subgraph Middleware["Next.js Middleware"]
        Auth[NextAuth JWT]
        RL[Rate Limiter]
        Headers[Security Headers]
    end

    subgraph API["22 API Routes"]
        Pipeline[/api/pipeline]
        Stats[/api/stats]
        Signals[/api/signals]
        Leads[/api/leads]
        DealFlow[/api/deal-flow]
        Portfolio[/api/portfolio]
        Services[/api/services]
        ChatAPI[/api/chat]
        Actions[/api/actions]
        Other[... 13 more routes]
    end

    subgraph DataSources["Data Sources"]
        HS[HubSpot API]
        DB[(SQLite)]
        LogFiles[/var/log/*.log]
        OCAgent[OpenClaw Agent]
    end

    Pages --> RQ
    Chat --> Store
    RQ --> API
    Store --> API

    API --> Auth
    API --> RL

    Pipeline --> HS
    Stats --> HS
    Stats --> LogFiles
    Signals --> DB
    Signals --> LogFiles
    Leads --> DB
    DealFlow --> HS
    Portfolio --> HS
    ChatAPI --> OCAgent
    Actions -->|execSync| OCAgent
    Services -->|In-memory| Services
```

## 7. Cron Schedule Timeline (UTC)

```
Hour  | 0  1  2  3  4  5  6  7  8  9  10 11 12 13 14 15 16 17 18 19 20 21 22 23
------+------------------------------------------------------------------------
*/3m  | MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB MB
*/5m  | MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR MR
*/15m | HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC HC
*/15m | PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP PP
*/30m | LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW LW
*/2h  | ET    ET    ET    ET    ET    ET    ET    ET    ET    ET    ET    ET
*/2h  | KR    KR    KR    KR    KR    KR    KR    KR    KR    KR    KR    KR
Daily |             PM DM       FS FB                                    LD
------+------------------------------------------------------------------------

MB = meeting-bot auto-join     MR = meeting-reminders    HC = health-check
PP = post-meeting-processor    LW = log-watcher          ET = email-to-deal
KR = keep-on-radar replies     PM = portfolio-monitor     DM = daily-maintenance
FS = founder-scout scan        FB = founder-scout brief   LD = log-watcher digest
```

## 8. Security & Auth Flow

```mermaid
flowchart TD
    subgraph Dashboard["Dashboard Auth"]
        Login[Google OAuth Login]
        Login --> Check{@groundup.vc?}
        Check -->|Yes| JWT[Issue JWT Cookie]
        Check -->|No| Deny[Access Denied]
        JWT --> MW[Middleware Check]
        MW --> API[API Route]
        API --> RateLimit{Rate Limit OK?}
        RateLimit -->|Yes| Process[Process Request]
        RateLimit -->|No| 429[429 Too Many Requests]
    end

    subgraph Skills["Skill Auth"]
        Config[config.yaml + .env]
        Config --> Maton[Maton Bearer Token]
        Config --> Claude[Anthropic API Key]
        Config --> GWS[gws-auth OAuth2]
        Config --> Brave[Brave API Key]
        Config --> Twilio[Twilio SID + Key]
    end

    subgraph Protection["Security Measures"]
        SSRF[SSRF: Domain allowlist + IP pinning]
        Shell[Shell: List-based subprocess]
        PII[PII: safe_log.py redaction]
        Headers[Headers: CSP, X-Frame, HSTS]
    end
```

## 9. Component Dependency Graph

```mermaid
graph LR
    subgraph Core["Core Libraries"]
        Config[config.py]
        Claude[claude.py]
        HubSpot[hubspot.py]
        GWS[gws.py]
        WhatsApp[whatsapp.py]
        Brave[brave.py]
        Email[email.py]
    end

    subgraph Skills["Skills"]
        FS[founder-scout]
        DA[deal-analyzer]
        ETD[email-to-deal]
        MR[meeting-reminders]
        MB[meeting-bot]
        KOR[keep-on-radar]
        CW[content-writer]
        VA[vc-automation]
        PT[ping-teammate]
    end

    FS --> Config & Claude & HubSpot & WhatsApp
    DA --> Config & Claude & HubSpot & Brave & WhatsApp & Email & GWS
    ETD --> Config & Claude & HubSpot & GWS & WhatsApp
    MR --> Config & WhatsApp & GWS & HubSpot
    MB --> Config & GWS & Claude & Email & WhatsApp
    KOR --> Config & Claude & HubSpot & Brave & GWS & WhatsApp
    CW --> Config & Claude & Brave & WhatsApp & Email
    VA --> Config & Claude & HubSpot & Brave & GWS
    PT --> Config
```
