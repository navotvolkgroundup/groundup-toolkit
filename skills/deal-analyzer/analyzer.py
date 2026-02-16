#!/usr/bin/env python3
"""
Deal Analyzer v2 — Deep investment evaluation from pitch decks.

Phases:
  1. EXTRACT  — Fetch deck content, extract structured data (Haiku)
  2. RESEARCH — Web research via Brave Search (8 queries)
  3. ANALYZE  — 12-section VC analysis in parallel (Sonnet)
  4. DELIVER  — WhatsApp summary + email full report

Usage:
  python3 analyzer.py analyze <deck-url> [sender-email]
  python3 analyzer.py evaluate <deck-url> <phone> [email]
  python3 analyzer.py test
"""

import sys
import os
import re
import json
import time
import subprocess
import tempfile
import requests
from datetime import datetime

# Load shared config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config

# --- Constants ---

ANTHROPIC_API_KEY = config.anthropic_api_key
BRAVE_SEARCH_API_KEY = config.brave_search_api_key
MATON_API_KEY = config.maton_api_key
MATON_BASE_URL = "https://gateway.maton.ai/hubspot/crm/v3/objects"
GOG_ACCOUNT = config.assistant_email
STATE_FILE = "/tmp/deal-analyzer-state.json"

# --- Core API Functions ---


def call_claude(prompt, system_prompt="", model="claude-sonnet-4-20250514", max_tokens=4096):
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    if system_prompt:
        payload["system"] = system_prompt

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    for attempt in range(5):
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=120
        )
        if response.status_code == 200:
            return response.json()["content"][0]["text"]

        if response.status_code == 429:
            wait = min(15 * (attempt + 1), 60)
            print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/5)...", file=sys.stderr)
            time.sleep(wait)
            continue

        if response.status_code == 529:
            wait = 30
            print(f"  API overloaded, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue

        print(f"  Claude API error: {response.status_code} {response.text[:200]}", file=sys.stderr)
        return f"Analysis failed — API error ({response.status_code})."

    return "Analysis failed — rate limit exceeded after retries."


def brave_search(query, count=5):
    if not BRAVE_SEARCH_API_KEY:
        return []
    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_SEARCH_API_KEY},
            params={"q": query, "count": count},
            timeout=10
        )
        if response.status_code != 200:
            return []
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
            for r in response.json().get("web", {}).get("results", [])
        ]
    except Exception as e:
        print(f"  Search error: {e}", file=sys.stderr)
        return []


