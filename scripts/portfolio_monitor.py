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
import hashlib
import logging
import tempfile
import requests
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib.structured_log import get_logger
log = get_logger("portfolio-monitor")

from lib.config import config
from lib.models import MODEL_HAIKU, ANTHROPIC_API_VERSION, ANTHROPIC_API_URL

MATON_API_KEY = config.maton_api_key
ANTHROPIC_API_KEY = config.anthropic_api_key
BASE = "https://gateway.maton.ai/hubspot"
HEADERS = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}

PORTFOLIO_STAGE_ID = "1008223160"  # Portfolio Monitoring
PIPELINE_ID = "default"

# ── Domain → Company mapping ──────────────────────────────────────────────────
# Loaded from the single-source-of-truth JSON file, plus alias domains below.

_PORTFOLIO_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'portfolio-companies.json')

def _load_portfolio_from_json() -> dict:
    """Build domain→name dict from portfolio-companies.json."""
    with open(_PORTFOLIO_JSON_PATH, 'r') as f:
        companies = json.load(f)
    mapping = {}
    for co in companies:
        domain = co.get("domain", "").strip()
        name = co.get("name", "").strip()
        if domain and name:
            mapping[domain] = name
    return mapping

PORTFOLIO = _load_portfolio_from_json()

# Alias domains not captured in the JSON (subdomains, alternate domains, etc.)
_ALIAS_DOMAINS = {
    "w.hellowonder.ai": "Hello Wonder",
}
for _alias_domain, _alias_name in _ALIAS_DOMAINS.items():
    if _alias_domain not in PORTFOLIO:
        PORTFOLIO[_alias_domain] = _alias_name

PORTFOLIO_CACHE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'portfolio-domains-cache.json')
PORTFOLIO_CACHE_TTL = 86400  # 24 hours


def _load_portfolio_cache() -> dict:
    """Load cached portfolio domains if fresh (< 24h). Returns empty dict if stale/missing."""
    try:
        with open(PORTFOLIO_CACHE_PATH, 'r') as f:
            cache = json.load(f)
        if time.time() - cache.get("timestamp", 0) < PORTFOLIO_CACHE_TTL:
            return cache.get("domains", {})
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logging.debug('Portfolio cache miss: %s', e)
    return {}


def sync_portfolio_from_hubspot() -> dict:
    """Fetch all Portfolio Monitoring deals from HubSpot, resolve associated company domains.

    Returns:
        dict of {domain: company_name} for all portfolio deals with a domain set.
        Also writes the result to the cache file.
    """
    domains = {}

    # Step 1: Search for all deals in Portfolio Monitoring stage
    try:
        resp = requests.post(
            f"{BASE}/crm/v3/objects/deals/search",
            headers=HEADERS,
            json={
                "filterGroups": [{"filters": [{"propertyName": "dealstage", "operator": "EQ", "value": PORTFOLIO_STAGE_ID}]}],
                "properties": ["dealname"],
                "limit": 100,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"  Failed to fetch portfolio deals: {resp.status_code}")
            return domains
        deals = resp.json().get("results", [])
    except Exception as e:
        print(f"  Error fetching portfolio deals: {e}")
        return domains

    print(f"  Found {len(deals)} deals in Portfolio Monitoring stage")

    # Step 2: For each deal, get associated company and its domain
    for deal in deals:
        deal_id = deal["id"]
        deal_name = deal.get("properties", {}).get("dealname", "?")
        try:
            # Get associated companies
            assoc_resp = requests.get(
                f"{BASE}/crm/v4/objects/deals/{deal_id}/associations/companies",
                headers=HEADERS, timeout=10,
            )
            if assoc_resp.status_code != 200:
                continue
            assoc_results = assoc_resp.json().get("results", [])
            if not assoc_results:
                continue

            company_id = assoc_results[0]["toObjectId"]

            # Get company details
            co_resp = requests.get(
                f"{BASE}/crm/v3/objects/companies/{company_id}",
                headers=HEADERS,
                params={"properties": "name,domain"},
                timeout=10,
            )
            if co_resp.status_code != 200:
                continue
            props = co_resp.json().get("properties", {})
            domain = (props.get("domain") or "").strip().lower()
            name = (props.get("name") or "").strip()

            if domain and name:
                # Normalize: strip www. prefix
                domain = re.sub(r'^www\.', '', domain)
                domains[domain] = name
                print(f"    {deal_name} → {name} ({domain})")
            else:
                print(f"    {deal_name} → skipped (domain={domain!r}, name={name!r})")
        except Exception as e:
            print(f"    Error processing deal {deal_id}: {e}")

    # Step 3: Write cache (atomic via temp + rename)
    try:
        cache_data = {"timestamp": time.time(), "domains": domains}
        cache_dir = os.path.dirname(PORTFOLIO_CACHE_PATH)
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix='.json', dir=cache_dir)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(cache_data, f, indent=2)
            os.replace(tmp_path, PORTFOLIO_CACHE_PATH)
        except Exception:
            os.unlink(tmp_path)
            raise
        print(f"  Cached {len(domains)} domains to {PORTFOLIO_CACHE_PATH}")
    except Exception as e:
        log.warning("Could not write portfolio cache: %s", e)

    return domains


# Merge cached HubSpot domains into PORTFOLIO (hardcoded values take precedence)
_cached_domains = _load_portfolio_cache()
if _cached_domains:
    for _domain, _name in _cached_domains.items():
        if _domain not in PORTFOLIO:
            PORTFOLIO[_domain] = _name

COMPANY_TO_DOMAIN = {v: k for k, v in PORTFOLIO.items()}

