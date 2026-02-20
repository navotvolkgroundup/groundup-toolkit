#!/usr/bin/env python3
"""
Founder Scout — Proactive discovery of Israeli tech founders about to start new companies.

Actions:
  scan              Run daily search rotation, detect signals, alert on high-tier
  briefing          Compile and send weekly email + WhatsApp summary
  watchlist-update  Re-scan existing tracked people for new signals
  status            Print tracked people and signal counts
  add <name> [url]  Manually add a person to track
  dismiss <id>      Mark a person as dismissed

Usage:
  python3 scout.py scan
  python3 scout.py briefing
  python3 scout.py watchlist-update
  python3 scout.py status
  python3 scout.py add "Yossi Cohen" "https://linkedin.com/in/yossicohen"
  python3 scout.py dismiss 42
"""

import sys
import os
import re
import json
import time
import fcntl
import sqlite3
import tempfile
import subprocess
import requests
from datetime import datetime, timedelta

# Load shared config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config

# --- Configuration ---

ANTHROPIC_API_KEY = config.anthropic_api_key
BRAVE_SEARCH_API_KEY = config.brave_search_api_key
GOG_ACCOUNT = config.assistant_email
LINKEDIN_BROWSER_PROFILE = "linkedin"
MAX_LINKEDIN_LOOKUPS_PER_SCAN = 5

# Data directory
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, 'founder-scout.db')
LOCK_PATH = os.path.join(_DATA_DIR, 'founder-scout.lock')

# Email recipients for scout reports
SCOUT_RECIPIENTS = []
for m in config.team_members:
    SCOUT_RECIPIENTS.append({
        'name': m['name'],
        'first_name': m['name'].split()[0],
        'email': m['email'],
        'phone': m['phone'],
    })

# --- Search Queries ---

SEARCH_QUERIES = {
    'il_stealth': {
        'query': 'Israel stealth startup founder {year}',
        'priority': 'high',
    },
    'il_left_role': {
        'query': 'Israel CTO CEO "left" OR "departed" OR "stepping down" tech {year}',
        'priority': 'high',
    },
    'il_building': {
        'query': 'Israel founder "building something new" OR "next chapter" OR "stealth" {year}',
        'priority': 'high',
    },
    'il_open_to': {
        'query': 'site:linkedin.com/in Israel "open to work" OR "exploring" CTO CEO founder',
        'priority': 'medium',
    },
    'il_exits': {
        'query': 'Israel startup acquisition exit founder {prev_year} {year}',
        'priority': 'medium',
    },
    'il_raising': {
        'query': 'Israel pre-seed seed "raising" OR "building" {year}',
        'priority': 'medium',
    },
    'il_8200': {
        'query': 'Israel 8200 OR Talpiot alumni startup founder {year}',
        'priority': 'low',
    },
    'il_serial': {
        'query': 'Israel serial entrepreneur "second time" OR "new venture" {year}',
        'priority': 'low',
    },
    'il_grants': {
        'query': 'Israel Innovation Authority grant startup founder {year}',
        'priority': 'low',
    },
    'il_accelerator': {
        'query': 'Israel accelerator batch {year} founder',
        'priority': 'low',
    },
}

# Priority → max days between runs
PRIORITY_INTERVALS = {
    'high': 1,
    'medium': 2,
    'low': 3,
}

MAX_QUERIES_PER_SCAN = 8
MAX_CLAUDE_CALLS_PER_SCAN = 10

# --- Signal Patterns ---

SIGNAL_PATTERNS = {
    'high': [
        (r'(?:left|departed|stepping down from|exited)\s+(?:his |her |their )?(?:role|position|as (?:cto|ceo|vp|co-?founder))', 'left_role'),
        (r'(?:building something new|next chapter|in stealth mode|working on something new)', 'stealth_hint'),
        (r'(?:co-?found|launch)(?:ing|ed)\s+(?:a new |his new |her new )', 'founding'),
    ],
    'medium': [
        (r'open to (?:work|new opportunities|exploring)', 'open_to_work'),
        (r'(?:after|following)\s+(?:the |his |her )?(?:acquisition|exit|sale)\s+of', 'recent_exit'),
        (r'exploring\s+(?:new |his next |her next |what)', 'exploring'),
    ],
    'low': [
        (r'(?:graduat|complet)(?:ed|ing)\s+(?:the |an? )?(?:accelerator|program|batch|cohort)', 'accelerator'),
        (r'(?:received|awarded|won)\s+(?:a |an? )?(?:grant|award|fellowship)', 'grant'),
        (r'(?:joined|serving)\s+as\s+(?:an? )?(?:angel|advisor|mentor)', 'advisory'),
    ],
}


