#!/usr/bin/env python3
"""
Founder Scout — Proactive discovery of Israeli tech founders about to start new companies.

Discovery is LinkedIn-only: searches LinkedIn people search via browser automation,
then analyzes profiles with Claude for startup signals.

Actions:
  scan              Run daily LinkedIn search rotation, detect signals, alert on high-tier
  briefing          Compile and send weekly email + WhatsApp summary
  watchlist-update  Re-scan existing tracked people via LinkedIn for new signals
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
GOG_ACCOUNT = config.assistant_email
LINKEDIN_BROWSER_PROFILE = "linkedin"

# LinkedIn rate limits
MAX_LINKEDIN_LOOKUPS_PER_SCAN = 15
MAX_PROFILES_PER_SEARCH = 3
LINKEDIN_NAV_DELAY = 4  # seconds between LinkedIn page navigations

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

# --- LinkedIn Search Queries ---

SEARCH_QUERIES = {
    'li_stealth': {
        'query': 'Israel founder stealth',
        'priority': 'high',
    },
    'li_cto_building': {
        'query': 'Israel CTO building something new',
        'priority': 'high',
    },
    'li_open_opportunities': {
        'query': 'Israel founder open to opportunities',
        'priority': 'high',
    },
    'li_ceo_next_chapter': {
        'query': 'Israel CEO next chapter',
        'priority': 'medium',
    },
    'li_cofounder_exploring': {
        'query': 'Israel co-founder exploring',
        'priority': 'medium',
    },
    'li_8200_talpiot': {
        'query': '8200 Talpiot founder Israel',
        'priority': 'medium',
    },
    'li_new_venture': {
        'query': 'Israel startup founder new venture',
        'priority': 'low',
    },
    'li_vp_left': {
        'query': 'Israel VP Engineering left',
        'priority': 'low',
    },
}

# Priority → max days between runs
PRIORITY_INTERVALS = {
    'high': 1,
    'medium': 2,
    'low': 3,
}

MAX_QUERIES_PER_SCAN = 6
MAX_CLAUDE_CALLS_PER_SCAN = 10


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

    def add_person(self, name, linkedin_url=None, source='linkedin_search'):
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


# --- Claude API ---

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


# --- LinkedIn Browser ---

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
    """Search LinkedIn for people using the browser skill. Returns HTML snapshot text."""
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

        # Use --format html to get profile URLs and headlines
        result = subprocess.run(
            ['openclaw', 'browser', 'snapshot', '--browser-profile', LINKEDIN_BROWSER_PROFILE, '--format', 'html'],
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


# --- Signal Detection ---

def extract_profiles_from_search(search_snapshot):
    """Parse profile URLs, names, and headlines from a LinkedIn search HTML snapshot.

    The HTML snapshot format has entries like:
        - link "Name" [ref=...]:
            - /url: https://www.linkedin.com/in/username?...
        ...
        - generic [ref=...]: Headline text
        - generic [ref=...]: Location

    Returns list of dicts: [{"name": "...", "linkedin_url": "...", "headline": "..."}, ...]
    """
    if not search_snapshot:
        return []

    profiles = []
    seen_urls = set()

    # Split into lines for sequential parsing
    lines = search_snapshot.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for: - link "Person Name" [ref=...]:
        # Followed by: - /url: https://www.linkedin.com/in/...
        name_match = re.match(r'- link "([^"]+)" \[ref=', line)
        if name_match:
            name = name_match.group(1)
            # Skip navigation links, "View X's profile" links
            if name.startswith('View ') or name in ('LinkedIn', 'Home', 'My Network', 'Jobs', 'Messaging', 'Notifications'):
                i += 1
                continue

            # Look for /url on the next few lines
            url = None
            for j in range(i + 1, min(i + 5, len(lines))):
                url_match = re.search(r'/url: (https://www\.linkedin\.com/in/[^\s?]+)', lines[j])
                if url_match:
                    url = url_match.group(1)
                    break

            if url and url not in seen_urls:
                seen_urls.add(url)

                # Look for headline in the nearby lines (typically within ~20 lines after the name link)
                headline = None
                for j in range(i + 5, min(i + 25, len(lines))):
                    hl_line = lines[j].strip()
                    # Headlines appear as: - generic [ref=...]: Headline text
                    hl_match = re.match(r'- generic \[ref=[^\]]+\]: (.+)', hl_line)
                    if hl_match:
                        text = hl_match.group(1).strip()
                        # Skip short texts (connection degree, follower counts, location names)
                        if len(text) > 10 and not text.startswith('View ') and 'degree connection' not in text and 'follower' not in text:
                            headline = text
                            break

                profiles.append({
                    'name': name,
                    'linkedin_url': f"https://www.linkedin.com/in/{url.split('/in/')[-1]}",
                    'headline': headline,
                })

        i += 1

    return profiles


def analyze_linkedin_profile(name, profile_text, linkedin_url, claude_calls_remaining):
    """Analyze a LinkedIn profile snapshot for startup signals."""
    if claude_calls_remaining <= 0:
        return None

    system_prompt = (
        "You are a VC scout analyzing a LinkedIn profile for signs that this person "
        "is about to start a new company. Look for: recent role changes, gaps in employment, "
        "'open to work' status, stealth references, pivot from corporate to startup, "
        "advisory roles at multiple startups, '8200' or 'Talpiot' background, "
        "serial entrepreneur patterns."
    )
    prompt = f"""Analyze this LinkedIn profile for "about to start a company" signals.

