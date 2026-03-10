#!/usr/bin/env python3
"""
Ground Up Ventures — Portfolio Monitor
=======================================
Handles all portfolio company data ingestion:
  1. Email forwarding: detect portfolio domain → log touchpoint + extract metrics
  2. WhatsApp "log to [Company]" handler
  3. Health score calculation
  4. HubSpot note/property updates

Called from email-to-deal-automation.py and from WhatsApp handler.
"""

import os
import sys
import re
import json
import time
import base64
import requests
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import config

MATON_API_KEY = config.maton_api_key
ANTHROPIC_API_KEY = config.anthropic_api_key
BASE = "https://gateway.maton.ai/hubspot"
HEADERS = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}

PORTFOLIO_STAGE_ID = "1008223160"  # Portfolio Monitoring
PIPELINE_ID = "default"

# ── Domain → Company mapping ──────────────────────────────────────────────────

PORTFOLIO = {
    "axoneurotech.com":      "Axo Neurotech",
    "covenant.co":           "Covenant",
    "nowdialogue.com":       "Dialogue",
    "draftboard.com":        "Draftboard",
    "futurelot.com":         "FutureLot",
    "g2-sys.com":            "G2",
    "harbingermotors.com":   "Harbinger",
    "hellowonder.ai":        "Hello Wonder",
    "w.hellowonder.ai":      "Hello Wonder",
    "hywatts.com":           "HyWatts",
    "kelacyber.com":         "Kela",
    "lenkie.com":            "Lenkie",
    "meridianpay.com":       "Meridian",
    "ownli.co":              "Ownli",
    "panjaya.ai":            "Panjaya",
    "pillar.security":       "Pillar Security",
    "portless.com":          "Portless",
    "preql.com":             "PreQl",
    "proov.ai":              "Proov.ai",
    "real.dev":              "Real",
    "getreap.com":           "Reap",
    "refineintelligence.com":"Refine Intelligence",
    "ourritual.com":         "Ritual",
    "starcloud.com":         "StarCloud",
    "termscout.com":         "TermScout",
    "threefold.ai":          "ThreeFold",
    "triplewhale.com":       "TripleWhale",
    "unitailabs.com":        "Unit.AI",
    "weave.bio":             "Weave",
    "getzealthy.com":        "Zealthy",
    "zeromark.com":          "Zeromark",
    "phasezero.ai":          "Phase Zero",
    "nevona.ai":             "Nevona.AI",
    "callbaba.com":          "Baba",
    "dialogicaai.com":       "Dialogica",
    "konko.ai":              "Konko.AI",
    # Fund I
    "tulu.io":               "Tulu",
    "getjones.com":          "Jones",
    "optimalq.com":          "OptimalQ",
    "pipe.com":              "Pipe",
    "komodor.com":           "Komodor",
    "joinflyp.com":          "Flyp",
    "accruemoney.com":       "Accrue Savings",
    "disconetwork.com":      "Disco",
    "eliseai.com":           "EliseAI",
    "truehold.com":          "TrueHold",
    "younity.io":            "Younity",
    "prettydamnquick.com":   "PrettyDamnQuick (PDQ)",
    "dandelionenergy.com":   "Dandelion Energy",
    "gotolstoy.com":         "Tolstoy",
    "daily.co":              "Daily.co",
    "brighthire.ai":         "BrightHire",
    "buildops.com":          "BuildOps",
    "openlayer.com":         "Openlayer",
    "upfort.com":            "Upfort (fka Paladin)",
    "glass-imaging.com":     "Glass Imaging",
    "postmoda.com":          "Postmoda (fka Wardrobe)",
}

COMPANY_TO_DOMAIN = {v: k for k, v in PORTFOLIO.items()}


def extract_email_body(thread_detail: dict) -> str:
    """Extract full text body from a Gmail thread detail object."""
    texts = []

    def decode_part(part):
        data = part.get('body', {}).get('data', '')
        if data:
            try:
                decoded = base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='ignore')
                # Strip heavy HTML but keep text
                decoded = re.sub(r'<style[^>]*>.*?</style>', '', decoded, flags=re.DOTALL)
                decoded = re.sub(r'<[^>]+>', ' ', decoded)
                decoded = re.sub(r'\s+', ' ', decoded).strip()
                if decoded:
                    texts.append(decoded)
            except Exception:
                pass

    def walk_parts(payload):
        mime = payload.get('mimeType', '')
        if mime in ('text/plain', 'text/html'):
            decode_part(payload)
        for part in payload.get('parts', []):
            walk_parts(part)

    for msg in thread_detail.get('messages', []):
        walk_parts(msg.get('payload', {}))
        # Fallback to snippet
        if not texts:
            snippet = msg.get('snippet', '')
            if snippet:
                texts.append(snippet)

    return '\n\n'.join(texts)[:8000]


