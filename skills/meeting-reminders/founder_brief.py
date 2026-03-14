#!/usr/bin/env python3
"""
Founder Deep Brief — auto-generated dossier before external meetings.

Extends meeting-reminders: runs 30 min before meetings with external attendees.
Gathers LinkedIn (via Camofox), Brave Search, HubSpot, Gmail, and calendar data,
then synthesizes everything with Claude into a scannable WhatsApp brief.
"""

import os
import sys
import json
import sqlite3
import subprocess
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import pytz
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config
from lib.whatsapp import send_whatsapp
from lib.gws import gws_calendar_events, gws_gmail_search, gws_gmail_thread_get
from lib.hubspot import (
    search_company as _search_company, get_deals_for_company,
    get_latest_note as _get_latest_note
)
from lib.brave import brave_search
from lib.claude import call_claude

WHATSAPP_ACCOUNT = config.whatsapp_account

_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, mode=0o700, exist_ok=True)
BRIEF_DB_PATH = os.path.join(_DATA_DIR, "founder-briefs.db")

TEAM_MEMBERS = {}
for m in config.team_members:
    TEAM_MEMBERS[m['email']] = {
        'name': m['name'].split()[0],
        'full_name': m['name'],
        'phone': m['phone'],
        'timezone': m['timezone'],
        'enabled': m.get('reminders_enabled', True),
    }

TEAM_EMAILS = set(TEAM_MEMBERS.keys())
TEAM_DOMAIN = config.team_domain

# Brief window: 25-35 min before meeting (cron runs every 5 min)
BRIEF_WINDOW_START = 35
BRIEF_WINDOW_END = 25

LINKEDIN_PROFILE = "linkedin"
LINKEDIN_RATE_LIMIT_SECS = 5


# ─── Database ───────────────────────────────────────────────────

class BriefDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init()

    def _init(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sent_briefs (
                event_id TEXT NOT NULL,
                email TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (event_id, email)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS founder_cache (
                email TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        conn.execute('DELETE FROM sent_briefs WHERE sent_at < ?', (cutoff,))
        conn.commit()
        conn.close()

    def is_sent(self, event_id, email):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT 1 FROM sent_briefs WHERE event_id = ? AND email = ?',
            (event_id, email)
        ).fetchone()
        conn.close()
        return row is not None

    def mark_sent(self, event_id, email):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT OR REPLACE INTO sent_briefs (event_id, email, sent_at) VALUES (?, ?, ?)',
            (event_id, email, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()

    def get_cached_founder(self, email, max_age_days=7):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT data, updated_at FROM founder_cache WHERE email = ?',
            (email.lower(),)
        ).fetchone()
        conn.close()
        if row:
            updated = datetime.fromisoformat(row[1])
            if datetime.now(timezone.utc) - updated < timedelta(days=max_age_days):
                return json.loads(row[0])
        return None

    def cache_founder(self, email, data):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT OR REPLACE INTO founder_cache (email, data, updated_at) VALUES (?, ?, ?)',
            (email.lower(), json.dumps(data), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()


# ─── LinkedIn via Camofox ───────────────────────────────────────

def _run_browser(cmd, timeout=30):
    """Run an openclaw browser command and return stdout."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            return None
        out = result.stdout.strip()
        # Strip any non-JSON prefix (e.g. doctor warnings banner)
        if out and "--json" in cmd:
            json_start = out.find("{")
            if json_start > 0:
                out = out[json_start:]
        return out
    except Exception as e:
        print(f"    Browser cmd error: {e}", file=sys.stderr)
        return None


def _linkedin_search_query(encoded_query):
    """Navigate to LinkedIn search and extract profile URLs."""
    url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_query}"
    _run_browser([
        'openclaw', 'browser', 'navigate',
        '--browser-profile', LINKEDIN_PROFILE, url
    ], timeout=30)
    time.sleep(6)

    js_fn = 'Array.from(document.querySelectorAll("a")).filter(a=>a.href.includes("/in/")).slice(0,10).map(a=>a.href)'
    result = _run_browser([
        'openclaw', 'browser', 'evaluate',
        '--browser-profile', LINKEDIN_PROFILE,
        '--fn', js_fn, '--json'
    ], timeout=30)

    if not result:
        return []
    try:
        data = json.loads(result)
        urls = data.get("result", [])
        seen = set()
        clean = []
        for u in urls:
            base = re.sub(r"\?.*", "", u)
            if base not in seen and "/in/" in base:
                seen.add(base)
                clean.append(base)
        return clean
    except Exception:
        return []


def linkedin_search(name, company=None):
    """Search LinkedIn for a person. Returns list of profile URL strings.

    Tries name+company first; falls back to name-only if no results.
    """
    import urllib.parse

    if company:
        encoded = urllib.parse.quote(f"{name} {company}")
        results = _linkedin_search_query(encoded)
        if results:
            return results
        print(f"    LinkedIn: no results for name+company, retrying name only...")
        time.sleep(LINKEDIN_RATE_LIMIT_SECS)

    encoded = urllib.parse.quote(name)
    return _linkedin_search_query(encoded)


def linkedin_profile(url):
    """Navigate to a LinkedIn profile and extract text content."""
    _run_browser([
        'openclaw', 'browser', 'navigate',
        '--browser-profile', LINKEDIN_PROFILE, url
    ], timeout=30)
    time.sleep(4)

    # Extract rich profile text from DOM (much better than aria snapshot)
    js_fn = '(document.querySelector("main")?.innerText || document.querySelector(".pv-top-card")?.innerText || "").substring(0,4000)'
    result = _run_browser([
        'openclaw', 'browser', 'evaluate',
        '--browser-profile', LINKEDIN_PROFILE,
        '--fn', js_fn, '--json'
    ], timeout=30)

    if not result:
        return None
    try:
        data = json.loads(result)
        text = data.get("result", "")
        if not text:
            return None
        return text
    except Exception:
        return None


def extract_linkedin_url_from_search(urls):
    """Extract the best profile URL from search results (list of URL strings)."""
    if not urls:
        return None
    # Return first non-navigation URL (skip encoded ACo... profile IDs which are usually ads/suggestions)
    for u in urls:
        if '/in/' in u and '/in/ACo' not in u:
            return u
    # Fallback: first URL
    return urls[0] if urls else None


def scrape_linkedin_profile(name, company=None):
    """Full LinkedIn pipeline: search -> find URL -> scrape profile.

    Returns: dict with raw profile snapshot text, or None.
    """
    print(f"    🔗 LinkedIn: searching for {name}...")
    search_urls = linkedin_search(name, company)
    if not search_urls:
        print(f"    🔗 LinkedIn: search returned no results")
        return None

    profile_url = extract_linkedin_url_from_search(search_urls)
    if not profile_url:
        print(f"    🔗 LinkedIn: no profile URL found")
        return None

    print(f"    🔗 LinkedIn: scraping {profile_url}")
    time.sleep(LINKEDIN_RATE_LIMIT_SECS)

    profile_data = linkedin_profile(profile_url)
    if not profile_data:
        return {'source': 'search', 'url': profile_url, 'raw': ''}

    return {'source': 'profile', 'url': profile_url, 'raw': profile_data[:3000]}


# ─── Brave Search ───────────────────────────────────────────────

def search_founder_web(name, company=None):
    """Search for press mentions, publications, patents, achievements."""
    queries = []
    if company:
        queries.append(f'{name} {company} founder startup')
        queries.append(f'{name} {company} funding acquisition exit')
    else:
        queries.append(f'{name} founder startup')

    all_results = []
    for q in queries:
        results = brave_search(q, count=5)
        all_results.extend(results)
        if results:
            break  # Don't burn quota if first query worked

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in all_results:
        if r['url'] not in seen:
            seen.add(r['url'])
            unique.append(r)

    return unique[:8]


# ─── HubSpot ───────────────────────────────────────────────────

def get_hubspot_context(attendee_emails, owner_email):
    """Get HubSpot company, deals, and notes for external attendees."""
    external = [e for e in attendee_emails if not e.endswith('@' + TEAM_DOMAIN) and e != owner_email]
    if not external:
        return None

    domain = external[0].split('@')[-1]
    company = _search_company(domain=domain)
    if not company:
        return None

    company_id = company.get('id')
    company_name = company.get('properties', {}).get('name') or domain
    deals = get_deals_for_company(company_id, limit=3)
    latest_note = _get_latest_note(company_id)

    return {
        'company_id': company_id,
        'company_name': company_name,
        'industry': company.get('properties', {}).get('industry') or '',
        'deals': deals,
        'latest_note': latest_note,
    }


# ─── Gmail ──────────────────────────────────────────────────────

def get_email_history(external_emails, max_threads=5):
    """Pull recent email exchanges with external attendees."""
    domains = set()
    for e in external_emails:
        if '@' in e:
            domains.add(e.split('@')[-1])
    if not domains:
        return None

    query_parts = [f"from:{d} OR to:{d}" for d in list(domains)[:2]]
    query = f"({' OR '.join(query_parts)}) newer_than:90d"

    try:
        threads = gws_gmail_search(query, max_results=max_threads)
        if not threads:
            return None

        summaries = []
        for thread in threads[:max_threads]:
            tid = thread.get('id')
            if not tid:
                continue
            tdata = gws_gmail_thread_get(tid, fmt="metadata")
            if not tdata:
                continue
            msgs = tdata.get('messages', [])
            if not msgs:
                continue

            headers = msgs[0].get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
            subject = re.sub(r'^(re|fwd|fw):\s*', '', subject, flags=re.IGNORECASE).strip()
            snippet = thread.get('snippet', '')[:150]
            date_ms = int(msgs[-1].get('internalDate', 0))
            date_str = datetime.fromtimestamp(date_ms / 1000).strftime('%b %d') if date_ms else ''

            summaries.append(f"{subject} ({date_str}): {snippet}")

        return summaries if summaries else None
    except Exception as e:
        print(f"    Email history error: {e}", file=sys.stderr)
        return None


# ─── Previous Meetings ─────────────────────────────────────────

def get_previous_meetings(owner_email, external_domains, current_event_id):
    """Find past meetings with the same external domains (90d lookback)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=90)

    try:
        events = gws_calendar_events(
            owner_email,
            start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            max_results=100,
        )
        if not events:
            return []

        past = []
        for ev in events:
            if ev.get('id') == current_event_id:
                continue
            attendees = ev.get('attendees', [])
            for a in attendees:
                ae = a.get('email', '')
                if '@' in ae and ae.split('@')[-1] in external_domains and ae.split('@')[-1] != TEAM_DOMAIN:
                    dt_str = ev.get('start', {}).get('dateTime', '')
                    if dt_str:
                        try:
                            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00')).replace(tzinfo=None)
                            past.append({
                                'summary': ev.get('summary', 'Untitled'),
                                'date': dt.strftime('%b %d'),
                                'days_ago': (now - dt).days,
                            })
                        except Exception:
                            pass
                    break

        past.sort(key=lambda m: m['days_ago'])
        return past[:5]
    except Exception as e:
        print(f"    Previous meetings error: {e}", file=sys.stderr)
        return []


# ─── Mutual Connections ────────────────────────────────────────

def check_mutual_connections(founder_name):
    """Check if any GroundUp team members appear as connections on a LinkedIn search."""
    # We already have the profile snapshot from scrape_linkedin_profile
    # This function does a targeted search
    team_names = [m['full_name'] for m in TEAM_MEMBERS.values()]
    # We'll check this in the AI synthesis step by including team names in context
    return team_names




def extract_names_from_title(title, team_names):
    """Extract non-team-member names from meeting title."""
    clean = re.sub(r'^(call with|meeting with|sync with|intro:?|catch up:?)\s*', '', title, flags=re.IGNORECASE)
    parts = re.split(r'\s*(?://|<>|/|and|,|\|)\s*', clean)
    names = []
    for p in parts:
        p = re.sub(r'\(.*?\)', '', p).strip()
        p = re.sub(r'\s+', ' ', p).strip()
        if not p or len(p) < 3:
            continue
        is_team = False
        for tn in team_names:
            if p.lower() in tn.lower() or tn.lower() in p.lower():
                is_team = True
                break
        if not is_team:
            names.append(p)
    return names


def match_name_to_email(names, ext_emails):
    """Try to match extracted names to email addresses.
    Returns dict: email -> best name guess.
    """
    mapping = {}
    for email in ext_emails:
        prefix = email.split('@')[0].lower()
        best_name = email.split('@')[0].replace('.', ' ').title()

        for name in names:
            name_parts = name.lower().split()
            # Check if email prefix matches first initial + last name or full name
            # aatzmon -> matches 'Asaf Atzmon' (a + atzmon)
            if len(name_parts) >= 2:
                first_initial = name_parts[0][0]
                last_name = name_parts[-1]
                if prefix == first_initial + last_name:
                    best_name = name
                    break
                # tmizrahi -> matches 'Tal Mizrahi'
                if prefix.startswith(first_initial) and last_name in prefix:
                    best_name = name
                    break
            # Direct substring match
            if name_parts[0].lower() in prefix or prefix in name.lower().replace(' ', ''):
                best_name = name
                break

        mapping[email] = best_name
    return mapping


# ─── Research Pipeline ─────────────────────────────────────────

def research_founder(email, display_name, company_domain=None, db=None):
    """Full research pipeline for one founder. Uses cache if available.

    Returns a dict with all gathered data.
    """
    # Check cache first
    if db:
        cached = db.get_cached_founder(email)
        if cached:
            print(f"    ✓ Using cached data for {display_name}")
            return cached

    company_name = None
    if company_domain:
        company_name = company_domain.split('.')[0]

    data = {
        'email': email,
        'name': display_name,
        'company_domain': company_domain,
        'linkedin': None,
        'web_results': [],
        'github': None,
    }

    # 1. LinkedIn via Camofox
    print(f"    [1/3] LinkedIn lookup...")
    linkedin_data = scrape_linkedin_profile(display_name, company_name)
    if linkedin_data:
        data['linkedin'] = linkedin_data
    time.sleep(1)

    # 2. Brave Search — press, publications, exits
    print(f"    [2/3] Web search...")
    web_results = search_founder_web(display_name, company_name)
    data['web_results'] = web_results

    # 3. GitHub (quick check)
    print(f"    [3/3] GitHub check...")
    try:
        username = email.split('@')[0] if '@' in email else display_name.lower().replace(' ', '')
        resp = requests.get(f"https://api.github.com/users/{username}",
                           headers={'Accept': 'application/vnd.github.v3+json'}, timeout=5)
        if resp.status_code == 200:
            gh = resp.json()
            if gh.get('public_repos', 0) > 0:
                data['github'] = {
                    'url': gh.get('html_url'),
                    'repos': gh.get('public_repos'),
                    'bio': gh.get('bio'),
                }
    except Exception:
        pass

    # Cache the result
    if db:
        db.cache_founder(email, data)

    return data


# ─── AI Synthesis ──────────────────────────────────────────────

def synthesize_brief(founder_data, hubspot_ctx, email_history,
                     previous_meetings, meeting_summary, team_member_name):
    """Use Claude to synthesize all data into a scannable dossier."""

    context_parts = []
    context_parts.append(f"Meeting: {meeting_summary}")
    context_parts.append(f"Team member receiving this brief: {team_member_name}")

    for fd in founder_data:
        context_parts.append(f"\n--- FOUNDER: {fd['name']} ({fd['email']}) ---")

        if fd.get('linkedin'):
            li = fd['linkedin']
            if li.get('url'):
                context_parts.append(f"LinkedIn: {li['url']}")
            context_parts.append(f"LinkedIn data:\n{li.get('raw', 'No data')[:3000]}")

        if fd.get('web_results'):
            context_parts.append("\nWeb search results:")
            for r in fd['web_results'][:5]:
                context_parts.append(f"  - {r['title']}: {r['description'][:200]}")

        if fd.get('github'):
            gh = fd['github']
            context_parts.append(f"\nGitHub: {gh.get('url', '')} — {gh.get('repos', 0)} repos")
            if gh.get('bio'):
                context_parts.append(f"  Bio: {gh['bio']}")

    if hubspot_ctx:
        context_parts.append(f"\n--- HUBSPOT ---")
        context_parts.append(f"Company: {hubspot_ctx.get('company_name', 'Unknown')}")
        if hubspot_ctx.get('industry'):
            context_parts.append(f"Industry: {hubspot_ctx['industry']}")
        if hubspot_ctx.get('deals'):
            for d in hubspot_ctx['deals']:
                props = d.get('properties', {})
                context_parts.append(f"Deal: {props.get('dealname', '?')} | Stage: {props.get('dealstage', '?')}")
        if hubspot_ctx.get('latest_note'):
            context_parts.append(f"Latest note: {hubspot_ctx['latest_note']}")

    if email_history:
        context_parts.append(f"\n--- RECENT EMAILS ---")
        for eh in email_history[:5]:
            context_parts.append(f"  {eh}")

    if previous_meetings:
        context_parts.append(f"\n--- PREVIOUS MEETINGS ---")
        for pm in previous_meetings:
            context_parts.append(f"  {pm['summary']} ({pm['date']}, {pm['days_ago']}d ago)")

    # Team names for mutual connection reference
    team_names = [m['full_name'] for m in TEAM_MEMBERS.values()]
    context_parts.append(f"\nGroundUp team members (check if any appear in LinkedIn data): {', '.join(team_names)}")

    context_text = '\n'.join(context_parts)

    system = (
        f"You are {config.assistant_name}, VC firm assistant at GroundUp Ventures. "
        "Generate a founder dossier for a team member to read on their phone before a meeting. "
        "Format for WhatsApp — short lines, clear sections, no markdown (no ** or #). "
        "\n\n"
        "Structure:\n"
        "FOUNDER NAME — Current Role at Company\n"
        "\n"
        "CAREER\n"
        "List 3-5 key career stops (company, role, years). Not full resume — just the important ones.\n"
        "\n"
        "STARTUP HISTORY\n"
        "Previous companies founded or co-founded. Include funding raised and exits if found.\n"
        "\n"
        "NOTABLE\n"
        "Publications, patents, awards, press mentions. Skip if nothing found.\n"
        "\n"
        "GROUNDUP HISTORY\n"
        "Prior interactions — deals, meetings, notes from HubSpot. Say 'First interaction' if none.\n"
        "\n"
        "MUTUAL CONNECTIONS\n"
        "Any GroundUp team members who appear connected on LinkedIn. Say 'None found' if none.\n"
        "\n"
        "CONVERSATION STARTERS\n"
        "3 specific openers based on their background (not generic). Number them 1-3.\n"
        "\n"
        "WATCH FOR\n"
        "Red flags or things to dig into — resume gaps, short stints, unclear exits. "
        "Say 'Nothing notable' if clean.\n"
        "\n"
        "Rules: Be concise. Each section 1-3 lines max. Total brief under 40 lines. "
        "Use line breaks between sections. Only include what you actually found in the data — "
        "never fabricate. If a section has no data, write 'No data found' and move on."
    )

    try:
        brief = call_claude(
            context_text,
            system_prompt=system,
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            timeout=60,
        )
        return brief
    except Exception as e:
        print(f"    AI synthesis error: {e}", file=sys.stderr)
        return None


# ─── Main Processing ───────────────────────────────────────────

def process_founder_briefs():
    """Main loop: check calendars, generate briefs, send via WhatsApp."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting founder brief check...")

    db = BriefDatabase(BRIEF_DB_PATH)
    now = datetime.now(timezone.utc)

    window_start = now + timedelta(minutes=BRIEF_WINDOW_END)
    window_end = now + timedelta(minutes=BRIEF_WINDOW_START)

    print(f"  Window: {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')} UTC")

    total_sent = 0

    for email, member in TEAM_MEMBERS.items():
        if not member['enabled']:
            continue

        print(f"\n  Checking {member['name']}...")

        events = gws_calendar_events(
            email,
            window_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            window_end.strftime('%Y-%m-%dT%H:%M:%SZ'),
            max_results=10,
        )
        if not events:
            print(f"    No meetings in window")
            continue

        for event in events:
            event_id = event.get('id')
            summary = event.get('summary', 'Untitled Meeting')
            start_time = event.get('start', {}).get('dateTime')
            attendees = event.get('attendees', [])

            if not event_id or not start_time:
                continue

            # Validate time
            try:
                mt = datetime.fromisoformat(start_time.replace('Z', '+00:00')).replace(tzinfo=None)
                if mt < now or mt > window_end:
                    continue
            except Exception:
                continue

            # Skip solo/internal meetings
            other = [a for a in attendees if a.get('email', '') != email]
            if not other:
                continue

            ext_emails = [a.get('email', '') for a in attendees
                         if a.get('email', '') and not a.get('email', '').endswith('@' + TEAM_DOMAIN)
                         and a.get('email', '') != email]
            if not ext_emails:
                print(f"    ⏭  Internal meeting: {summary}")
                continue

            # Already sent?
            if db.is_sent(event_id, email):
                print(f"    ⏭  Already briefed: {summary}")
                continue

            print(f"    📋 Generating brief for: {summary}")

            # ── Gather data ──

            # Research each external founder
            founders = []
            for ext_email in ext_emails[:3]:  # Cap at 3 attendees
                display_name = ext_email.split('@')[0].replace('.', ' ').title()
                # Try to get display name from attendee data
                for a in attendees:
                    if a.get('email', '').lower() == ext_email.lower():
                        dn = a.get('displayName', '')
                        if dn:
                            display_name = dn
                        break

                domain = ext_email.split('@')[-1]
                fd = research_founder(ext_email, display_name, domain, db=db)
                founders.append(fd)
                time.sleep(1)  # Rate limit between founders

            # HubSpot context
            print(f"    📊 HubSpot lookup...")
            hubspot_ctx = get_hubspot_context(ext_emails, email)

            # Email history
            print(f"    📧 Email history...")
            email_history = get_email_history(ext_emails)

            # Previous meetings
            ext_domains = set(e.split('@')[-1] for e in ext_emails if '@' in e)
            print(f"    📅 Previous meetings...")
            prev_meetings = get_previous_meetings(email, ext_domains, event_id)

            # ── Synthesize ──
            print(f"    🤖 Synthesizing brief...")
            brief = synthesize_brief(
                founders, hubspot_ctx, email_history,
                prev_meetings, summary, member['name']
            )

            if not brief:
                print(f"    ✗ Failed to generate brief for {summary}")
                continue

            # ── Format and send ──
            meeting_time = format_meeting_time(start_time, member['timezone'])
            header = f"📋 FOUNDER BRIEF\n📅 {summary}\n⏰ {meeting_time}\n"

            # Add LinkedIn URLs if found
            li_links = []
            for fd in founders:
                if fd.get('linkedin', {}) and fd['linkedin'].get('url'):
                    li_links.append(f"🔗 {fd['name']}: {fd['linkedin']['url']}")
            link_section = '\n'.join(li_links) + '\n' if li_links else ''

            message = f"{header}\n{link_section}{brief}"

            print(f"    📤 Sending to {member['name']}...")
            sent = send_whatsapp(member['phone'], message, account=WHATSAPP_ACCOUNT)
            if sent:
                db.mark_sent(event_id, email)
                total_sent += 1
                print(f"    ✓ Brief sent!")
            else:
                print(f"    ✗ WhatsApp send failed")

    print(f"\n✅ Sent {total_sent} founder brief(s)")


def format_meeting_time(start_time_str, timezone_str):
    """Format meeting time in user's timezone."""
    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
    user_tz = pytz.timezone(timezone_str)
    local_time = start_time.astimezone(user_tz)
    return local_time.strftime('%I:%M %p').lstrip('0')


# ─── CLI ───────────────────────────────────────────────────────

def main():
    import fcntl

    lock_path = os.path.join(_DATA_DIR, "founder-brief.lock")
    lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another instance running, skipping.")
        return

    try:
        process_founder_briefs()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    main()