# --- Database ---

class ScoutDatabase:
    """Track scouted founders and signals."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tracked_people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            linkedin_url TEXT UNIQUE,
            source TEXT,
            signal_tier TEXT,
            last_signal TEXT,
            last_scanned TEXT,
            added_at TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            notes TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER REFERENCES tracked_people(id),
            signal_type TEXT NOT NULL,
            signal_tier TEXT NOT NULL,
            description TEXT,
            source_url TEXT,
            detected_at TEXT NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            queries_run INTEGER DEFAULT 0,
            people_found INTEGER DEFAULT 0,
            signals_detected INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS search_rotation (
            query_key TEXT PRIMARY KEY,
            last_run TEXT,
            run_count INTEGER DEFAULT 0
        )''')
        conn.commit()
        conn.close()

    def add_person(self, name, linkedin_url=None, source='search'):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                'INSERT OR IGNORE INTO tracked_people (name, linkedin_url, source, added_at) VALUES (?, ?, ?, ?)',
                (name, linkedin_url, source, datetime.now().isoformat())
            )
            conn.commit()
            person_id = conn.execute(
                'SELECT id FROM tracked_people WHERE name = ? AND (linkedin_url = ? OR (linkedin_url IS NULL AND ? IS NULL))',
                (name, linkedin_url, linkedin_url)
            ).fetchone()
            return person_id[0] if person_id else None
        finally:
            conn.close()

    def get_person_by_name(self, name):
        conn = sqlite3.connect(self.db_path)
        result = conn.execute(
            'SELECT id, name, linkedin_url, signal_tier, status FROM tracked_people WHERE name = ? AND status = ?',
            (name, 'active')
        ).fetchone()
        conn.close()
        return result

    def get_person_by_linkedin(self, url):
        conn = sqlite3.connect(self.db_path)
        result = conn.execute(
            'SELECT id FROM tracked_people WHERE linkedin_url = ?', (url,)
        ).fetchone()
        conn.close()
        return result[0] if result else None

    def get_active_people(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        results = conn.execute(
            'SELECT * FROM tracked_people WHERE status = ? ORDER BY signal_tier DESC, added_at DESC',
            ('active',)
        ).fetchall()
        conn.close()
        return [dict(r) for r in results]

    def record_signal(self, person_id, signal_type, tier, description, source_url=None):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT INTO signal_history (person_id, signal_type, signal_tier, description, source_url, detected_at) VALUES (?, ?, ?, ?, ?, ?)',
            (person_id, signal_type, tier, description, source_url, datetime.now().isoformat())
        )
        conn.execute(
            'UPDATE tracked_people SET signal_tier = ?, last_signal = ?, last_scanned = ? WHERE id = ?',
            (tier, description, datetime.now().isoformat(), person_id)
        )
        conn.commit()
        conn.close()

    def get_signals_since(self, since_date):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        results = conn.execute(
            '''SELECT sh.*, tp.name, tp.linkedin_url
               FROM signal_history sh
               JOIN tracked_people tp ON sh.person_id = tp.id
               WHERE sh.detected_at >= ?
               ORDER BY sh.signal_tier ASC, sh.detected_at DESC''',
            (since_date,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in results]

    def get_rotation_queue(self, max_queries):
        """Select queries due to run based on priority intervals."""
        now = datetime.now()
        conn = sqlite3.connect(self.db_path)
        queue = []

        for key, info in SEARCH_QUERIES.items():
            row = conn.execute(
                'SELECT last_run FROM search_rotation WHERE query_key = ?', (key,)
            ).fetchone()

            interval_days = PRIORITY_INTERVALS[info['priority']]
            if row and row[0]:
                last_run = datetime.fromisoformat(row[0])
                if (now - last_run).total_seconds() < interval_days * 86400:
                    continue

            queue.append((key, info['priority']))

        conn.close()

        # Sort: high first, then medium, then low
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        queue.sort(key=lambda x: priority_order[x[1]])

        return [key for key, _ in queue[:max_queries]]

    def update_rotation(self, query_key):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT OR REPLACE INTO search_rotation (query_key, last_run, run_count) VALUES (?, ?, COALESCE((SELECT run_count FROM search_rotation WHERE query_key = ?), 0) + 1)',
            (query_key, datetime.now().isoformat(), query_key)
        )
        conn.commit()
        conn.close()

    def log_scan(self, scan_type, queries_run=0, people_found=0, signals_detected=0):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT INTO scan_log (scan_type, started_at, completed_at, queries_run, people_found, signals_detected) VALUES (?, ?, ?, ?, ?, ?)',
            (scan_type, datetime.now().isoformat(), datetime.now().isoformat(), queries_run, people_found, signals_detected)
        )
        conn.commit()
        conn.close()

    def dismiss_person(self, person_id):
        conn = sqlite3.connect(self.db_path)
        conn.execute('UPDATE tracked_people SET status = ? WHERE id = ?', ('dismissed', person_id))
        conn.commit()
        conn.close()

    def get_stats(self):
        conn = sqlite3.connect(self.db_path)
        active = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ?', ('active',)).fetchone()[0]
        high = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ? AND signal_tier = ?', ('active', 'high')).fetchone()[0]
        medium = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ? AND signal_tier = ?', ('active', 'medium')).fetchone()[0]
        low = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ? AND signal_tier = ?', ('active', 'low')).fetchone()[0]
        total_signals = conn.execute('SELECT COUNT(*) FROM signal_history').fetchone()[0]
        total_scans = conn.execute('SELECT COUNT(*) FROM scan_log').fetchone()[0]
        conn.close()
        return {
            'active': active, 'high': high, 'medium': medium, 'low': low,
            'total_signals': total_signals, 'total_scans': total_scans,
        }


# --- Brave Search + Claude ---

def brave_search(query, count=5):
    """Search using Brave Search API."""
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


def call_claude(prompt, system_prompt="", model="claude-sonnet-4-20250514", max_tokens=2048):
    """Call Claude API."""
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    if system_prompt:
        payload["system"] = system_prompt

    for attempt in range(3):
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json=payload,
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        if response.status_code == 429:
            wait = 15 * (attempt + 1)
            print(f"  Claude rate limited, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        print(f"  Claude API error: {response.status_code} {response.text[:200]}", file=sys.stderr)
        return None
    print(f"  Claude API: exhausted retries", file=sys.stderr)
    return None


# --- Signal Detection ---

def extract_names_from_results(results):
    """Extract potential person names from search results.

    Uses heuristics to filter out company names, places, and other non-person entities.
    """
    names = set()
    # Match 2-3 word capitalized sequences (likely names)
    name_pattern = re.compile(r'\b([A-Z][a-z]{1,15}\s+[A-Z][a-z]{1,15}(?:\s+[A-Z][a-z]{1,15})?)\b')

    # Words that indicate this is NOT a person name
    NON_PERSON_WORDS = {
        # Places
        'united', 'states', 'york', 'francisco', 'angeles', 'israel', 'israeli',
        'valley', 'silicon', 'street', 'east', 'west', 'north', 'south', 'middle',
        'european', 'american', 'korean', 'dallas', 'london', 'berlin', 'paris',
        # Organizations
        'startup', 'startups', 'security', 'capital', 'ventures', 'venture',
        'foundation', 'authority', 'union', 'defense', 'forces', 'cloud',
        'incubator', 'accelerator', 'guardian', 'intelligence', 'technology',
        'cybersecurity', 'partners', 'group', 'global', 'institute', 'university',
        # Generic/descriptor
        'top', 'best', 'great', 'former', 'national', 'general', 'early', 'stage',
        'funding', 'seed', 'series', 'round', 'inside', 'daily', 'weekly',
        'annual', 'first', 'second', 'third', 'new', 'recent', 'other', 'others',
        'data', 'tech', 'ctech', 'mode', 'stealth', 'emerges', 'exits',
        'raises', 'raising', 'building', 'founded', 'testing', 'penetration',
        'agents', 'mimic', 'human', 'space', 'make', 'few', 'there', 'nearly',
        'transportation', 'ecosystem',
    }

    for r in results:
        text = f"{r.get('title', '')} {r.get('description', '')}"
        for match in name_pattern.finditer(text):
            candidate = match.group(1)
            words = candidate.lower().split()
            # Skip if any word is a non-person word
            if any(w in NON_PERSON_WORDS for w in words):
                continue
            # Skip single-character first/last names
            if any(len(w) < 2 for w in candidate.split()):
                continue
            names.add(candidate)
    return list(names)


def score_candidate(name, results):
    """Score a candidate's relevance for deeper analysis.

    Returns (score, relevant_results) where higher score = more worth analyzing.
    Scoring:
      +3 per result with a LinkedIn URL mentioning the name
      +2 per result containing a role keyword near the name
      +1 per result mentioning the name
    """
    first_name = name.split()[0].lower()
    last_name = name.split()[-1].lower() if len(name.split()) > 1 else ''
    role_keywords = re.compile(r'\b(?:ceo|cto|coo|cfo|vp|founder|co-?founder|chief|director)\b', re.I)

    score = 0
    relevant = []
    for r in results:
        text = f"{r.get('title', '')} {r.get('description', '')}".lower()
        url = r.get('url', '').lower()

        # Must mention at least the first name
        if first_name not in text:
            continue

        relevant.append(r)
        score += 1

        # Bonus for LinkedIn URL
        if 'linkedin.com/in/' in url and (first_name in url or last_name in url):
            score += 3

        # Bonus for role keyword near the name
        if role_keywords.search(text):
            score += 2

    return score, relevant


def analyze_with_claude(name, snippets, claude_calls_remaining):
    """Phase 2: Use Claude to analyze a candidate for startup signals."""
    if claude_calls_remaining <= 0:
        return None

    snippets_text = '\n'.join([
        f"- {s.get('title', '')}: {s.get('description', '')}"
        for s in snippets[:10]
    ])

    system_prompt = (
        "You are a VC scout analyzing whether an Israeli tech person is about to start a new company. "
        "Be conservative — only flag genuine signals, not speculation."
    )
    prompt = f"""Analyze this person for "about to start a company" signals.