NAME: {name}
LINKEDIN URL: {linkedin_url}

PROFILE DATA:
{profile_text[:4000]}

Return ONLY valid JSON (no markdown, no explanation):
{{"name": "{name}", "signals": ["signal1", "signal2"], "confidence": "high|medium|low|none", "summary": "One sentence description", "current_title": "their current role or null", "linkedin_url": "{linkedin_url}"}}

Rules:
- signals: list of specific observations (e.g. "Left CTO role at Company X in Jan 2026", "Profile shows 'Open to work' badge")
- confidence: high = strong evidence of starting something new, medium = suggestive signals, low = weak hints only
- If this person is clearly established at an existing company with no change signals, return confidence "none"
- If no real signals found, return: {{"name": "{name}", "signals": [], "confidence": "none", "summary": "No startup signals detected", "current_title": null, "linkedin_url": "{linkedin_url}"}}"""

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
        f"Stats: {stats.get('queries', 0)} LinkedIn searches, {stats.get('candidates', 0)} candidates screened, {stats.get('flagged', 0)} flagged",
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
    """Run daily LinkedIn search rotation and detect signals."""
    print(f"[{datetime.now()}] Starting Founder Scout daily scan (LinkedIn-only)...")

    db = ScoutDatabase(DB_PATH)

    # LinkedIn browser is REQUIRED
    if not linkedin_browser_available():
        print("  ERROR: LinkedIn browser not available. Cannot run scan.", file=sys.stderr)
        db.log_scan('daily_search')
        return

    print("  LinkedIn browser: available")

    # Get queries due to run
    queue = db.get_rotation_queue(MAX_QUERIES_PER_SCAN)
    if not queue:
        print("  No queries due to run today.")
        db.log_scan('daily_search')
        return

    print(f"  Running {len(queue)} LinkedIn searches...")

    claude_calls = 0
    profile_lookups = 0
    people_found = 0
    signals_detected = 0
    high_alerts = []

    for query_key in queue:
        if claude_calls >= MAX_CLAUDE_CALLS_PER_SCAN:
            print(f"  Claude call limit reached ({MAX_CLAUDE_CALLS_PER_SCAN}), stopping.")
            break
        if profile_lookups >= MAX_LINKEDIN_LOOKUPS_PER_SCAN:
            print(f"  LinkedIn lookup limit reached ({MAX_LINKEDIN_LOOKUPS_PER_SCAN}), stopping.")
            break

        info = SEARCH_QUERIES[query_key]
        query = info['query']
        print(f"    [{query_key}] Searching LinkedIn: {query}...")

        # Step 1: LinkedIn people search
        search_snapshot = linkedin_search(query)
        db.update_rotation(query_key)

        if not search_snapshot:
            print(f"      No search results returned.")
            continue

        # Step 2: Extract profile URLs and names from snapshot (regex, no Claude needed)
        profiles = extract_profiles_from_search(search_snapshot)

        if not profiles:
            print(f"      No profiles extracted from search.")
            continue

        print(f"      Found {len(profiles)} profiles, analyzing top {MAX_PROFILES_PER_SEARCH}...")

        # Step 3: For each extracted profile, do a full profile lookup + analysis
        for profile in profiles[:MAX_PROFILES_PER_SEARCH]:
            if claude_calls >= MAX_CLAUDE_CALLS_PER_SCAN:
                break
            if profile_lookups >= MAX_LINKEDIN_LOOKUPS_PER_SCAN:
                break

            name = profile['name']
            linkedin_url = profile['linkedin_url']

            # Skip if already tracked
            existing = db.get_person_by_name(name)
            if existing:
                continue
            existing_by_url = db.get_person_by_linkedin(linkedin_url)
            if existing_by_url:
                continue

            # Full profile lookup
            print(f"      [{name}] Fetching profile...")
            time.sleep(LINKEDIN_NAV_DELAY)
            profile_text = linkedin_profile_lookup(linkedin_url)
            profile_lookups += 1

            if not profile_text:
                print(f"      [{name}] Profile lookup failed, skipping.")
                continue

            # Claude analyzes profile
            time.sleep(13)
            analysis = analyze_linkedin_profile(
                name, profile_text, linkedin_url,
                MAX_CLAUDE_CALLS_PER_SCAN - claude_calls
            )
            claude_calls += 1

            if not analysis:
                continue

            confidence = analysis.get('confidence', 'none')
            if confidence in ('high', 'medium') and analysis.get('signals'):
                summary = analysis.get('summary', '')
                current_title = analysis.get('current_title')
                if current_title:
                    summary = f"[{current_title}] {summary}"

                person_id = db.add_person(name, linkedin_url, 'linkedin_search')
                if person_id:
                    db.record_signal(
                        person_id, 'linkedin_analysis', confidence, summary, linkedin_url
                    )
                    people_found += 1
                    signals_detected += 1
                    print(f"      [{confidence.upper()}] {name}: {summary[:70]}")

                    if confidence == 'high':
                        high_alerts.append({
                            'name': name,
                            'description': summary,
                            'linkedin_url': linkedin_url,
                        })

    # Send WhatsApp alerts for high-signal founders
    if high_alerts:
        print(f"\n  Sending {len(high_alerts)} high-signal alert(s)...")
        for alert in high_alerts:
            wa_message = format_whatsapp_alert(alert['name'], alert['description'], alert.get('linkedin_url'))
            for recipient in SCOUT_RECIPIENTS:
                send_whatsapp(recipient['phone'], wa_message)

    db.log_scan('daily_search', queries_run=len(queue), people_found=people_found, signals_detected=signals_detected)
    print(f"\n  Scan complete: {len(queue)} searches, {people_found} new people, "
          f"{signals_detected} signals, {claude_calls} Claude calls, "
          f"{profile_lookups} LinkedIn lookups")


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
    """Re-scan existing tracked people for new signals via LinkedIn."""
    print(f"[{datetime.now()}] Running Founder Scout watchlist update (LinkedIn-only)...")

    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()

    if not people:
        print("  No active people in watchlist.")
        db.log_scan('watchlist_update')
        return

    # LinkedIn browser is REQUIRED
    if not linkedin_browser_available():
        print("  ERROR: LinkedIn browser not available. Cannot run watchlist update.", file=sys.stderr)
        db.log_scan('watchlist_update')
        return

    print(f"  LinkedIn browser: available")
    print(f"  Re-scanning {len(people)} active people...")

    claude_calls = 0
    profile_lookups = 0
    new_signals = 0

    for person in people:
        if claude_calls >= MAX_CLAUDE_CALLS_PER_SCAN:
            break
        if profile_lookups >= MAX_LINKEDIN_LOOKUPS_PER_SCAN:
            break

        name = person['name']
        linkedin_url = person.get('linkedin_url')
        print(f"    Checking {name}...")

        profile_text = None

        if linkedin_url:
            # Direct profile lookup
            time.sleep(LINKEDIN_NAV_DELAY)
            profile_text = linkedin_profile_lookup(linkedin_url)
            profile_lookups += 1
        else:
            # Try to find them via LinkedIn search
            print(f"      Searching LinkedIn for {name}...")
            time.sleep(LINKEDIN_NAV_DELAY)
            search_text = linkedin_search(name)
            if search_text:
                li_match = re.search(
                    r'(https://www\.linkedin\.com/in/[a-zA-Z0-9_-]+)', search_text
                )
                if li_match:
                    linkedin_url = li_match.group(1)
                    print(f"      Found profile: {linkedin_url}")
                    # Update the person's LinkedIn URL in the DB
                    conn = sqlite3.connect(db.db_path)
                    conn.execute(
                        'UPDATE tracked_people SET linkedin_url = ? WHERE id = ?',
                        (linkedin_url, person['id'])
                    )
                    conn.commit()
                    conn.close()
                    time.sleep(LINKEDIN_NAV_DELAY)
                    profile_text = linkedin_profile_lookup(linkedin_url)
                    profile_lookups += 1

        if not profile_text:
            conn = sqlite3.connect(db.db_path)
            conn.execute(
                'UPDATE tracked_people SET last_scanned = ? WHERE id = ?',
                (datetime.now().isoformat(), person['id'])
            )
            conn.commit()
            conn.close()
            continue

        # Claude analysis for change detection
        if claude_calls > 0:
            time.sleep(13)

        system_prompt = (
            "You are a VC scout checking for new signals about a person already on our watchlist. "
            "Look for changes since last check: new role, stealth hints, fundraising, advisory roles, "
            "'building something new', company announcements."
        )
        prompt = f"""Check for NEW signals about this person (they're already on our watchlist).

NAME: {name}
LINKEDIN: {linkedin_url or 'unknown'}
LAST KNOWN SIGNAL: {person.get('last_signal', 'None')}

LINKEDIN PROFILE:
{profile_text[:4000]}

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
                            db.record_signal(
                                person['id'], 'watchlist_update',
                                analysis['confidence'], new_summary, linkedin_url
                            )
                            new_signals += 1
                            print(f"      New signal: {new_summary[:60]}")
            except (json.JSONDecodeError, AttributeError):
                pass

        # Update last_scanned
        conn = sqlite3.connect(db.db_path)
        conn.execute(
            'UPDATE tracked_people SET last_scanned = ? WHERE id = ?',
            (datetime.now().isoformat(), person['id'])
        )
        conn.commit()
        conn.close()

    db.log_scan('watchlist_update', queries_run=len(people), signals_detected=new_signals)
    print(f"  Watchlist update complete: {len(people)} checked, {new_signals} new signals, "
          f"{claude_calls} Claude calls, {profile_lookups} LinkedIn lookups")


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