def lookup_domain(email_or_domain: str):
    """Return portfolio company name for an email address or domain, or None."""
    domain = email_or_domain.strip().lower()
    if "@" in domain:
        domain = domain.split("@")[-1]
    domain = re.sub(r'^www\.', '', domain)
    return PORTFOLIO.get(domain)


def fuzzy_lookup_name(company_name: str):
    """Fuzzy match a company name to a portfolio company. Returns canonical name or None."""
    name = company_name.strip().lower()
    name_nospace = re.sub(r'[\s\-_.]', '', name)

    for canonical in COMPANY_TO_DOMAIN:
        c = canonical.lower()
        c_nospace = re.sub(r'[\s\-_.]', '', c)
        # Exact match
        if c == name or c_nospace == name_nospace:
            return canonical
        # Partial match (normalized)
        if name_nospace in c_nospace or c_nospace in name_nospace:
            return canonical
    return None


# ── HubSpot helpers ───────────────────────────────────────────────────────────

def find_portfolio_company(company_name: str):
    """Find a portfolio company in HubSpot by name. Returns company dict or None."""
    resp = requests.post(
        f"{BASE}/crm/v3/objects/companies/search",
        headers=HEADERS,
        json={
            "filterGroups": [{"filters": [{"propertyName": "name", "operator": "EQ", "value": company_name}]}],
            "properties": ["name", "domain", "description"],
            "limit": 3,
        },
        timeout=10,
    )
    results = resp.json().get("results", []) if resp.status_code == 200 else []
    for r in results:
        if r.get("properties", {}).get("name", "").lower() == company_name.lower():
            return r
    return results[0] if results else None


def get_portfolio_deal(company_id: str):
    """Get the Portfolio Monitoring deal for a company."""
    resp = requests.get(
        f"{BASE}/crm/v3/objects/companies/{company_id}/associations/deals",
        headers=HEADERS, timeout=10
    )
    if resp.status_code != 200:
        return None
    for assoc in resp.json().get("results", []):
        deal_resp = requests.get(
            f"{BASE}/crm/v3/objects/deals/{assoc['id']}",
            headers=HEADERS,
            params={"properties": "dealname,dealstage,pipeline"},
            timeout=10,
        )
        if deal_resp.status_code == 200:
            d = deal_resp.json()
            if d.get("properties", {}).get("dealstage") == PORTFOLIO_STAGE_ID:
                return d
    return None


def add_note_to_company(company_id: str, note_text: str, original_date_ms: int = None):
    """Add a note to a HubSpot company. Uses original_date_ms if provided, else now."""
    ts = str(original_date_ms) if original_date_ms else str(int(datetime.now().timestamp() * 1000))
    resp = requests.post(
        f"{BASE}/crm/v3/objects/notes",
        headers=HEADERS,
        json={
            "properties": {
                "hs_timestamp": ts,
                "hs_note_body": note_text,
            },
            "associations": [{
                "to": {"id": company_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 190}],
            }],
        },
        timeout=10,
    )
    return resp.status_code in [200, 201]


def update_company_description(company_id: str, description: str):
    """Update the company description/notes field."""
    requests.patch(
        f"{BASE}/crm/v3/objects/companies/{company_id}",
        headers=HEADERS,
        json={"properties": {"description": description}},
        timeout=10,
    )


# ── AI extraction ─────────────────────────────────────────────────────────────