NAME: {name}

SEARCH RESULTS:
{snippets_text}

Return ONLY valid JSON (no markdown, no explanation):
{{"name": "{name}", "signals": ["signal1", "signal2"], "confidence": "high|medium|low", "summary": "One sentence description", "linkedin_hint": "linkedin URL if found in results, else null"}}

Rules:
- signals: list of specific observations (e.g. "Left CTO role at Company X in Jan 2026")
- confidence: high = strong evidence of starting something, medium = suggestive, low = weak hints
- If no real signals found, return: {{"name": "{name}", "signals": [], "confidence": "none", "summary": "No startup signals detected", "linkedin_hint": null}}"""

    response = call_claude(prompt, system_prompt, max_tokens=512)
    if not response:
        return None

    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        print(f"  Could not parse Claude response for {name}: {response[:200]}", file=sys.stderr)
    return None


def find_linkedin_url(name, results):
    """Try to extract a LinkedIn profile URL from search results."""
    for r in results:
        url = r.get('url', '')
        if 'linkedin.com/in/' in url:
            # Check if the name appears in the result
            text = f"{r.get('title', '')} {r.get('description', '')}".lower()
            if name.split()[0].lower() in text:
                return url
    return None


# --- LinkedIn Browser Integration ---

def linkedin_browser_available():
    """Check if the LinkedIn browser session is available."""
    try:
        result = subprocess.run(
            ['openclaw', 'browser', 'status', '--browser-profile', LINKEDIN_BROWSER_PROFILE, '--json'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def linkedin_search(query):
    """Search LinkedIn for a person using the browser skill. Returns snapshot text."""
    try:
        encoded = subprocess.run(
            ['python3', '-c', f"import urllib.parse; print(urllib.parse.quote({query!r}))"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()

        url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
        subprocess.run(
            ['openclaw', 'browser', 'navigate', '--browser-profile', LINKEDIN_BROWSER_PROFILE, url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(3)

        result = subprocess.run(
            ['openclaw', 'browser', 'snapshot', '--browser-profile', LINKEDIN_BROWSER_PROFILE, '--efficient'],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout if result.returncode == 0 else None
    except Exception as e:
        print(f"  LinkedIn search error: {e}", file=sys.stderr)
        return None


def linkedin_profile_lookup(url):
    """Look up a LinkedIn profile using the browser skill. Returns snapshot text."""
    try:
        subprocess.run(
            ['openclaw', 'browser', 'navigate', '--browser-profile', LINKEDIN_BROWSER_PROFILE, url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(3)

        result = subprocess.run(
            ['openclaw', 'browser', 'snapshot', '--browser-profile', LINKEDIN_BROWSER_PROFILE,
             '--format', 'aria', '--limit', '300'],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout if result.returncode == 0 else None
    except Exception as e:
        print(f"  LinkedIn profile lookup error: {e}", file=sys.stderr)
        return None


def enrich_with_linkedin(name, linkedin_url, claude_calls_remaining):
    """Use LinkedIn browser to get richer profile data, then have Claude extract signals.

    Returns enriched analysis dict or None.
    """
    profile_text = None

    if linkedin_url:
        print(f"      LinkedIn: looking up profile {linkedin_url[:50]}...")
        profile_text = linkedin_profile_lookup(linkedin_url)
    else:
        # Try to find them via LinkedIn search
        print(f"      LinkedIn: searching for {name}...")
        search_text = linkedin_search(name)
        if search_text:
            # Try to extract a profile URL from the search results
            li_match = re.search(r'(https://www\.linkedin\.com/in/[a-zA-Z0-9_-]+)', search_text)
            if li_match:
                linkedin_url = li_match.group(1)
                print(f"      LinkedIn: found profile {linkedin_url}")
                profile_text = linkedin_profile_lookup(linkedin_url)

    if not profile_text or claude_calls_remaining <= 0:
        return None

    # Have Claude analyze the LinkedIn profile for signals
    system_prompt = (
        "You are a VC scout analyzing a LinkedIn profile for signs that this person is about to start "
        "a new company. Look for: recent role changes, 'open to work', stealth references, gaps in "
        "employment, pivot from corporate to startup, advisory roles at multiple startups."
    )
    prompt = f"""Analyze this LinkedIn profile for "about to start a company" signals.

