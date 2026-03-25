# US Founder Scout

**Status:** Jordan-only access
**Version:** 1.0.0
**Triggers:** `us founder scout`, `american founder scout`, `approached founder`

Automated scouting for US tech founders and operators who are about to start new companies — before they announce or raise. Uses LinkedIn and Twitter/X browser automation to search for people, analyze profiles, and detect early signals. All tracking is local — no HubSpot sync.

## Features

### Target Profile
- US tech founders, CTOs, VPs who recently left a company
- Serial entrepreneurs between ventures
- YC/a16z/Sequoia alumni starting something new
- Operators hinting at "stealth mode" or "building something new"
- **Defense tech, deep tech, and dual-use founders specifically**

### Signal Tiers
- **High**: Left role + stealth tweets, co-founding announcement, "day 1" posts
- **Medium**: Open to work, recent exit/acquisition, exploring opportunities, cryptic "exciting news soon" posts
- **Low**: Accelerator completion, grants, advisory roles, conference speaking on "what's next"

### Twitter/X Signal Keywords
Monitored via browser search in addition to LinkedIn activity:
- "stealth", "building something", "day 1", "we're hiring" (from individual)
- "left [company]", "chapter 2", "new chapter", "grateful for the journey"
- Sudden spike in reply activity to other founders/investors

## Search Populations

The scan rotates through these seed lists. Each run picks 2-3 sources to stay within rate limits.

### 1. Deep Tech Company Alumni

People who worked at these $50M+ raised companies and recently left or changed roles:

**Defense**: Anduril, Shield AI, Epirus, Rebellion Defense, Vannevar Labs, Onebrief, Sarcos

**Robotics**: Figure AI, Physical Intelligence, Apptronik, Mytra, Gecko Robotics, Agility Robotics, Hadrian, Machina Labs

**Energy**: X-energy, Koloma, Commonwealth Fusion, Antora Energy, Form Energy, Electric Hydrogen, Solugen

**Space**: Astranis, Varda Space, Hermeus, Relativity Space, Albedo, True Anomaly, Apex Space

**Mobility**: Waabi, Gatik, Kodiak Robotics, Nuro, Einride, Plus.ai

**Smart Agriculture**: Plenty, Monarch Tractor, Field AI, AppHarvest

LinkedIn search logic:
- Past company: [name from list above]
- Current company: blank OR "stealth" OR self-employed
- Title keywords (past): founder, co-founder, CEO, CTO, CPO, VP Eng, VP Product
- Posted on LinkedIn: last 30 days

### 2. Ground Up Portfolio Company Alumni

People who previously worked at a Ground Up portfolio company and show founding signals.
These are warm leads — GUP has existing relationships and can provide direct intros.

**Fund I**: 402, Accrue Savings, Array, BuildOps, Daily.co, Dandelion Energy, Disco, EliseAI, Flyp, Glass Imaging, Jones, Komodor, Openlayer, PDQ, Pipe, Postmoda, Tolstoy, TrueHold, Tulu, Upfort, Younity

**Fund II**: Axo Neurotech, Baba, Covenant, Dialogue, Dialogica, Draftboard, FutureLot, G2, Harbinger, Hello Wonder, HyWatts, Kela, Lenkie, Meridian, Nevona.AI, Ownli, Panjaya, Phase Zero, Pillar Security, Portless, PreQl, Proov.ai, Real, Reap, Refine Intelligence, Ritual, StarCloud, TermScout, ThreeFold, TripleWhale, Unit.AI, Weave, Zealthy, Zeromark

Flag in DB: `source = "gup_alumni"` — surface at top of briefings.
Note context: which portfolio company, and flag for warm intro potential.

### 3. Accelerator Alumni
YC batches (W22–W25), a16z Scout, Sequoia Arc, Lux Capital portfolio operators

### 4. Exit/Acquisition Lists
People at companies acquired in the last 18 months (sourced via Crunchbase browse)

### 5. Mutual Network
LinkedIn 2nd-degree connections from team members (Jordan, Cory, David, Navot, Allie)

## Commands

```bash
# Daily scan — run rotated LinkedIn + Twitter/X searches, detect signals
us-founder-scout scan

# Weekly briefing — compile summary (printed to stdout / log)
us-founder-scout briefing

# Re-scan existing tracked people
us-founder-scout watchlist-update

# View current state
us-founder-scout status

# Manually add a person
us-founder-scout add "Name" "https://linkedin.com/in/username" [--twitter @handle]

# Dismiss a tracked person
us-founder-scout dismiss <id>

# Mark a person as approached (by name)
us-founder-scout approach "Jake Saper"

# Mark a person as approached (by DB id)
us-founder-scout approach-id 42
```

## Handling "I approached X" Messages

**IMPORTANT — When Jordan says something like:**
- "I approached Jake Saper"
- "I reached out to Sarah Guo"
- "Mark Dan Romero as approached"

**The assistant MUST:**
1. Run `us-founder-scout approach "<person name>"` to mark them as approached
2. This updates the local database only
3. Confirm to the user that the person was marked as approached
4. If multiple matches are found, show the list and ask the user to clarify

If the person is not in the watchlist, tell the user and offer to add them first with `us-founder-scout add`.

## Setup

### 1. Environment
Requires these keys in `.env`:
- `ANTHROPIC_API_KEY` — for Claude signal analysis

### 2. Browser Sessions (both required)
Both sessions must be logged in and available before a scan will run. The scan aborts if either session is unavailable.

- **LinkedIn** — existing browser skill session
- **Twitter/X** — same setup pattern as LinkedIn; requires a logged-in X account

No Twitter API key or developer account needed.

### 3. Cron (automated)

Add these to Christina's crontab:

```bash
# Daily scan at 7:00 AM UTC
0 7 * * * . /root/.env && /usr/bin/python3 /root/.openclaw/skills/us-founder-scout/scout.py scan >> /var/log/us-founder-scout.log 2>&1

# Weekly briefing Sunday 8:00 AM (printed to stdout / log)
0 8 * * 0 . /root/.env && /usr/bin/python3 /root/.openclaw/skills/us-founder-scout/scout.py briefing >> /var/log/us-founder-scout.log 2>&1

# Watchlist re-scan Mon/Wed/Fri at 14:00
0 14 * * 1,3,5 . /root/.env && /usr/bin/python3 /root/.openclaw/skills/us-founder-scout/scout.py watchlist-update >> /var/log/us-founder-scout.log 2>&1
```

## Rate Limits
- LinkedIn browser: max 15 profile lookups/scan, ~4s delay between navigations
- Twitter/X browser: max 10 searches/scan, ~3-4s delay between searches
- Claude API: max 10 calls/scan (~$0.10/scan)

## Local Database
All tracked founders are stored in a local SQLite DB. No external CRM sync. Schema includes:
- `id`, `name`, `linkedin_url`, `twitter_handle`
- `signal_tier`, `last_signal`, `last_scanned`
- `status` — `OPEN` or `APPROACHED`
- `source` — `deeptech_alumni`, `gup_alumni`, `accelerator`, `exit_list`, `network`, `manual`
- `source_company` — which company they came from (used for warm intro context)
- `notes` — freeform field for manual context

## Data Location
Database stored at: `~/.groundup-toolkit/us-founder-scout/founders.db`

## Access Control
**This skill is restricted to Jordan Odinsky.** Only Jordan can trigger scans, update the watchlist, or modify tracking.

Attempting to run as another user will result in an access denied error.