# All portfolio company names (including those without domains)
_ALL_NAMES_JSON = os.path.join(os.path.dirname(__file__), '..', 'data', 'portfolio-companies.json')
try:
    import json as _j2
    ALL_COMPANY_NAMES = {c['name'] for c in _j2.load(open(_ALL_NAMES_JSON)) if c.get('name')}
except Exception:
    ALL_COMPANY_NAMES = set(COMPANY_TO_DOMAIN.keys())


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
            except Exception as e:
                log.debug('Base64 decode error: %s', e)

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

    # Search all portfolio companies (including those without domains)
    for canonical in ALL_COMPANY_NAMES:
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
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL_HAIKU,
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

    # Append structured JSON block for machine-readable parsing
    structured = {}
    if metrics.get("arr"):
        structured["arr"] = metrics["arr"]
    if metrics.get("mrr"):
        structured["mrr"] = metrics["mrr"]
    if metrics.get("runway_months"):
        structured["runway"] = f"{metrics['runway_months']}mo"
    if metrics.get("headcount"):
        structured["headcount"] = metrics["headcount"]
    if metrics.get("mom_growth"):
        structured["mom_growth"] = metrics["mom_growth"]
    if health and health != "UNKNOWN":
        structured["health"] = health
    structured["as_of"] = date_str
    if structured:
        import json as _json
        lines.append(f"\nSOI_JSON:{_json.dumps(structured)}")

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
    # Fallback: search by domain
    if not company:
        domain = COMPANY_TO_DOMAIN.get(company_name)
        if domain:
            resp = requests.post(
                f"{BASE}/crm/v3/objects/companies/search",
                headers=HEADERS,
                json={
                    "filterGroups": [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}],
                    "properties": ["name", "domain", "description"],
                    "limit": 1,
                },
                timeout=10,
            )
            results = resp.json().get("results", []) if resp.status_code == 200 else []
            if results:
                company = results[0]
                print(f"  → Found company by domain {domain}: {company.get('properties', {}).get('name', '?')}")
    # If still not found, ask the sender via WhatsApp instead of guessing
    if not company:
        print(f"  {company_name} recognized as portfolio but not in HubSpot — asking sender")
        # Return a stub so we DON'T fall through to deal creation
        return {"company_name": company_name, "skipped": True, "ask_sender": True}

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
        except Exception as e:
            log.debug('Could not parse email date "%s": %s', raw_date, e)

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


NEWS_SEEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'portfolio-news-seen.json')


def _load_news_seen():
    """Load hash set of already-seen news URLs."""
    try:
        with open(NEWS_SEEN_PATH, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_news_seen(seen):
    """Atomically save the seen-news set."""
    data_dir = os.path.dirname(NEWS_SEEN_PATH)
    os.makedirs(data_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix='.json', dir=data_dir)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(list(seen), f)
        os.replace(tmp_path, NEWS_SEEN_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def deep_scan_portfolio():
    """Run a deep news scan for all portfolio companies.

    Searches Brave for funding, acquisition, hiring, and layoff news.
    Deduplicates against previously seen results.
    Returns list of new findings.
    """
    from lib.brave import brave_search

    seen = _load_news_seen()
    new_findings = []

    for domain, company_name in PORTFOLIO.items():
        queries = [
            f'"{company_name}" funding OR acquisition OR layoff OR hire',
            f'"{company_name}" Series OR round OR raised',
        ]

        for query in queries:
            try:
                results = brave_search(query, count=5)
                if not results:
                    continue

                web_results = results.get("web", {}).get("results", [])
                for item in web_results:
                    url = item.get("url", "")
                    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
                    if url_hash in seen:
                        continue

                    title = item.get("title", "")
                    description = item.get("description", "")
                    seen.add(url_hash)

                    new_findings.append({
                        "company": company_name,
                        "domain": domain,
                        "title": title,
                        "description": description,
                        "url": url,
                    })
                    print(f"  NEW: [{company_name}] {title[:80]}")
            except Exception as e:
                log.warning("Deep scan error for %s: %s", company_name, e)

        # Rate limit: be polite to Brave API
        time.sleep(1)

    _save_news_seen(seen)
    print(f"\nDeep scan complete: {len(new_findings)} new finding(s) across {len(PORTFOLIO)} companies")

    # Create HubSpot notes for new findings
    if new_findings and MATON_API_KEY:
        from lib.hubspot import search_company, add_note
        for finding in new_findings:
            company = search_company(name=finding["company"])
            if company:
                note_text = (
                    f"PORTFOLIO NEWS: {finding['title']}\n\n"
                    f"{finding['description']}\n\n"
                    f"Source: {finding['url']}"
                )
                add_note(company["id"], note_text, object_type="companies")
                log.info("Added news note for %s", finding["company"])

    return new_findings


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == 'sync':
        result = sync_portfolio_from_hubspot()
        print(f"Synced {len(result)} portfolio domains from HubSpot")
    elif len(sys.argv) > 1 and sys.argv[1] == 'deep-scan':
        findings = deep_scan_portfolio()
        if findings:
            print(json.dumps(findings, indent=2))
    else:
        # Test domain lookup
        print("Testing domain lookup:")
        for test in ["ceo@portless.com", "update@triplewhale.com", "unknown@example.com"]:
            result = lookup_domain(test)
            print(f"  {test} → {result}")

        print("\nTesting fuzzy name lookup:")
        for test in ["portless", "Triple Whale", "StarCloud", "unknownco"]:
            result = fuzzy_lookup_name(test)
            print(f"  {test} → {result}")