NAME: {name}
LINKEDIN URL: {linkedin_url or 'unknown'}

PROFILE DATA:
{profile_text[:3000]}

Return ONLY valid JSON (no markdown):
{{"signals": ["signal1", "signal2"], "confidence": "high|medium|low|none", "summary": "One sentence", "current_title": "their current role or null", "linkedin_url": "{linkedin_url or ''}"}}"""

    response = call_claude(prompt, system_prompt, max_tokens=512)
    if not response:
        return None

    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            parsed['linkedin_url'] = linkedin_url
            return parsed
    except (json.JSONDecodeError, AttributeError):
        print(f"  Could not parse LinkedIn analysis for {name}", file=sys.stderr)
    return None


# --- Sending ---

def send_email(to_email, subject, body):
    """Send email using gog CLI with body file."""
    try:
        fd, body_file = tempfile.mkstemp(suffix='.txt', prefix='scout-email-')
        with os.fdopen(fd, 'w') as f:
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
        except OSError:
            pass

        if result.returncode == 0:
            print(f"  Email sent to {to_email}")
            return True
        else:
            print(f"  Email failed for {to_email}: {result.stderr.strip()[:200]}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  Email exception for {to_email}: {e}", file=sys.stderr)
        return False


def send_whatsapp(phone, message, max_retries=3, retry_delay=3):
    """Send WhatsApp message via OpenClaw with retry."""
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
                print(f"  WhatsApp sent to {phone}" + (f" (attempt {attempt})" if attempt > 1 else ""))
                return True
            else:
                print(f"  Attempt {attempt}/{max_retries} failed: {result.stderr.strip()[:100]}", file=sys.stderr)
                if attempt < max_retries:
                    time.sleep(retry_delay)
        except Exception as e:
            print(f"  Attempt {attempt}/{max_retries} exception: {e}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(retry_delay)
    return False


# --- Formatting ---

def format_briefing_email(recipient_name, high_signals, medium_signals, low_signals, stats):
    """Format weekly briefing email."""
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime('%b %d')
    week_end = now.strftime('%b %d, %Y')

    lines = [
        f"Hi {recipient_name},",
        "",
        f"Here's your Founder Scout weekly briefing ({week_start} - {week_end}).",
        "",
    ]

    if high_signals:
        lines.append("HIGH SIGNAL")
        lines.append("-" * 40)
        for i, s in enumerate(high_signals, 1):
            lines.append(f"{i}. {s['name']}")
            if s.get('linkedin_url'):
                lines.append(f"   LinkedIn: {s['linkedin_url']}")
            lines.append(f"   Signal: {s.get('description', 'N/A')}")
            lines.append("")
    else:
        lines.append("No high-signal founders detected this week.")
        lines.append("")

    if medium_signals:
        lines.append("MEDIUM SIGNAL")
        lines.append("-" * 40)
        for i, s in enumerate(medium_signals, 1):
            lines.append(f"{i}. {s['name']}")
            if s.get('linkedin_url'):
                lines.append(f"   LinkedIn: {s['linkedin_url']}")
            lines.append(f"   Signal: {s.get('description', 'N/A')}")
            lines.append("")

    if low_signals:
        lines.append(f"LOW SIGNAL: {len(low_signals)} additional candidate(s) detected.")
        lines.append("")

    lines.extend([
        f"Stats: {stats.get('queries', 0)} searches, {stats.get('candidates', 0)} candidates screened, {stats.get('flagged', 0)} flagged",
        f"Watchlist: {stats.get('active', 0)} active people tracked",
        "",
        f"-- {config.assistant_name}",
    ])

    return '\n'.join(lines)


def format_whatsapp_alert(name, signal_description, linkedin_url=None):
    """Format instant WhatsApp alert for high-signal founders."""
    lines = [
        "Founder Scout Alert",
        "",
        f"{name}",
        f"Signal: {signal_description}",
    ]
    if linkedin_url:
        lines.append(f"LinkedIn: {linkedin_url}")
    return '\n'.join(lines)


def format_whatsapp_briefing(recipient_name, high_count, medium_count, low_count, total_active):
    """Format compact WhatsApp weekly summary."""
    lines = [
        "Founder Scout Weekly",
        "",
        f"Hi {recipient_name}, this week's scouting results:",
        f"  High signal: {high_count}",
        f"  Medium signal: {medium_count}",
        f"  Low signal: {low_count}",
        f"  Active watchlist: {total_active}",
        "",
        "Full details sent to your email.",
    ]
    return '\n'.join(lines)


# --- Main Actions ---

def run_daily_scan():
    """Run daily search rotation and detect signals."""
    print(f"[{datetime.now()}] Starting Founder Scout daily scan...")

    db = ScoutDatabase(DB_PATH)
    year = datetime.now().year
    prev_year = year - 1

    # Check LinkedIn browser availability
    li_available = linkedin_browser_available()
    li_lookups = 0
    if li_available:
        print("  LinkedIn browser: available")
    else:
        print("  LinkedIn browser: not available (will skip profile lookups)")

    # Get queries due to run
    queue = db.get_rotation_queue(MAX_QUERIES_PER_SCAN)
    if not queue:
        print("  No queries due to run today.")
        db.log_scan('daily_search')
        return

    print(f"  Running {len(queue)} queries...")

    all_results = {}
    for query_key in queue:
        info = SEARCH_QUERIES[query_key]
        query = info['query'].format(year=year, prev_year=prev_year)
        print(f"    [{query_key}] {query[:70]}...")
        results = brave_search(query, count=8)
        all_results[query_key] = results
        db.update_rotation(query_key)
        time.sleep(0.5)

    # Collect all results into a flat list for name extraction
    flat_results = []
    for results in all_results.values():
        flat_results.extend(results)

    if not flat_results:
        print("  No search results.")
        db.log_scan('daily_search', queries_run=len(queue))
        return

    # Extract and rank candidate names
    names = extract_names_from_results(flat_results)
    print(f"  Extracted {len(names)} candidate names")

    # Score candidates by relevance
    scored = []
    for name in names:
        score, relevant = score_candidate(name, flat_results)
        if score >= 2:  # Minimum relevance threshold
            scored.append((score, name, relevant))

    scored.sort(reverse=True)
    print(f"  Scored {len(scored)} candidates above threshold (top: {scored[0][0] if scored else 0})")

    # Claude analysis for top candidates (sorted by score)
    claude_calls = 0
    people_found = 0
    signals_detected = 0
    high_alerts = []

    for score, name, relevant_results in scored:
        if claude_calls >= MAX_CLAUDE_CALLS_PER_SCAN:
            break

        # Skip if already tracked
        existing = db.get_person_by_name(name)
        if existing:
            continue

        # Try to find LinkedIn URL
        linkedin_url = find_linkedin_url(name, relevant_results)

        if linkedin_url:
            existing_by_url = db.get_person_by_linkedin(linkedin_url)
            if existing_by_url:
                continue

        # Rate limit: wait between Claude calls
        if claude_calls > 0:
            time.sleep(13)  # Stay under 5 req/min limit

        analysis = analyze_with_claude(name, relevant_results, MAX_CLAUDE_CALLS_PER_SCAN - claude_calls)
        claude_calls += 1

        if analysis and analysis.get('confidence') in ('high', 'medium') and analysis.get('signals'):
            confidence = analysis['confidence']
            summary = analysis.get('summary', '')
            li_hint = analysis.get('linkedin_hint') or linkedin_url

            # LinkedIn enrichment for high/medium candidates
            if li_available and li_lookups < MAX_LINKEDIN_LOOKUPS_PER_SCAN and confidence in ('high', 'medium'):
                li_lookups += 1
                time.sleep(13)  # Rate limit before Claude call
                li_analysis = enrich_with_linkedin(name, li_hint, MAX_CLAUDE_CALLS_PER_SCAN - claude_calls)
                if li_analysis:
                    claude_calls += 1
                    # Upgrade confidence if LinkedIn confirms signals
                    li_confidence = li_analysis.get('confidence', 'none')
                    if li_confidence == 'high' and confidence != 'high':
                        confidence = 'high'
                    if li_analysis.get('linkedin_url'):
                        li_hint = li_analysis['linkedin_url']
                    li_summary = li_analysis.get('summary', '')
                    if li_summary:
                        summary = f"{summary} | LinkedIn: {li_summary}"
                    current_title = li_analysis.get('current_title')
                    if current_title:
                        summary = f"[{current_title}] {summary}"

            person_id = db.add_person(name, li_hint, 'search')
            if person_id:
                db.record_signal(person_id, 'claude_analysis', confidence, summary,
                                 li_hint)
                people_found += 1
                signals_detected += 1
                print(f"    [{confidence.upper()}] {name} (score={score}): {summary[:70]}")

                if confidence == 'high':
                    high_alerts.append({
                        'name': name,
                        'description': summary,
                        'linkedin_url': li_hint,
                    })

    # Send WhatsApp alerts for high-signal founders
    if high_alerts:
        print(f"\n  Sending {len(high_alerts)} high-signal alert(s)...")
        for alert in high_alerts:
            wa_message = format_whatsapp_alert(alert['name'], alert['description'], alert.get('linkedin_url'))
            for recipient in SCOUT_RECIPIENTS:
                send_whatsapp(recipient['phone'], wa_message)

    db.log_scan('daily_search', queries_run=len(queue), people_found=people_found, signals_detected=signals_detected)
    print(f"\n  Scan complete: {len(queue)} queries, {people_found} new people, {signals_detected} signals, {claude_calls} Claude calls")


def run_weekly_briefing():
    """Compile and send weekly briefing email + WhatsApp summary."""
    print(f"[{datetime.now()}] Sending Founder Scout weekly briefing...")

    db = ScoutDatabase(DB_PATH)
    since = (datetime.now() - timedelta(days=7)).isoformat()
    recent_signals = db.get_signals_since(since)

    high_signals = [s for s in recent_signals if s['signal_tier'] == 'high']
    medium_signals = [s for s in recent_signals if s['signal_tier'] == 'medium']
    low_signals = [s for s in recent_signals if s['signal_tier'] == 'low']

    db_stats = db.get_stats()
    stats = {
        'queries': db_stats['total_scans'],
        'candidates': db_stats['active'],
        'flagged': len(recent_signals),
        'active': db_stats['active'],
    }

    week_str = datetime.now().strftime('%b %d, %Y')
    subject = f"Founder Scout Weekly — {week_str}"

    for recipient in SCOUT_RECIPIENTS:
        # Email
        email_body = format_briefing_email(
            recipient['first_name'], high_signals, medium_signals, low_signals, stats
        )
        print(f"  Sending email to {recipient['email']}...")
        send_email(recipient['email'], subject, email_body)

        # WhatsApp summary
        wa_message = format_whatsapp_briefing(
            recipient['first_name'], len(high_signals), len(medium_signals),
            len(low_signals), db_stats['active']
        )
        print(f"  Sending WhatsApp to {recipient['phone']}...")
        send_whatsapp(recipient['phone'], wa_message)

    db.log_scan('weekly_briefing', signals_detected=len(recent_signals))
    print(f"  Briefing sent: {len(high_signals)} high, {len(medium_signals)} medium, {len(low_signals)} low")


def run_watchlist_update():
    """Re-scan existing tracked people for new signals using Brave + LinkedIn."""
    print(f"[{datetime.now()}] Running Founder Scout watchlist update...")

    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()

    if not people:
        print("  No active people in watchlist.")
        db.log_scan('watchlist_update')
        return

    # Check LinkedIn browser availability
    li_available = linkedin_browser_available()
    li_lookups = 0
    if li_available:
        print(f"  LinkedIn browser: available (max {MAX_LINKEDIN_LOOKUPS_PER_SCAN} lookups)")
    else:
        print("  LinkedIn browser: not available")

    print(f"  Re-scanning {len(people)} active people...")
    year = datetime.now().year
    claude_calls = 0
    new_signals = 0

    for person in people:
        name = person['name']
        linkedin_url = person.get('linkedin_url')
        print(f"    Checking {name}...")

        # Brave search for recent news
        results = brave_search(f'"{name}" Israel startup founder {year}', count=5)
        time.sleep(0.5)

        if claude_calls >= MAX_CLAUDE_CALLS_PER_SCAN:
            break

        # LinkedIn profile check for people who have a URL
        li_profile_text = None
        if li_available and linkedin_url and li_lookups < MAX_LINKEDIN_LOOKUPS_PER_SCAN:
            li_lookups += 1
            print(f"      LinkedIn: checking profile...")
            li_profile_text = linkedin_profile_lookup(linkedin_url)
            time.sleep(2)

        if not results and not li_profile_text:
            continue

        # Rate limit: wait between Claude calls
        if claude_calls > 0:
            time.sleep(13)

        # Build combined context for Claude
        snippets_text = '\n'.join([
            f"- {r.get('title', '')}: {r.get('description', '')}"
            for r in (results or [])[:8]
        ])
        li_context = ""
        if li_profile_text:
            li_context = f"\n\nLINKEDIN PROFILE:\n{li_profile_text[:2000]}"

        system_prompt = (
            "You are a VC scout checking for new signals about a person already on our watchlist. "
            "Look for changes since last check: new role, stealth hints, fundraising, advisory roles."
        )
        prompt = f"""Check for NEW signals about this person (they're already on our watchlist).

NAME: {name}
LINKEDIN: {linkedin_url or 'unknown'}
LAST KNOWN SIGNAL: {person.get('last_signal', 'None')}

RECENT WEB RESULTS:
{snippets_text or 'No web results found.'}{li_context}

Return ONLY valid JSON:
{{"signals": ["signal1"], "confidence": "high|medium|low|none", "summary": "What's new since last check"}}"""

        response = call_claude(prompt, system_prompt, max_tokens=512)
        claude_calls += 1

        if response:
            try:
                match = re.search(r'\{.*\}', response, re.DOTALL)
                if match:
                    analysis = json.loads(match.group())
                    if analysis.get('confidence') in ('high', 'medium') and analysis.get('signals'):
                        new_summary = analysis.get('summary', '')
                        if new_summary != person.get('last_signal'):
                            db.record_signal(person['id'], 'watchlist_update', analysis['confidence'],
                                             new_summary, linkedin_url)
                            new_signals += 1
                            print(f"      New signal: {new_summary[:60]}")
            except (json.JSONDecodeError, AttributeError):
                pass

        # Update last_scanned
        conn = sqlite3.connect(db.db_path)
        conn.execute('UPDATE tracked_people SET last_scanned = ? WHERE id = ?',
                     (datetime.now().isoformat(), person['id']))
        conn.commit()
        conn.close()

    db.log_scan('watchlist_update', queries_run=len(people), signals_detected=new_signals)
    print(f"  Watchlist update complete: {len(people)} checked, {new_signals} new signals, "
          f"{claude_calls} Claude calls, {li_lookups} LinkedIn lookups")


def run_status():
    """Print current tracked people and signal counts."""
    db = ScoutDatabase(DB_PATH)
    stats = db.get_stats()
    people = db.get_active_people()

    print(f"Founder Scout Status — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"  Active people: {stats['active']}")
    print(f"  High signal: {stats['high']}")
    print(f"  Medium signal: {stats['medium']}")
    print(f"  Low signal: {stats['low']}")
    print(f"  Total signals recorded: {stats['total_signals']}")
    print(f"  Total scans run: {stats['total_scans']}")

    if people:
        print(f"\n  Active Watchlist:")
        for p in people:
            tier_label = f"[{p['signal_tier'].upper()}]" if p.get('signal_tier') else "[---]"
            li = f" ({p['linkedin_url']})" if p.get('linkedin_url') else ""
            signal = f" — {p['last_signal'][:60]}" if p.get('last_signal') else ""
            print(f"    {tier_label} {p['name']}{li}{signal}")
    else:
        print("\n  No people tracked yet. Run 'founder-scout scan' to start.")


def run_add(name, linkedin_url=None):
    """Manually add a person to track."""
    db = ScoutDatabase(DB_PATH)
    person_id = db.add_person(name, linkedin_url or None, 'manual')
    if person_id:
        print(f"Added {name} to watchlist (id={person_id})")
        if linkedin_url:
            print(f"  LinkedIn: {linkedin_url}")
    else:
        print(f"Could not add {name} (may already exist)")


def run_dismiss(person_id):
    """Mark a person as dismissed."""
    db = ScoutDatabase(DB_PATH)
    db.dismiss_person(int(person_id))
    print(f"Dismissed person id={person_id}")


# --- Entry Point ---

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action == 'scan':
        lock_file = open(LOCK_PATH, 'w')
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another instance is running, skipping.")
            return
        try:
            run_daily_scan()
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()

    elif action == 'briefing':
        run_weekly_briefing()

    elif action == 'watchlist-update':
        run_watchlist_update()

    elif action == 'status':
        run_status()

    elif action == 'add':
        if len(sys.argv) < 3:
            print("Usage: scout.py add <name> [linkedin_url]")
            sys.exit(1)
        name = sys.argv[2]
        linkedin_url = sys.argv[3] if len(sys.argv) > 3 else None
        run_add(name, linkedin_url)

    elif action == 'dismiss':
        if len(sys.argv) < 3:
            print("Usage: scout.py dismiss <id>")
            sys.exit(1)
        run_dismiss(sys.argv[2])

    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
