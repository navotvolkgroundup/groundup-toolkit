#!/usr/bin/env python3
"""
Deal Analyzer v2 — Deep investment evaluation from pitch decks.

Phases:
  1. EXTRACT  — Fetch deck content, extract structured data (Haiku)
  2. RESEARCH — Web research via Brave Search (8 queries)
  3. ANALYZE  — 12-section VC analysis in parallel (Sonnet)
  4. DELIVER  — WhatsApp summary + email full report

Usage:
  python3 analyzer.py analyze <deck-url-or-path> [sender-email]
  python3 analyzer.py evaluate <deck-url-or-path> <phone> [email]
  python3 analyzer.py test
"""

import sys
import os
import json
import time
import tempfile
import sqlite3
import requests
from datetime import datetime

_session = requests.Session()

# Load shared config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config
from lib.claude import call_claude
from lib.whatsapp import send_whatsapp
from lib.email import send_email
from lib.hubspot import search_company as _search_company, add_note as _add_note

# --- Constants ---
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(_DATA_DIR, "deal-analyzer-state.json")
DEMO_STATE_FILE = os.path.join(_DATA_DIR, "deal-analyzer-demo.json")

# --- Modules ---
# Import pipeline modules (they use deferred imports back to this file for shared helpers)
from modules.deck_extractor import (
    extract_deck_links, fetch_deck_content, extract_deck_data, format_deck_data_text,
)
from modules.market_researcher import (
    build_research_queries, run_research, format_research_for_section,
)
from modules.section_analyzer import (
    SYSTEM_PROMPT, ANALYSIS_SECTIONS, SYNTHESIS_SECTION, run_section, run_analysis,
)
from modules.report_generator import (
    html_escape, markdown_to_html, format_report_html, create_google_doc,
    format_full_report, format_whatsapp_summary, format_hubspot_note,
    format_email_with_link, deliver_results,
)


def _call_claude_with_retry(prompt, system_prompt=None, model=None, max_tokens=None, max_retries=3):
    """Call Claude with retry logic and timeout."""
    kwargs = {}
    if system_prompt is not None:
        kwargs['system_prompt'] = system_prompt
    if model is not None:
        kwargs['model'] = model
    if max_tokens is not None:
        kwargs['max_tokens'] = max_tokens
    for attempt in range(max_retries):
        try:
            result = call_claude(prompt, **kwargs)
            if result:
                return result
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                print(f"  Claude call failed (attempt {attempt + 1}/{max_retries}): {e}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Claude call failed after {max_retries} attempts: {e}", file=sys.stderr)
                return None
    return None


# --- Audit Logging ---

AUDIT_DB = os.path.join(_DATA_DIR, "deal-analyzer-audit.db")