def extract_metrics_with_claude(content: str, company_name: str) -> dict:
    """Use Claude to extract portfolio metrics and health signals from content."""
    if not ANTHROPIC_API_KEY:
        return {}

    prompt = f"""You are analyzing a communication about {company_name}, a portfolio company.

Extract ALL metrics and signals. Return a JSON object with these fields (use null if not mentioned):
{{
  "arr": "Annual Recurring Revenue (e.g. $2.4M)",
  "mrr": "Monthly Recurring Revenue",
  "mom_growth": "Month-over-month growth rate (e.g. 15%)",
  "runway_months": "Runway in months as integer",
  "headcount": "Number of employees as integer",
  "customers": "Number of customers/users",
  "raised": "Total funding raised",
  "last_round": "Most recent funding round details",
  "good_news": ["list of positive developments"],
  "bad_news": ["list of challenges or concerns"],
  "red_flags": ["list of serious concerns needing intervention"],
  "health_score": "Your assessment: GREEN / YELLOW / RED",
  "health_reasoning": "1-2 sentences explaining the health score",
  "summary": "2-3 sentence executive summary of the update",
  "next_actions": ["suggested actions for the VC team"]
}}

CONTENT:
{content[:6000]}

Return ONLY the JSON object, no other text."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            text = resp.json()["content"][0]["text"].strip()
            # Extract JSON if wrapped in markdown
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
    except Exception as e:
        print(f"  Claude extraction error: {e}")
    return {}


def format_touchpoint_note(source: str, company_name: str, content: str, metrics: dict, original_date_str: str = None) -> str:
    """Format a HubSpot note for a portfolio touchpoint."""
    date_str = original_date_str or datetime.now().strftime("%b %d, %Y")
    lines = [
        f"PORTFOLIO UPDATE: {company_name} — {source}",
        f"Date: {date_str}",
        "",
    ]

    if metrics.get("summary"):
        lines += [f"Summary: {metrics['summary']}", ""]

    # Key metrics
    metric_lines = []
    for key, label in [
        ("arr", "ARR"), ("mrr", "MRR"), ("mom_growth", "MoM Growth"),
        ("runway_months", "Runway"), ("headcount", "Headcount"), ("customers", "Customers"),
        ("last_round", "Last Round"),
    ]:
        val = metrics.get(key)
        if val and val != "null":
            if key == "runway_months":
                metric_lines.append(f"{label}: {val} months")
            else:
                metric_lines.append(f"{label}: {val}")

    if metric_lines:
        lines += ["Metrics:"] + [f"  {m}" for m in metric_lines] + [""]

    health = metrics.get("health_score", "UNKNOWN")
    reasoning = metrics.get("health_reasoning", "")
    lines.append(f"Health: {health}" + (f" — {reasoning}" if reasoning else ""))
    lines.append("")

    if metrics.get("good_news"):
        lines += ["Good news:"] + [f"  + {g}" for g in metrics["good_news"]] + [""]
    if metrics.get("bad_news"):
        lines += ["Concerns:"] + [f"  - {b}" for b in metrics["bad_news"]] + [""]
    if metrics.get("red_flags"):
        lines += ["RED FLAGS:"] + [f"  ⚠ {r}" for r in metrics["red_flags"]] + [""]
    if metrics.get("next_actions"):
        lines += ["Suggested actions:"] + [f"  → {a}" for a in metrics["next_actions"]] + [""]

    lines += ["---", f"Source: {source}", "Logged by Christina (AI)"]
    return "\n".join(lines)


# ── Main entry points ─────────────────────────────────────────────────────────

def handle_portfolio_email(original_sender_email: str, subject: str, body: str, attachments_text: str = "", company_name_override: str = None) -> dict | None:
    """
    Check if an email is from a portfolio company and handle it.
    Called from email-to-deal-automation.py BEFORE the normal deal flow.

    Returns:
        dict with {company_name, company_id, note_id} if handled as portfolio touchpoint
        None if not a portfolio email (caller should proceed with normal deal flow)
    """
    company_name = company_name_override or lookup_domain(original_sender_email)

    # If sender is a team member (forwarded email), extract original sender from body
    if not company_name:
        # Try to find "From: name <email>" in forwarded content
        fwd_from_match = re.search(r'From:.*?[\s<]([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', body)
        if fwd_from_match:
            fwd_email = fwd_from_match.group(1)
            company_name = lookup_domain(fwd_email)
            if company_name:
                print(f"  → Matched forwarded sender {fwd_email} to {company_name}")

    # Try fuzzy matching company name from subject
    if not company_name:
        # Strip Fwd:/Re: prefixes
        clean_subj = subject
        while re.match(r'^(re|fwd|fw):\s*', clean_subj, re.IGNORECASE):
            clean_subj = re.sub(r'^(re|fwd|fw):\s*', '', clean_subj, flags=re.IGNORECASE).strip()
        # Try each word/phrase in subject against fuzzy lookup
        for word in re.split(r'[\s\-–—:,]+', clean_subj):
            if len(word) >= 3:
                match = fuzzy_lookup_name(word)
                if match:
                    company_name = match
                    print(f"  → Matched subject word \"{word}\" to {company_name}")
                    break

    if not company_name:
        return None

    print(f"  → Portfolio email detected: {company_name}")

    company = find_portfolio_company(company_name)
    if not company:
        print(f"  ✗ {company_name} not found in HubSpot")
        return None

    company_id = company["id"]
    content = f"Subject: {subject}\n\n{body}"
    if attachments_text:
        content += f"\n\nAttachment content:\n{attachments_text}"

    # Extract original email date from headers in body (e.g. "Date: Mon, 20 Jan 2025 ...")
    original_date_str = None
    original_date_ms = None
    date_header_match = re.search(r'^Date:\s*(.+)$', body, re.MULTILINE | re.IGNORECASE)
    if date_header_match:
        raw_date = date_header_match.group(1).strip()
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(raw_date)
            original_date_ms = int(dt.timestamp() * 1000)
            original_date_str = dt.strftime("%b %d, %Y")
        except Exception:
            pass

    # Extract metrics with Claude
    metrics = extract_metrics_with_claude(content, company_name)

    # Format and log note
    note_text = format_touchpoint_note("Email", company_name, content, metrics, original_date_str=original_date_str)
    success = add_note_to_company(company_id, note_text, original_date_ms=original_date_ms)

    if success:
        print(f"  ✓ Logged touchpoint for {company_name} (health: {metrics.get('health_score', 'unknown')})")
        return {
            "company_name": company_name,
            "company_id": company_id,
            "metrics": metrics,
        }
    else:
        print(f"  ✗ Failed to log note for {company_name}")
        return None


def handle_whatsapp_log(company_name_raw: str, content: str, sender_phone: str) -> dict | None:
    """
    Handle 'log to [Company Name]' WhatsApp command.
    Called when a team member sends content followed by 'log to X'.

    Returns result dict or None on failure.
    """
    company_name = fuzzy_lookup_name(company_name_raw)
    if not company_name:
        return {"error": f"'{company_name_raw}' doesn't match any portfolio company."}

    company = find_portfolio_company(company_name)
    if not company:
        return {"error": f"{company_name} found in portfolio list but not in HubSpot."}

    company_id = company["id"]
    metrics = extract_metrics_with_claude(content, company_name)
    note_text = format_touchpoint_note("WhatsApp", company_name, content, metrics)
    success = add_note_to_company(company_id, note_text)

    if success:
        return {
            "company_name": company_name,
            "company_id": company_id,
            "metrics": metrics,
        }
    return {"error": "Failed to log note to HubSpot."}


def get_portfolio_summary(company_name: str) -> str:
    """Get a summary of recent notes for a portfolio company."""
    company = find_portfolio_company(company_name)
    if not company:
        return f"No HubSpot record found for {company_name}."

    company_id = company["id"]

    # Get recent notes
    resp = requests.get(
        f"{BASE}/crm/v3/objects/companies/{company_id}/associations/notes",
        headers=HEADERS, params={"limit": 5}, timeout=10
    )
    if resp.status_code != 200:
        return f"Could not fetch notes for {company_name}."

    note_ids = [r["id"] for r in resp.json().get("results", [])]
    notes = []
    for nid in note_ids:
        nr = requests.get(
            f"{BASE}/crm/v3/objects/notes/{nid}",
            headers=HEADERS, params={"properties": "hs_note_body,hs_timestamp"}, timeout=10
        )
        if nr.status_code == 200:
            body = nr.json().get("properties", {}).get("hs_note_body", "")
            ts = nr.json().get("properties", {}).get("hs_timestamp", "")
            if body.startswith("PORTFOLIO UPDATE:"):
                notes.append(body[:1000])

    if not notes:
        return f"No portfolio updates logged for {company_name} yet."

    return f"Latest updates for {company_name}:\n\n" + "\n\n---\n\n".join(notes[:3])


if __name__ == "__main__":
    # Test domain lookup
    print("Testing domain lookup:")
    for test in ["ceo@portless.com", "update@triplewhale.com", "unknown@example.com"]:
        result = lookup_domain(test)
        print(f"  {test} → {result}")

    print("\nTesting fuzzy name lookup:")
    for test in ["portless", "Triple Whale", "StarCloud", "unknownco"]:
        result = fuzzy_lookup_name(test)
        print(f"  {test} → {result}")