def send_whatsapp(phone, message, max_retries=3, retry_delay=3):
    for attempt in range(1, max_retries + 1):
        try:
            cmd = [
                'openclaw', 'message', 'send',
                '--channel', 'whatsapp',
                '--target', phone,
                '--message', message
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                return True
            else:
                print(f"  WhatsApp attempt {attempt}/{max_retries}: {result.stderr.strip()[:100]}", file=sys.stderr)
                if attempt < max_retries:
                    time.sleep(retry_delay)
        except Exception as e:
            print(f"  WhatsApp attempt {attempt}/{max_retries}: {e}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(retry_delay)
    return False


def send_email(to_email, subject, body):
    try:
        body_file = tempfile.mktemp(suffix='.txt')
        with open(body_file, 'w') as f:
            f.write(body)
        cmd = [
            'gog', 'gmail', 'send',
            '--to', to_email,
            '--subject', subject,
            '--body-file', body_file,
            '--account', GOG_ACCOUNT,
            '--force', '--no-input'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        try:
            os.unlink(body_file)
        except Exception:
            pass
        if result.returncode == 0:
            print(f"  Email sent to {to_email}")
            return True
        else:
            print(f"  Email failed: {result.stderr.strip()[:200]}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  Email exception: {e}", file=sys.stderr)
        return False


# --- State Management ---


def save_state(deck_data, section_results=None, tldr=None):
    """Save analysis state so the log action can read it later."""
    state = {
        'deck_data': deck_data,
        'tldr': tldr,
        'timestamp': datetime.now().isoformat(),
    }
    if section_results:
        state['hubspot_note'] = format_hubspot_note(deck_data, section_results, tldr)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def load_state():
    """Load the last analysis state."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# --- HubSpot Integration ---


def hubspot_search_company(company_name):
    """Search HubSpot for a company by name. Returns company ID or None."""
    if not MATON_API_KEY:
        print("  MATON_API_KEY not set, skipping HubSpot", file=sys.stderr)
        return None
    headers = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(
            f"{MATON_BASE_URL}/companies/search",
            headers=headers,
            json={
                "filterGroups": [{"filters": [{"propertyName": "name", "operator": "CONTAINS_TOKEN", "value": company_name}]}],
                "properties": ["name", "domain"],
                "limit": 5,
            },
            timeout=10,
        )
        if response.status_code == 200:
            results = response.json().get('results', [])
            for r in results:
                if r.get('properties', {}).get('name', '').lower() == company_name.lower():
                    return r['id']
            if results:
                return results[0]['id']
        return None
    except Exception as e:
        print(f"  HubSpot search error: {e}", file=sys.stderr)
        return None


def hubspot_add_note(company_id, note_text):
    """Add a note to a HubSpot company."""
    headers = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(
            f"{MATON_BASE_URL}/notes",
            headers=headers,
            json={
                "properties": {
                    "hs_timestamp": str(int(datetime.now().timestamp() * 1000)),
                    "hs_note_body": note_text,
                },
                "associations": [{"to": {"id": company_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 190}]}],
            },
            timeout=10,
        )
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"  HubSpot note error: {e}", file=sys.stderr)
        return False


# --- Phase 1: Deck Extraction ---

DOCSEND_PATTERN = re.compile(r'https://docsend\.com/view/[a-zA-Z0-9]+')
GDOCS_PATTERN = re.compile(r'https://docs\.google\.com/[^\s<>"]+')
GDRIVE_PATTERN = re.compile(r'https://drive\.google\.com/[^\s<>"]+')
DROPBOX_PATTERN = re.compile(r'https://www\.dropbox\.com/[^\s<>"]+')
PDF_PATTERN = re.compile(r'https://[^\s<>"]*\.pdf')


def extract_deck_links(text):
    links = []
    for pattern in [DOCSEND_PATTERN, GDOCS_PATTERN, GDRIVE_PATTERN, DROPBOX_PATTERN, PDF_PATTERN]:
        links.extend(pattern.findall(text))
    return list(dict.fromkeys(links))


def fetch_deck_content(url, sender_email=None):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        if 'docsend.com' in url and sender_email:
            headers['Cookie'] = f'email={sender_email}'
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.text
        print(f"  Fetch failed: HTTP {response.status_code} for {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Fetch error: {e}", file=sys.stderr)
        return None


def extract_deck_data(content):
    """Phase 1: Extract structured data from deck content using Haiku."""
    prompt = f"""Extract structured information from this pitch deck content. Return ONLY valid JSON with no markdown formatting.

{{
    "company_name": "company name or null",
    "product_overview": "1-2 sentence product summary or null",
    "problem_solution": "problem being solved and proposed solution or null",
    "key_capabilities": "main features, technology, differentiators or null",
    "team_background": "founders and key team with relevant experience or null",
    "gtm_strategy": "target market, customer segments, sales approach or null",
    "traction": "revenue, users, growth, pilots, partnerships or null",
    "fundraising": "amount raising, valuation, instrument, use of funds or null",
    "industry": "primary industry/sector (e.g. cybersecurity, fintech, healthtech) or null",
    "competitors_mentioned": ["competitor1", "competitor2"],
    "founder_names": ["First Last", "First Last"],
    "location": "HQ location or null",
    "business_model": "how they make money (SaaS, marketplace, etc.) or null",
    "target_customers": "who they sell to (enterprise, SMB, consumer, etc.) or null"
}}

For any field where information is not available in the deck, use null.

DECK CONTENT:
{content[:25000]}"""

    result = call_claude(prompt, model="claude-haiku-4-5-20251001", max_tokens=2000)

    try:
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        print(f"  Could not parse extraction: {result[:200]}", file=sys.stderr)
    return None


def format_deck_data_text(deck_data):
    """Format extracted deck data as readable text for analysis prompts."""
    parts = []
    fields = [
        ('Company', 'company_name'),
        ('Product', 'product_overview'),
        ('Problem/Solution', 'problem_solution'),
        ('Key Capabilities', 'key_capabilities'),
        ('Team', 'team_background'),
        ('GTM Strategy', 'gtm_strategy'),
        ('Traction', 'traction'),
        ('Fundraising', 'fundraising'),
        ('Industry', 'industry'),
        ('Business Model', 'business_model'),
        ('Target Customers', 'target_customers'),
        ('Location', 'location'),
    ]
    for label, key in fields:
        val = deck_data.get(key)
        if val:
            parts.append(f"{label}: {val}")

    competitors = deck_data.get('competitors_mentioned', [])
    if competitors:
        parts.append(f"Competitors Mentioned: {', '.join(competitors)}")

    founders = deck_data.get('founder_names', [])
    if founders:
        parts.append(f"Founders: {', '.join(founders)}")

    return '\n'.join(parts)


# --- Phase 2: Research ---


def build_research_queries(deck_data):
    company = deck_data.get('company_name') or ''
    industry = deck_data.get('industry') or ''
    founders = deck_data.get('founder_names') or []
    product = deck_data.get('product_overview') or ''
    target = deck_data.get('target_customers') or ''

    queries = {}

    if industry:
        queries['market_size'] = f"{industry} market size TAM 2025 2026"
        queries['industry_trends'] = f"{industry} trends growth drivers 2025 2026"
        queries['investor_landscape'] = f"{industry} VC investment funding rounds 2025"

    if company:
        queries['competitors'] = f"{company} competitors {industry} landscape".strip()
        queries['company_news'] = f"{company} startup funding news 2025 2026"

    if founders:
        queries['founder_bg'] = f"{founders[0]} founder CEO startup background"

    if industry:
        queries['comparable_exits'] = f"{industry} startup acquisitions exits M&A 2024 2025"
        bm = deck_data.get('business_model') or ''
        if 'saas' in bm.lower() or 'subscription' in bm.lower():
            queries['unit_economics'] = f"{industry} SaaS unit economics benchmarks LTV CAC"
        else:
            queries['unit_economics'] = f"{industry} startup benchmarks unit economics metrics"

    return queries


def run_research(queries):
    results = {}
    for qid, query in queries.items():
        print(f"    Searching: {query[:60]}...")
        results[qid] = brave_search(query, count=5)
        time.sleep(0.3)
    total = sum(len(v) for v in results.values())
    print(f"    Total: {total} results from {len(queries)} queries")
    return results


def format_research_for_section(research_results, relevant_keys):
    parts = []
    for key in relevant_keys:
        items = research_results.get(key, [])
        if items:
            for item in items[:4]:
                parts.append(f"- {item['title']}: {item['description']}")
    if not parts:
        return "No relevant research data available."
    return '\n'.join(parts)


# --- Phase 3: Analysis ---

SYSTEM_PROMPT = """You are a senior investment analyst combining expertise from Sequoia Capital, Andreessen Horowitz, Benchmark Capital, Accel, First Round Capital, Lightspeed Venture Partners, Insight Partners, Kleiner Perkins, GGV Capital, Tiger Global, Bessemer Venture Partners, and Index Ventures.

Your analysis must be:
- Grounded in the data provided (deck content and web research)
- Honest about gaps — explicitly state "Not available from deck — request from founders" rather than speculating or hallucinating data
- Quantitative where possible — use specific numbers, percentages, multiples, dollar figures
- Balanced — identify both strengths and risks for each section
- Actionable — end each section with 2-3 specific questions to ask the founders

When research data is provided, reference specific findings. When making estimates, clearly label them as estimates and state your confidence level (High/Medium/Low).

Format your output in clean markdown with headers, bullet points, and bold for key figures."""


ANALYSIS_SECTIONS = [
    {
        'id': 'market_sizing',
        'title': '1. Market Sizing & TAM Analysis',
        'relevant_research': ['market_size', 'industry_trends'],
        'max_tokens': 1500,
        'prompt': """Analyze the market opportunity for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

MARKET RESEARCH:
{research_data}

Provide a complete market sizing analysis:

## 1. Market Sizing & TAM Analysis

- **Total Addressable Market (TAM)**: Global market size with data sources and methodology
- **Serviceable Available Market (SAM)**: Realistic portion this startup can reach given geography, go-to-market, and product scope
- **Serviceable Obtainable Market (SOM)**: What they can capture in 3-5 years with current trajectory
- **Market growth rate**: CAGR for next 5 years with key trend drivers
- **Market segments**: Break TAM into customer types or use cases with sizing per segment
- **Bottom-up validation**: Unit economics x potential customers calculation
- **Comparable markets**: Similar industries that scaled and their trajectory
- **Red flags**: Reasons market might be smaller than claimed

End with: Is this a venture-scale market? (Yes/No) Confidence: (High/Medium/Low)
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'competitive_landscape',
        'title': '2. Competitive Landscape Analysis',
        'relevant_research': ['competitors', 'company_news'],
        'max_tokens': 1500,
        'prompt': """Analyze the competitive landscape for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

COMPETITIVE RESEARCH:
{research_data}

Provide a complete competitive analysis:

## 2. Competitive Landscape Analysis

- **Direct competitors**: Top 5 companies solving the same problem — name, funding, stage, differentiation
- **Indirect competitors**: 5 adjacent solutions customers currently use
- **Competitive positioning**: Where {company_name} fits (price vs. features matrix)
- **Moat analysis**: What makes each competitor defensible (network effects, switching costs, data, brand, IP)
- **White space**: Gaps no competitor is filling that {company_name} could own
- **Threat level**: Rate each competitor as Low/Medium/High threat with reasoning
- **Market share estimates**: Current distribution if data available
- **Strategic moves**: Recent funding, acquisitions, pivots, or partnerships by competitors

Format as competitive intelligence brief with comparison matrix.
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'founder_background',
        'title': '3. Founder Background Check',
        'relevant_research': ['founder_bg', 'company_news'],
        'max_tokens': 1500,
        'prompt': """Evaluate the founding team of {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

FOUNDER RESEARCH:
{research_data}

Provide a founder diligence assessment:

## 3. Founder Background Check

- **Professional background**: Previous companies, roles, outcomes for each founder
- **Domain expertise**: Years in industry, specific achievements, unfair insights
- **Technical capabilities**: Engineering/product skills and ability to build v1
- **Network strength**: Key relationships, advisors, investors, industry connections
- **Previous ventures**: Track record — exits, failures, learnings
- **Team dynamics**: Complementary skills, how long working together, how they met
- **Red flags**: Gaps in experience, concerning patterns, missing roles
- **Commitment level**: Full-time status, financial skin in game

Format as founder diligence memo.
Risk assessment: (Low/Medium/High) with reasoning
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'unit_economics',
        'title': '4. Unit Economics Deep Dive',
        'relevant_research': ['unit_economics', 'market_size'],
        'max_tokens': 1500,
        'prompt': """Analyze the unit economics for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

BENCHMARK RESEARCH:
{research_data}

Provide a unit economics deep dive:

## 4. Unit Economics Deep Dive

- **Customer Acquisition Cost (CAC)**: Estimate from available data or industry benchmarks
- **Lifetime Value (LTV)**: Average revenue per customer x retention period
- **LTV:CAC ratio**: Target 3:1 minimum — how does this compare?
- **Payback period**: Months to recover CAC (target <12 months)
- **Gross margin**: Revenue minus COGS as percentage
- **Contribution margin**: After all variable costs per customer
- **Burn multiple**: Net burn / net new ARR (lower is better, target <2x)
- **Path to profitability**: When unit economics turn positive at scale

Where data is missing from the deck, provide industry benchmarks for comparison and clearly label estimates.

Format as financial analysis with sensitivity analysis (optimistic/base/pessimistic).
Questions for founders: (2-3 specific questions about their actual numbers)""",
    },
    {
        'id': 'product_market_fit',
        'title': '5. Product-Market Fit Assessment',
        'relevant_research': ['competitors', 'industry_trends'],
        'max_tokens': 1500,
        'prompt': """Assess product-market fit for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

MARKET RESEARCH:
{research_data}

Provide a PMF assessment:

## 5. Product-Market Fit Assessment

- **Sean Ellis test**: Would 40%+ of users be "very disappointed" if the product disappeared? Evidence?
- **Retention signals**: Do cohorts flatten or decay? What does the deck suggest?
- **NPS indicators**: Any Net Promoter Score data or customer satisfaction signals
- **Organic growth**: What % of growth is organic/referral vs. paid acquisition
- **Usage frequency**: DAU/WAU/MAU ratios if available — how often do users engage?
- **Feature adoption**: Which features drive retention vs. vanity metrics
- **Customer testimonials**: Qualitative evidence of value delivered
- **Market pull signals**: Inbound demand, waitlist, word-of-mouth indicators

Based on available evidence, assess PMF status.

**PMF Verdict**: Pre-PMF / Emerging PMF / Strong PMF
**Confidence**: High/Medium/Low
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'traction_growth',
        'title': '6. Traction & Growth Metrics',
        'relevant_research': ['company_news', 'unit_economics'],
        'max_tokens': 1500,
        'prompt': """Analyze traction and growth for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

GROWTH RESEARCH:
{research_data}

Provide a traction analysis:

## 6. Traction & Growth Metrics Analysis

- **Revenue growth**: MoM and YoY growth rates if available
- **User growth**: New user acquisition rate and trajectory
- **Retention analysis**: Churn rates, cohort retention patterns
- **Sales efficiency**: Magic number (net new ARR / S&M spend) if calculable
- **Growth channels**: What channels work, estimated CAC by channel
- **Viral coefficient**: Does each user bring more users? Evidence?
- **Market penetration**: % of TAM/SAM captured so far
- **Leading indicators**: Signals that predict future growth acceleration or deceleration

Format as growth dashboard with trend analysis.
Growth trajectory: Accelerating / Steady / Decelerating / Too early to tell
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'financial_model',
        'title': '7. Financial Model Review',
        'relevant_research': ['unit_economics', 'comparable_exits'],
        'max_tokens': 1500,
        'prompt': """Review the financial model for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

BENCHMARK RESEARCH:
{research_data}

Provide a financial model assessment:

## 7. Financial Model Review

- **Revenue projections**: Are forecasts realistic vs. comparable companies at same stage?
- **Cost structure**: Fixed vs. variable costs breakdown and scalability
- **Burn rate**: Monthly cash consumption and implied runway
- **Capital efficiency**: Growth generated per dollar invested
- **Break-even analysis**: Revenue needed to reach profitability
- **Assumptions check**: Are growth rates, pricing, and margins reasonable?
- **Scenario modeling**: Best case / base case / worst case 3-year outcomes
- **Funding needs**: Capital required to reach next milestones and what those milestones are

Where specific financials aren't in the deck, note what's missing and provide comparable benchmarks.

Format as financial review with clearly stated assumptions.
Financial health: Strong / Adequate / Concerning / Insufficient data
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'technology_ip',
        'title': '8. Technology & IP Assessment',
        'relevant_research': ['competitors', 'industry_trends'],
        'max_tokens': 1500,
        'prompt': """Assess the technology and IP position of {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

TECHNOLOGY RESEARCH:
{research_data}

Provide a technical diligence assessment:

## 8. Technology & IP Assessment

- **Technology stack**: What they've built on and scalability implications
- **Proprietary technology**: What's unique vs. off-the-shelf components
- **IP portfolio**: Patents, trade secrets, proprietary algorithms, defensibility
- **Technical debt indicators**: Signals about engineering quality and practices
- **Data moat**: Proprietary data assets that strengthen over time with usage
- **Switching costs**: How hard is it for customers to leave once integrated?
- **Technical risks**: Dependencies, security considerations, scaling challenges
- **Team capability**: Can this team execute on the technical roadmap?

Format as technical diligence report.
Technical defensibility: Strong / Moderate / Weak / Insufficient data
Questions for founders: (2-3 specific technical questions)""",
    },
    {
        'id': 'gtm_strategy',
        'title': '9. Go-to-Market Strategy Evaluation',
        'relevant_research': ['competitors', 'market_size'],
        'max_tokens': 1500,
        'prompt': """Evaluate the go-to-market strategy for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

GTM RESEARCH:
{research_data}

Provide a GTM strategy evaluation:

## 9. Go-to-Market Strategy Evaluation

- **Customer acquisition**: What channels work and estimated CAC by channel
- **Sales model**: Self-serve, inside sales, field sales, or hybrid approach
- **Sales cycle**: Expected length and key friction points
- **Pricing strategy**: How they monetize, pricing tiers, competitive positioning on price
- **Channel partnerships**: Distribution deals, ecosystem plays, integrations
- **Marketing playbook**: What campaigns/content/events drive pipeline
- **Sales team**: Current size, productivity signals, quota attainment
- **GTM efficiency**: Sales & marketing spend as % of revenue vs. benchmarks

Format as GTM strategy review with optimization recommendations.
GTM readiness: Strong / Developing / Early / Needs rethinking
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'market_timing',
        'title': '10. Market Timing & Trend Analysis',
        'relevant_research': ['industry_trends', 'investor_landscape'],
        'max_tokens': 1500,
        'prompt': """Analyze market timing for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

TREND RESEARCH:
{research_data}

Provide a market timing analysis:

## 10. Market Timing & Trend Analysis

- **Market catalysts**: What changed recently that makes this possible now?
- **Technology enablers**: New tech that enables or improves this solution
- **Regulatory tailwinds/headwinds**: Policy changes creating opportunity or risk
- **Behavioral shifts**: Consumer/business behavior changes driving adoption
- **Why now**: Why couldn't this succeed 5 years ago? What's different?
- **Timing risks**: Is the market ready, or is this too early/too late?
- **Macro trends**: Economic, demographic, technological shifts helping or hurting
- **Competitive timing**: How long until copycats or incumbents respond?

Format as market timing memo.
Timing verdict: Perfect timing / Good timing / Slightly early / Slightly late / Wrong timing
Conviction level: High/Medium/Low
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'exit_scenarios',
        'title': '11. Exit Scenario & Return Analysis',
        'relevant_research': ['comparable_exits', 'investor_landscape'],
        'max_tokens': 1500,
        'prompt': """Analyze exit scenarios for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

EXIT RESEARCH:
{research_data}

Provide exit scenario and return analysis:

## 11. Exit Scenario & Return Analysis

- **Potential acquirers**: 10 companies that could acquire this startup and why
- **Strategic rationale**: Why each acquirer would want this asset
- **Comparable exits**: Similar companies acquired in the space — deal size and multiples
- **IPO potential**: Is this a venture-scale outcome? Could it reach $1B+ valuation?
- **Timeline to exit**: Realistic years to liquidity event (3/5/7 year scenarios)
- **Return scenarios**: At current valuation, what ownership and exit price needed for target returns
- **Exit multiples**: Revenue and EBITDA multiples for comparable exits in this space
- **Liquidation preference impact**: How deal structure affects investor returns at various exit prices

Format as return analysis with probability-weighted scenarios.
Exit attractiveness: Highly attractive / Attractive / Moderate / Challenging
Questions for founders: (2-3 specific questions)""",
    },
]

# Section 12 is the synthesis — runs after sections 1-11
SYNTHESIS_SECTION = {
    'id': 'investment_memo',
    'title': '12. Investment Memo Summary',
    'max_tokens': 2500,
    'prompt': """You have completed a comprehensive 11-section investment analysis for {company_name}. Below are all findings.

COMPANY DATA (from pitch deck):
{deck_data}

COMPLETE ANALYSIS:
{prior_analysis}

Now write the final investment memo summary that synthesizes everything:

## 12. Investment Memo Summary

### Executive Summary
3 paragraphs: (1) The problem and market opportunity, (2) The solution and why this team, (3) Why now and the investment case

### Investment Recommendation
**Recommendation**: STRONG PASS / PASS / MONITOR / INVEST / STRONG INVEST
**Conviction Level**: Low / Medium / High
**Rationale**: 2-3 sentences explaining the recommendation

### Investment Thesis (if recommending INVEST)
5 reasons this could be a $1B+ company (or explain why it can't reach that scale)

### Key Strengths (Top 5)
Ranked by importance with evidence from the analysis

### Key Risks (Top 5)
Ranked by severity with mitigation strategies

### Deal Terms Assessment
Comment on valuation, round size, and terms relative to stage and traction

### Required Milestones for Next Round
What needs to happen in 12-18 months to raise the next round at 3-5x step-up

### Critical Questions Before Proceeding
Top 5 questions that must be answered before making an investment decision

### Comparable Companies
3-5 companies at similar stage that went on to succeed or fail, and what this implies""",
}


def run_section(section, deck_data, research_results):
    """Run a single analysis section through Claude Sonnet."""
    company = deck_data.get('company_name') or 'Unknown Company'
    deck_text = format_deck_data_text(deck_data)
    research_text = format_research_for_section(research_results, section.get('relevant_research', []))

    prompt = section['prompt'].format(
        company_name=company,
        deck_data=deck_text,
        research_data=research_text,
    )

    return call_claude(prompt, SYSTEM_PROMPT, max_tokens=section['max_tokens'])


def run_analysis(deck_data, research_results, progress_phone=None):
    """Phase 3: Run sections 1-11 sequentially (API rate limit: 5 RPM), then section 12 as synthesis."""
    section_results = {}

    # Run sections 1-11 sequentially to respect API rate limits
    for i, section in enumerate(ANALYSIS_SECTIONS):
        try:
            result = run_section(section, deck_data, research_results)
            section_results[section['id']] = result
            print(f"    [{i+1}/11] {section['title']}")
        except Exception as e:
            section_results[section['id']] = f"Analysis failed: {e}"
            print(f"    [{i+1}/11] FAILED: {section['title']}: {e}", file=sys.stderr)

        # Send progress update at milestones
        if progress_phone and i in (3, 7):
            milestone = "Market, competition, team, and economics done..." if i == 3 else "Almost there — finalizing strategy and exit analysis..."
            send_whatsapp(progress_phone, milestone)

        # Small delay between calls to stay under rate limit
        if i < len(ANALYSIS_SECTIONS) - 1:
            time.sleep(2)

    # Run synthesis (section 12) with all prior results
    print("    Running synthesis...")
    company = deck_data.get('company_name') or 'Unknown Company'
    deck_text = format_deck_data_text(deck_data)

    prior_analysis = '\n\n---\n\n'.join(
        f"{s['title']}\n\n{section_results.get(s['id'], 'Analysis not available')}"
        for s in ANALYSIS_SECTIONS
    )

    synthesis_prompt = SYNTHESIS_SECTION['prompt'].format(
        company_name=company,
        deck_data=deck_text,
        prior_analysis=prior_analysis,
    )

    section_results['investment_memo'] = call_claude(
        synthesis_prompt, SYSTEM_PROMPT, max_tokens=SYNTHESIS_SECTION['max_tokens']
    )
    print("    Done: 12. Investment Memo Summary")

    # Generate TL;DR
    print("    Generating TL;DR...")
    tldr_prompt = f"""Write a single TL;DR paragraph (3-5 sentences) summarizing this investment evaluation. Include: what the company does, key traction numbers, the recommendation (invest/pass/monitor), and the top reason for that recommendation.

INVESTMENT MEMO:
{section_results['investment_memo'][:3000]}

Write ONLY the paragraph, no label or prefix."""

    section_results['tldr'] = call_claude(tldr_prompt, model="claude-haiku-4-5-20251001", max_tokens=300)
    print("    Done: TL;DR")

    return section_results


# --- Phase 4: Delivery ---


def format_full_report(deck_data, section_results):
    company = deck_data.get('company_name') or 'Unknown Company'
    date = datetime.now().strftime('%B %d, %Y')

    parts = [
        f"# Investment Analysis: {company}",
        f"*Generated: {date} | GroundUp Ventures Deal Evaluation*",
        "",
    ]

    # TL;DR at top
    tldr = section_results.get('tldr', '')
    if tldr:
        parts.extend([
            f"**TL;DR:** {tldr}",
            "",
        ])

    parts.extend(["---", ""])

    # Sections 1-11
    for section in ANALYSIS_SECTIONS:
        result = section_results.get(section['id'], 'Analysis not available for this section.')
        parts.append(result)
        parts.append("")
        parts.append("---")
        parts.append("")

    # Section 12 (synthesis)
    memo = section_results.get('investment_memo', 'Synthesis not available.')
    parts.append(memo)
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("*This analysis was generated by GroundUp's AI deal evaluation system. "
                 "All assessments should be validated through direct founder engagement "
                 "and independent due diligence.*")

    return '\n'.join(parts)


def format_whatsapp_summary(deck_data, section_results):
    company = deck_data.get('company_name') or 'Unknown Company'
    tldr = section_results.get('tldr', '')
    memo = section_results.get('investment_memo', '')
    date = datetime.now().strftime('%B %d, %Y')

    # Truncate memo to fit WhatsApp limit
    memo_text = memo[:2500] if len(memo) > 2500 else memo

    return f"""*Deal Evaluation: {company}*
{date}

*TL;DR:* {tldr}

{memo_text}

---
_Full 12-section report sent to your email._"""


def format_hubspot_note(deck_data, section_results, tldr=None):
    """Format a condensed version for HubSpot company notes."""
    company = deck_data.get('company_name') or 'Unknown Company'
    tldr = tldr or section_results.get('tldr', '')
    memo = section_results.get('investment_memo', 'No analysis available')

    parts = [
        f"DEAL EVALUATION: {company} (AI-Generated, {datetime.now().strftime('%b %d %Y')})",
        "",
    ]
    if tldr:
        parts.extend([f"TL;DR: {tldr}", ""])

    parts.append(memo[:3000])

    if len(memo) > 3000:
        parts.append("\n[Full 12-section analysis available via email]")

    return '\n'.join(parts)


def deliver_results(deck_data, section_results, phone, email=None):
    company = deck_data.get('company_name') or 'Unknown Company'

    # Resolve email
    if not email:
        member = config.get_member_by_phone(phone)
        if member:
            email = member['email']

    # WhatsApp: executive summary
    wa_summary = format_whatsapp_summary(deck_data, section_results)
    send_whatsapp(phone, wa_summary)

    # Email: full report
    if email:
        full_report = format_full_report(deck_data, section_results)
        send_email(email, f"Deal Evaluation: {company}", full_report)

    # Save state for HubSpot logging
    save_state(deck_data, section_results, section_results.get('tldr'))

    # Ask about HubSpot
    send_whatsapp(phone, f"Want me to log this analysis to HubSpot under *{company}*? Just reply 'log to hubspot'.")


# --- Entry Points ---


def quick_analyze(deck_url, phone, sender_email=None):
    """Quick extraction — sends summary via WhatsApp and asks about full report."""
    print(f"Quick analysis: {deck_url}")

    content = fetch_deck_content(deck_url, sender_email)
    if not content:
        if phone:
            send_whatsapp(phone, f"Could not access deck at {deck_url}. Check the link and try again.")
        print("ERROR: Could not fetch deck content")
        return None

    deck_data = extract_deck_data(content)
    if not deck_data or not deck_data.get('company_name'):
        if phone:
            send_whatsapp(phone, "Could not extract company information from the deck. Try a different link or format.")
        print("ERROR: Could not extract deck data")
        return None

    company = deck_data.get('company_name', 'Unknown')
    print(f"  Extracted: {company}")

    # Save state so evaluate can pick up
    save_state(deck_data)

    # Format quick summary for WhatsApp
    summary = format_deck_data_text(deck_data)
    msg = f"*Quick Analysis: {company}*\n\n{summary}\n\n---\nWant the full 12-section investment report? Just reply 'full report'."

    if phone:
        send_whatsapp(phone, msg)
    else:
        print(msg)

    return deck_data


def deep_evaluate(deck_url, notify_phone, notify_email=None):
    """Full 12-section investment analysis."""
    start_time = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting deep evaluation: {deck_url}")

    # Check if we already have extracted data from a quick analyze
    state = load_state()
    deck_data = None

    if state and state.get('deck_data', {}).get('company_name'):
        # Reuse extraction from quick_analyze if recent (within 30 minutes)
        state_time = datetime.fromisoformat(state['timestamp'])
        if (datetime.now() - state_time).total_seconds() < 1800:
            deck_data = state['deck_data']
            print(f"  Reusing extraction from quick analyze: {deck_data['company_name']}")

    if not deck_data:
        # Phase 1: Extract
        print("  Phase 1: Extracting deck data...")
        content = fetch_deck_content(deck_url)
        if not content:
            send_whatsapp(notify_phone, f"Could not access deck at {deck_url}. Check the link and try again.")
            return

        deck_data = extract_deck_data(content)
        if not deck_data or not deck_data.get('company_name'):
            send_whatsapp(notify_phone, "Could not extract company information from the deck. Try a different link or format.")
            return

    company = deck_data['company_name']
    print(f"    Company: {company}")

    # Send acknowledgment
    send_whatsapp(notify_phone, f"Evaluating *{company}*. Running 12-section deep analysis — results in 3-5 minutes.")

    # Phase 2: Research
    print("  Phase 2: Researching...")
    queries = build_research_queries(deck_data)
    research_results = run_research(queries)

    # Phase 3: Analyze
    print("  Phase 3: Running 12 analysis sections...")
    section_results = run_analysis(deck_data, research_results, progress_phone=notify_phone)

    # Phase 4: Deliver
    print("  Phase 4: Delivering results...")
    deliver_results(deck_data, section_results, notify_phone, notify_email)

    elapsed = time.time() - start_time
    print(f"  Done in {elapsed:.0f}s — {company} evaluation complete")


def log_to_hubspot(phone):
    """Log the last analysis to HubSpot."""
    state = load_state()
    if not state or not state.get('hubspot_note'):
        send_whatsapp(phone, "No recent analysis to log. Run an evaluation first.")
        return

    company_name = state['deck_data'].get('company_name', 'Unknown')
    note_text = state['hubspot_note']

    print(f"Logging to HubSpot: {company_name}")

    # Find company in HubSpot
    company_id = hubspot_search_company(company_name)
    if not company_id:
        send_whatsapp(phone, f"Could not find *{company_name}* in HubSpot. Create the company first, then try again.")
        return

    # Add note
    if hubspot_add_note(company_id, note_text):
        send_whatsapp(phone, f"Logged deal evaluation for *{company_name}* to HubSpot.")
        print(f"  Logged to HubSpot company {company_id}")
    else:
        send_whatsapp(phone, f"Failed to log to HubSpot. Try again or add manually.")
        print(f"  Failed to log to HubSpot", file=sys.stderr)


def test():
    """Test with hardcoded sample deck content."""
    phone = config.alert_phone

    sample_content = """
    FleetPulse — AI Fleet Maintenance for Logistics Companies

    THE PROBLEM
    Commercial fleet operators spend $1,200/truck/year on unplanned maintenance. 23% of
    delivery delays are caused by vehicle breakdowns. Fleet managers rely on fixed schedules
    rather than actual vehicle condition, leading to both over-maintenance (waste) and
    under-maintenance (breakdowns).

    OUR SOLUTION
    FleetPulse uses IoT sensors and predictive AI to forecast vehicle failures 2-3 weeks
    before they happen. Our platform replaces calendar-based maintenance with condition-based
    maintenance, reducing costs and eliminating surprise breakdowns.
    - Predictive failure detection across engine, transmission, brakes, electrical
    - Automated work order generation and parts pre-ordering
    - Fleet health dashboard with risk scoring per vehicle
    - Integration with major fleet management systems (Samsara, Geotab, Motive)

    MARKET OPPORTUNITY
    Fleet maintenance market: $38B in North America (2024)
    Predictive maintenance software: $6.9B globally, growing at 25% CAGR
    Connected fleet vehicles: 47M in US, growing 18% annually

    TRACTION
    - $850K ARR (grew 3.2x in 12 months)
    - 22 fleet operators (combined 14,000 trucks)
    - 94% prediction accuracy on engine failures
    - Average customer saves $340/truck/year
    - 112% net revenue retention

    TEAM
    Marcus Webb, CEO — Former VP Operations at Ryder Fleet Management, 18 years in logistics
    Priya Sharma, CTO — PhD in ML from MIT, former Tesla Autopilot team
    James Okafor, VP Sales — Scaled Samsara's enterprise segment from $2M to $18M ARR

    BUSINESS MODEL
    SaaS — per-vehicle pricing ($45/truck/month) + platform fee ($1,500-10,000/month)
    Average contract value: $95K/year
    Gross margin: 82%
    Hardware margin: 35% (optional IoT sensors at $120/unit)

    COMPETITORS
    Uptake Technologies, Samsara (expanding into maintenance), Geotab, Pitstop,
    Decisiv (legacy), Platform Science

    GO-TO-MARKET
    Enterprise field sales — fleets with 500+ trucks (top 200 operators)
    Inside sales — mid-market fleets (50-500 trucks)
    Channel partners — Samsara and Geotab integration marketplace

    FUNDRAISING
    Raising $6M Series A at $30M pre-money valuation
    Use of funds: 40% engineering (expand ML models to new vehicle types), 35% sales,
    25% customer success
    Target: 18-month runway to $3.5M ARR
    """

    print(f"Running test — analyzing FleetPulse sample deck, sending to {phone}")
    print()

    # Phase 1
    print("  Phase 1: Extracting...")
    deck_data = extract_deck_data(sample_content)
    if not deck_data:
        print("ERROR: Extraction failed")
        return
    print(f"    Extracted: {deck_data.get('company_name')}")

    # Send ack
    send_whatsapp(phone, f"[TEST] Evaluating *{deck_data['company_name']}*. Deep analysis in progress...")

    # Phase 2
    print("  Phase 2: Researching...")
    queries = build_research_queries(deck_data)
    research_results = run_research(queries)

    # Phase 3
    print("  Phase 3: Analyzing (12 sections)...")
    section_results = run_analysis(deck_data, research_results, progress_phone=phone)

    # Phase 4
    print("  Phase 4: Delivering...")
    deliver_results(deck_data, section_results, phone)

    print("\n  Test complete.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action == 'analyze':
        if len(sys.argv) < 3:
            print("Usage: analyzer.py analyze <deck-url> <phone> [sender-email]")
            sys.exit(1)
        deck_url = sys.argv[2]
        phone = sys.argv[3] if len(sys.argv) > 3 else None
        sender_email = sys.argv[4] if len(sys.argv) > 4 else None
        quick_analyze(deck_url, phone, sender_email)

    elif action == 'evaluate':
        if len(sys.argv) < 4:
            print("Usage: analyzer.py evaluate <deck-url> <phone> [email]")
            sys.exit(1)
        deck_url = sys.argv[2]
        phone = sys.argv[3]
        email = sys.argv[4] if len(sys.argv) > 4 else None
        deep_evaluate(deck_url, phone, email)

    elif action == 'log':
        phone = sys.argv[2] if len(sys.argv) > 2 else config.alert_phone
        log_to_hubspot(phone)

    elif action == 'test':
        test()

    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