def _init_audit_db():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        company_name TEXT,
        deck_url TEXT,
        sender_email TEXT,
        sender_phone TEXT,
        doc_url TEXT,
        tldr TEXT,
        sections_json TEXT,
        duration_seconds REAL
    )''')
    conn.commit()
    conn.close()


def _log_audit(company_name, deck_url, sender_email, sender_phone, doc_url, tldr, section_results, duration):
    try:
        _init_audit_db()
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute(
            '''INSERT INTO analyses (timestamp, company_name, deck_url, sender_email, sender_phone, doc_url, tldr, sections_json, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (datetime.now().isoformat(), company_name, deck_url, sender_email, sender_phone, doc_url, tldr,
             json.dumps(section_results) if section_results else None, duration)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  Audit log error: {e}", file=sys.stderr)


# --- State Management ---


def save_state(deck_data, section_results=None, tldr=None, deck_url=None, doc_url=None):
    """Save analysis state so the log action can read it later."""
    state = {
        'deck_data': deck_data,
        'tldr': tldr,
        'timestamp': datetime.now().isoformat(),
    }
    if deck_url:
        state['deck_url'] = deck_url
    if doc_url:
        state['doc_url'] = doc_url
    if section_results:
        state['hubspot_note'] = format_hubspot_note(deck_data, section_results, tldr, doc_url=doc_url)
    # Write atomically with restricted permissions (owner-only)
    fd, tmp_path = tempfile.mkstemp(suffix='.json', prefix='deal-state-', dir='/tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_state():
    """Load the last analysis state."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# --- Demo State ---


def save_demo_state(phone, email=None, phase="konko"):
    """Activate demo mode."""
    state = {"active": True, "phone": phone, "email": email, "phase": phase, "started": datetime.now().isoformat()}
    fd, tmp = tempfile.mkstemp(suffix='.json', prefix='demo-state-', dir='/tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, DEMO_STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_demo_state():
    """Check if demo mode is active. Returns state dict or None."""
    try:
        with open(DEMO_STATE_FILE) as f:
            state = json.load(f)
        if state.get("active"):
            return state
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def clear_demo_state():
    """Deactivate demo mode."""
    try:
        os.unlink(DEMO_STATE_FILE)
    except FileNotFoundError:
        pass


# --- HubSpot Integration ---


def hubspot_search_company(company_name):
    """Search HubSpot for a company by name. Returns company ID or None."""
    result = _search_company(name=company_name)
    return result['id'] if result else None


def hubspot_add_note(company_id, note_text):
    """Add a note to a HubSpot company."""
    return _add_note(company_id, note_text, object_type="companies")


def hubspot_create_company(name, domain=None, industry=None):
    """Create a company in HubSpot. Returns company ID or None."""
    if not MATON_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}
    properties = {"name": name}
    if domain:
        properties["domain"] = domain
    if industry:
        properties["industry"] = industry
    try:
        response = _session.post(
            f"{MATON_BASE_URL}/companies",
            headers=headers,
            json={"properties": properties},
            timeout=10,
        )
        if response.status_code in (200, 201):
            return response.json().get('id')
        print(f"  HubSpot create company failed: HTTP {response.status_code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  HubSpot create error: {e}", file=sys.stderr)
        return None


def hubspot_create_deal(deal_name, pipeline="default", stage=None, company_id=None, amount=None):
    """Create a deal in HubSpot. Returns deal ID or None."""
    if not MATON_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}
    properties = {"dealname": deal_name, "pipeline": pipeline}
    if stage:
        properties["dealstage"] = stage
    if amount:
        properties["amount"] = str(amount)

    payload = {"properties": properties}
    if company_id:
        payload["associations"] = [{
            "to": {"id": company_id},
            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 5}]
        }]

    try:
        response = _session.post(
            f"{MATON_BASE_URL}/deals",
            headers=headers,
            json=payload,
            timeout=10,
        )
        if response.status_code in (200, 201):
            return response.json().get('id')
        print(f"  HubSpot create deal failed: HTTP {response.status_code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  HubSpot deal error: {e}", file=sys.stderr)
        return None


# HubSpot API config (used by hubspot_create_company/deal — demo mode only)
MATON_API_KEY = config.maton_api_key if hasattr(config, 'maton_api_key') else os.getenv("MATON_API_KEY", "")
MATON_BASE_URL = config.hubspot_api_gateway if hasattr(config, 'hubspot_api_gateway') else 'https://gateway.maton.ai/hubspot'


# --- Entry Points ---


def quick_analyze(deck_url, phone, sender_email=None):
    """Quick extraction — sends summary via WhatsApp and asks about full report."""
    # Demo mode — use pre-cached data instead of real fetch
    demo = load_demo_state()
    if demo:
        demo_phone = demo.get("phone") or phone
        phase = demo.get("phase", "konko")

        if phase == "konko":
            deck_data = DEMO_DECK_DATA
            company_name = "Konko AI"
            domain = "konko.ai"
            industry = "HOSPITAL_HEALTH_CARE"
            deal_name = "Konko AI — Seed"
            amount = 4000000
        else:
            deck_data = DEMO_NOOVOX_DECK_DATA
            company_name = "Noovox"
            domain = "noovox.com"
            industry = "COMPUTER_SOFTWARE"
            deal_name = "Noovox — Seed"
            amount = 2000000

        # Create HubSpot company + deal
        company_id = hubspot_search_company(company_name)
        if not company_id:
            company_id = hubspot_create_company(company_name, domain=domain, industry=industry)
        if company_id:
            hubspot_create_deal(deal_name, stage="qualifiedtobuy", company_id=company_id, amount=amount)

        save_state(deck_data)

        # Send directly via WhatsApp with formatted summary
        if phase == "konko":
            summary = """*Product:* AI-powered patient coordinator (Kora) that automates appointment booking via WhatsApp for LATAM clinics

*Problem:* 95% of clinic scheduling in Latin America is still manual. Doctors waste 40% of their time on admin

*Traction:* $0 → $520K ARR in 9 months, 2x QoQ growth, 53 customers, 500K+ patient interactions

*Team:* Jean Marc Goguikian (CEO) — BCG, Harvard MBA, clinic owner who 3x'd his own bookings. Michael Haddad (CTO) — C3.ai, Tesla, Harvard MBA

*Fundraising:* $4M seed round (+$1.1M prior). 18-month runway targeting $5M ARR

*Business Model:* SaaS — $795/month per clinic, 30% revenue uplift for clients within 60 days"""
        else:
            summary = """*Product:* First OS for executive-led growth — orchestrate, govern, and measure executives' thought leadership at scale

*Problem:* 95% of hidden buyers say thought leadership makes them receptive to sales, but 71% never interact with sales. Companies lack tools to scale executive content

*Traction:* $20K ARR in first month, 13 enterprise customers (12-month commitments), 100+ waitlist

*Team:* Andres Prilloltensky (CEO), balanced team with CPO, CTO, marketing, and AI leads. Israel-based, US/EU GTM

*Fundraising:* Raising $2M seed. Target: 15-18 months to $1.6M ARR and 120+ paying companies

*Business Model:* SaaS — $50/month/user ($250/month for 5 users), enterprise 12-month commitments"""

        send_whatsapp(demo_phone, f"""Done! Created *{company_name}* in HubSpot.

*Quick Summary: {company_name}*

{summary}

---
Want the full 12-section investment report?""")
        # Tell agent messages were already sent
        print("DELIVERED: Quick summary sent to WhatsApp and HubSpot records created. Do not send any additional messages.")
        return deck_data

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

    # Audit log
    _log_audit(
        company_name=company, deck_url=deck_url, sender_email=notify_email,
        sender_phone=notify_phone, doc_url=None, tldr=section_results.get('tldr'),
        section_results=section_results, duration=elapsed,
    )


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


def full_report(phone, email=None):
    """Run full 12-section evaluation from saved state (no URL needed)."""
    # Check demo mode — use pre-cached data instead of real analysis
    demo = load_demo_state()
    if demo:
        phase = demo.get("phase", "konko")
        demo_phone = demo.get("phone") or phone
        demo_email = demo.get("email") or email
        if phase == "konko":
            demo_report(demo_phone, demo_email)
        else:
            demo_report_noovox(demo_phone, demo_email)
        return

    state = load_state()
    if not state or not state.get('deck_data', {}).get('company_name'):
        send_whatsapp(phone, "No recent deck analysis found. Send a deck link first.")
        return

    # Check state is recent (within 2 hours)
    state_time = datetime.fromisoformat(state['timestamp'])
    if (datetime.now() - state_time).total_seconds() > 7200:
        send_whatsapp(phone, "Last analysis is too old. Send a new deck link to start fresh.")
        return

    deck_data = state['deck_data']
    deck_url = state.get('deck_url')
    company = deck_data['company_name']

    start_time = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Full report from state: {company}")

    send_whatsapp(phone, f"Evaluating *{company}*. Running 12-section deep analysis — results in 3-5 minutes.")

    # Phase 2: Research
    print("  Phase 2: Researching...")
    queries = build_research_queries(deck_data)
    research_results = run_research(queries)

    # Phase 3: Analyze
    print("  Phase 3: Running 12 analysis sections...")
    section_results = run_analysis(deck_data, research_results, progress_phone=phone)

    # Phase 4: Deliver
    print("  Phase 4: Delivering results...")
    deliver_results(deck_data, section_results, phone, email)

    elapsed = time.time() - start_time
    print(f"  Done in {elapsed:.0f}s — {company} full report complete")

    # Audit log
    _log_audit(
        company_name=company, deck_url=deck_url, sender_email=email,
        sender_phone=phone, doc_url=None, tldr=section_results.get('tldr'),
        section_results=section_results, duration=elapsed,
    )


# --- Demo Mode (LP Meeting) ---

DEMO_DECK_DATA = {
    "company_name": "Konko AI",
    "product_overview": "AI-powered patient coordinator (Kora) that automates appointment booking and healthcare administration through WhatsApp for Latin American clinics.",
    "problem_solution": "95% of clinic scheduling in Latin America is still manual via WhatsApp, and doctors waste 40% of their time on admin. Konko's AI agent Kora automates patient conversations, appointment scheduling, and info gathering directly through WhatsApp — achieving 67% full automation and delivering 30% revenue uplift within 60 days.",
    "key_capabilities": "WhatsApp-native AI patient coordinator, event-driven multi-agent architecture, 67% full automation rate, <1 hour setup, 34-second average first response time, handles scheduling intent detection, info gathering, and appointment booking",
    "team_background": "Jean Marc Goguikian (CEO) — BCG consultant, Harvard MBA, clinic owner who tripled his own clinic's bookings using AI. Michael Haddad (CTO) — enterprise AI experience from C3.ai and Tesla, Harvard MBA.",
    "gtm_strategy": "Founder-led sales targeting Latin American private clinics. Started with small/mid-sized clinics at $795/month. Expanding to large clinic networks. WhatsApp-first approach matches regional communication patterns (85%+ WhatsApp penetration in LATAM).",
    "traction": "$0 to $520K ARR in 9 months, 2x quarter-over-quarter growth, 53 customers, 500K+ patient interactions, 30% revenue uplift for clients within 60 days, 2-month payback period",
    "fundraising": "Raising $4M seed round (plus prior $1.1M). 18-month runway targeting $5M ARR.",
    "industry": "Healthtech / Healthcare AI",
    "competitors_mentioned": ["Assort", "Tennr", "Freed"],
    "founder_names": ["Jean Marc Goguikian", "Michael Haddad"],
    "location": "Latin America",
    "business_model": "SaaS — $795/month per clinic, with potential for higher ARPU on larger practices",
    "target_customers": "Private clinics and medical practices in Latin America (small, mid-sized, and large)"
}

DEMO_GOOGLE_DOC_URL = "https://docs.google.com/document/d/1qRucJuK9DRVyDqHXpcpMPIXRwSBl-zDjOHVtALqsJZM/edit"

DEMO_TLDR = (
    "Konko AI builds an AI-powered patient coordinator that automates appointment booking and "
    "healthcare administration through WhatsApp for Latin American clinics, addressing a $150B regional "
    "market where 95% of scheduling remains manual. The company grew from $0 to $520K ARR in just 9 months "
    "with 2x quarter-over-quarter growth across 53 customers and 500K+ patient interactions, delivering "
    "30% revenue uplift to clients within 60 days. Recommendation: STRONG INVEST — perfect market timing, "
    "world-class founders with domain expertise (CEO tripled his own clinic's bookings), and an 18-24 month "
    "competitive window in an underserved market."
)

DEMO_HUBSPOT_NOTE = f"""DEAL EVALUATION: Konko AI (AI-Generated, {datetime.now().strftime('%b %d %Y')})

Full report: {DEMO_GOOGLE_DOC_URL}

TL;DR: {DEMO_TLDR}

## Investment Memo Summary

### Executive Summary
Latin America's healthcare system spends $150B annually on administration, with 95% of appointments still booked manually via WhatsApp. Doctors waste 40% of their time on admin tasks. Konko AI's Kora platform automates patient coordination directly through WhatsApp, achieving 67% full automation and 30% revenue uplift for clinics within 60 days.

The founding team combines exceptional domain expertise — CEO Jean Marc Goguikian (BCG, Harvard MBA) tripled his own clinic's bookings using AI, while CTO Michael Haddad brings enterprise AI experience from C3.ai and Tesla. Their event-driven multi-agent architecture configures in under an hour.

Perfect market timing: generative AI reaching production readiness, WhatsApp Business API maturing, and post-COVID healthcare digitization accelerating. $0 to $520K ARR in 9 months with 2x QoQ growth across 53 customers and 500K+ patient interactions.

### Investment Recommendation
**Recommendation**: STRONG INVEST
**Conviction Level**: High
**Rationale**: Exceptional early traction validates strong product-market fit in a massive underserved market, with world-class founders executing flawlessly during the optimal timing window for healthcare AI adoption.

### Key Strengths
1. Exceptional traction velocity — $0 to $520K ARR in 9 months with 2x QoQ growth
2. Unique positioning — only player targeting LATAM clinics with WhatsApp-native AI coordination
3. Compelling value prop — 30% revenue uplift and 2-month payback period
4. Strong founding team — domain expertise (clinic owner) + enterprise AI (C3.ai, Tesla) + Harvard MBAs
5. Large underserved market — $150B admin spend with 95% manual processes

### Key Risks
1. Platform dependency — heavy reliance on WhatsApp Business API (Meta could change terms)
2. Geographic concentration — economically volatile Latin American markets, currency risk
3. Competitive moat — basic chatbot competitors could emerge, though 67% automation rate provides defensibility
4. Scaling challenges — founder-led sales model may create bottlenecks
5. Regulatory uncertainty — healthcare AI regulation varies by country in LATAM"""


DEMO_NOOVOX_DECK_DATA = {
    "company_name": "Noovox",
    "product_overview": "The first operating system purpose-built for executive-led growth — an end-to-end platform to orchestrate, govern, and measure the impact of executives' thought leadership content.",
    "problem_solution": "B2B playbook is broken: 95% of hidden buyers say thought leadership makes them more receptive to sales, but 71% never interact with sales. Companies want executive-led growth but face workflow bottlenecks, generic content, and brand/compliance risk. Noovox provides AI-powered executive workspace + org control center to orchestrate authentic thought leadership at scale.",
    "key_capabilities": "AI ideation & content creation, authentic voice personalization, multi-executive orchestration, brand & risk management, team enablement & advocacy, engagement & network insights, performance analytics, multi-agent infrastructure with proprietary executive voice models",
    "team_background": "Andres Prilloltensky (CEO) — experienced founder. Balanced founding team including CPO (Eran Ben Yehoshua), CTO (Uri Cusnir), Marketing Strategist (Yael Klass), B2B Marketing Executive (Nira Frenkel), AI & Data Lead (Aviv Peleg), plus 3 additional team members.",
    "gtm_strategy": "Direct enterprise sales targeting B2B companies in North America and EMEA. Waitlist-driven launch strategy. Phase 1 (now): secure wedge with V2 personalization engine and early monetization. Phase 2 (Q3/26): CRM/Slack integrations, full monetization. Phase 3 (Q4/26+): social listening, cross-platform support.",
    "traction": "$20K ARR within first month of monetization, 13 paying enterprise customers on 12-month commitments, 100+ companies on waitlist, 8-10 paying executives on individual plans",
    "fundraising": "Raising $2M seed round. Target dilution: 15-20%. Min checks: $500K for funds, $100K for angels. 15-18 months to $1.6M ARR and 120+ paying companies.",
    "industry": "SaaS / B2B Marketing Technology / Executive Growth Platform",
    "competitors_mentioned": ["Hootsuite", "Sprout Social", "Jasper", "Copy.ai", "LinkedIn native tools"],
    "founder_names": ["Andres Prilloltensky"],
    "location": "Israel (HQ), US/EU GTM focus",
    "business_model": "SaaS subscription — $50/month/user ($250/month for 5 users), enterprise customers on 12-month commitments",
    "target_customers": "B2B companies with 100+ employees, marketing and communications teams, enterprises needing multi-executive thought leadership"
}

DEMO_NOOVOX_GOOGLE_DOC_URL = "https://docs.google.com/document/d/1qRucJuK9DRVyDqHXpcpMPIXRwSBl-zDjOHVtALqsJZM/edit"

DEMO_NOOVOX_TLDR = (
    "Noovox is building the first OS for executive-led growth — a SaaS platform helping B2B companies "
    "orchestrate, govern, and measure executive thought leadership at scale. Early traction ($20K ARR, "
    "13 enterprise customers, 100+ waitlist) shows initial interest but remains very early-stage. "
    "The TAM ($180-360M) is narrow for venture scale without significant category expansion, the founding "
    "team lacks proven startup exits, and $20K ARR after months of selling signals slow adoption. "
    "The executive-led growth category is unproven and may remain a feature rather than a standalone platform. "
    "Recommendation: PASS — revisit at Series A if they demonstrate stronger growth velocity and TAM expansion."
)

DEMO_NOOVOX_HUBSPOT_NOTE = f"""DEAL EVALUATION: Noovox (AI-Generated, {datetime.now().strftime('%b %d %Y')})

Full report: {DEMO_NOOVOX_GOOGLE_DOC_URL}

TL;DR: {DEMO_NOOVOX_TLDR}

## Investment Memo Summary

### Executive Summary
Noovox is building the first operating system for executive-led growth, enabling B2B companies to orchestrate and measure their executives' thought leadership at scale. The platform combines an AI-powered executive workspace with an organizational control center for governance and analytics.

The team is Israel-based with a balanced mix of product, engineering, marketing, and AI expertise, led by CEO Andres Prilloltensky. They've secured 13 enterprise customers on 12-month commitments and have 100+ companies on their waitlist, but revenue remains very early at $20K ARR.

### Investment Recommendation
**Recommendation**: PASS
**Conviction Level**: Medium
**Rationale**: While the vision of systematizing executive-led growth is compelling, the narrow TAM, early-stage traction, and unproven category make this too risky at the current valuation. The $20K ARR after active selling suggests product-market fit is not yet established.

### Key Concerns
1. Narrow TAM — $180-360M addressable market is small for venture-scale returns without major category expansion
2. Very early traction — $20K ARR with 13 customers doesn't yet validate willingness to pay at scale
3. Unproven category — "executive-led growth" may remain a feature within existing marketing suites rather than a standalone platform
4. Competitive risk — LinkedIn, Hootsuite, and AI content tools could add similar features as product extensions
5. Founding team — no prior exits or proven startup track record at scale

### What Would Change Our Mind
1. Demonstrating $200K+ ARR with clear month-over-month growth acceleration
2. Evidence that the category is real — multiple funded startups or enterprise budget line items for executive-led growth
3. Expansion into adjacent use cases that significantly increase TAM
4. Strategic partnerships that validate the platform approach over point solutions"""


def run_demo(phone, email=None):
    """LP demo — arm demo mode. No messages sent. The flow starts when you send a WhatsApp message."""
    if not phone:
        print("ERROR: Phone number required for demo")
        print("Usage: deal-analyzer demo <phone> [email]")
        sys.exit(1)

    save_demo_state(phone, email, phase="konko")
    print("Demo mode armed (2 deals: Konko AI → Noovox).")
    print("  Phase 1: Send a deck URL → Konko AI quick summary → 'full report' → STRONG INVEST")
    print("  Phase 2: Send another deck URL → Noovox quick summary → 'full report' → PASS")
    print("  Then 'end demo' to stop.")


def demo_report(phone, email=None):
    """Demo step 2: Send evaluation via WhatsApp, log to HubSpot, send email."""
    # Progress messages
    send_whatsapp(phone, "Running deep analysis on *Konko AI*...")
    time.sleep(5)

    send_whatsapp(phone, "Market, competition, team, and economics done...")
    time.sleep(5)

    send_whatsapp(phone, "Almost there — finalizing strategy and exit analysis...")
    time.sleep(5)

    # Send evaluation via WhatsApp
    send_whatsapp(phone, f"""*Deal Evaluation: Konko AI*
{datetime.now().strftime('%B %d, %Y')}

*TL;DR:* {DEMO_TLDR}

*Full Report:* {DEMO_GOOGLE_DOC_URL}""")

    # Log to HubSpot
    company_id = hubspot_search_company("Konko AI")
    if company_id:
        hubspot_add_note(company_id, DEMO_HUBSPOT_NOTE)

    send_whatsapp(phone, "Logged deal evaluation for *Konko AI* to HubSpot. \u2713")

    # Send email if provided
    if email:
        email_body = f"""Deal Evaluation: Konko AI
{datetime.now().strftime('%B %d, %Y')}

TL;DR
{DEMO_TLDR}

Full 12-Section Report
{DEMO_GOOGLE_DOC_URL}

---
This analysis was generated by GroundUp's AI deal evaluation system.
All assessments should be validated through direct founder engagement and independent due diligence."""
        send_email(email, "Deal Evaluation: Konko AI", email_body)

    # Advance demo to Noovox phase
    demo = load_demo_state()
    if demo:
        save_demo_state(demo["phone"], demo.get("email"), phase="noovox")

    # Tell agent messages were already sent
    print("DELIVERED: Full evaluation sent to WhatsApp, logged to HubSpot, email sent. Do not send any additional messages.")


def demo_report_noovox(phone, email=None):
    """Demo Noovox evaluation — PASS recommendation."""
    # Progress messages
    send_whatsapp(phone, "Running deep analysis on *Noovox*...")
    time.sleep(5)

    send_whatsapp(phone, "Market, competition, team, and economics done...")
    time.sleep(5)

    send_whatsapp(phone, "Almost there — finalizing strategy and exit analysis...")
    time.sleep(5)

    # Send evaluation via WhatsApp
    send_whatsapp(phone, f"""*Deal Evaluation: Noovox*
{datetime.now().strftime('%B %d, %Y')}

*TL;DR:* {DEMO_NOOVOX_TLDR}

*Full Report:* {DEMO_NOOVOX_GOOGLE_DOC_URL}""")

    # Log to HubSpot
    company_id = hubspot_search_company("Noovox")
    if company_id:
        hubspot_add_note(company_id, DEMO_NOOVOX_HUBSPOT_NOTE)

    send_whatsapp(phone, "Logged deal evaluation for *Noovox* to HubSpot. \u2713")

    # Send email if provided
    if email:
        email_body = f"""Deal Evaluation: Noovox
{datetime.now().strftime('%B %d, %Y')}

TL;DR
{DEMO_NOOVOX_TLDR}

Full 12-Section Report
{DEMO_NOOVOX_GOOGLE_DOC_URL}

---
This analysis was generated by GroundUp's AI deal evaluation system.
All assessments should be validated through direct founder engagement and independent due diligence."""
        send_email(email, "Deal Evaluation: Noovox", email_body)

    # Tell agent messages were already sent
    print("DELIVERED: Full evaluation sent to WhatsApp, logged to HubSpot, email sent. Do not send any additional messages.")


def demo_end():
    """End demo mode."""
    demo = load_demo_state()
    if not demo:
        print("Demo mode is not active.")
        return
    clear_demo_state()
    print("Demo mode ended.")


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

    elif action == 'full-report':
        phone = sys.argv[2] if len(sys.argv) > 2 else config.alert_phone
        email = sys.argv[3] if len(sys.argv) > 3 else None
        full_report(phone, email)

    elif action == 'log':
        phone = sys.argv[2] if len(sys.argv) > 2 else config.alert_phone
        log_to_hubspot(phone)

    elif action == 'demo':
        phone = sys.argv[2] if len(sys.argv) > 2 else None
        email = sys.argv[3] if len(sys.argv) > 3 else None
        run_demo(phone, email)

    elif action == 'end-demo':
        demo_end()

    elif action == 'test':
        test()

    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
