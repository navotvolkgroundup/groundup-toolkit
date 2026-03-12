#!/usr/bin/env python3
"""
Founder Scout — Proactive discovery of Israeli tech founders about to start new companies.

Discovery is LinkedIn-only: searches LinkedIn people search via browser automation,
then analyzes profiles with Claude for startup signals.

Actions:
  scan              Run daily LinkedIn search rotation, detect signals, alert on high-tier
  briefing          Compile and send weekly email + WhatsApp summary
  watchlist-update  Re-scan existing tracked people via LinkedIn for new signals
  github-scan       Scan GitHub activity of tracked founders (new repos, orgs, activity spikes)
  status            Print tracked people and signal counts
  add <name> [url]  Manually add a person to track
  dismiss <id>      Mark a person as dismissed
  sync-hubspot      Sync all tracked people to HubSpot as lead contacts
  approach <name>   Mark a person as approached (updates DB + HubSpot)
  approach-id <id>  Mark a person as approached by DB id

Usage:
  python3 scout.py scan
  python3 scout.py briefing
  python3 scout.py watchlist-update
  python3 scout.py status
  python3 scout.py add "Yossi Cohen" "https://linkedin.com/in/yossicohen"
  python3 scout.py dismiss 42
  python3 scout.py sync-hubspot
  python3 scout.py approach "Yuval Lev"
"""

import sys
import os
import re
import json
import time
import fcntl
import sqlite3
import contextlib
import tempfile
import subprocess
import requests
from datetime import datetime, timedelta

# Load shared config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config
from lib.claude import call_claude
from lib.whatsapp import send_whatsapp
from lib.email import send_email
from lib.hubspot import (
    search_contact, create_contact, update_contact,
    search_company, create_company, associate_contact_company,
    fetch_deals_by_stage,
)

# --- Configuration ---
LINKEDIN_BROWSER_PROFILE = "linkedin"

# LinkedIn rate limits
MAX_LINKEDIN_LOOKUPS_PER_SCAN = 15
MAX_PROFILES_PER_SEARCH = 3
LINKEDIN_NAV_DELAY = 4  # seconds between LinkedIn page navigations

# Data directory
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, mode=0o700, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, 'founder-scout.db')
LOCK_PATH = os.path.join(_DATA_DIR, 'founder-scout.lock')

# Email recipients for scout reports (from config.yaml founder_scout.recipient_emails)
_SCOUT_EMAILS = set(config._data.get('founder_scout', {}).get('recipient_emails', []))
SCOUT_RECIPIENTS = []
for m in config.team_members:
    if m['email'] in _SCOUT_EMAILS:
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
    'li_exited_startup': {
        'query': 'Israel founder exited startup',
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

    def _conn(self):
        """Return a connection as a context manager for safe cleanup."""
        return contextlib.closing(sqlite3.connect(self.db_path))

    def _init_db(self):
        with self._conn() as conn:
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
            c.execute('''CREATE TABLE IF NOT EXISTS sent_profiles (
                linkedin_url TEXT PRIMARY KEY,
                name TEXT,
                sent_at TEXT NOT NULL
            )''')
            # Migration: add hubspot_contact_id if missing
            cols = [row[1] for row in c.execute('PRAGMA table_info(tracked_people)').fetchall()]
            if 'hubspot_contact_id' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN hubspot_contact_id TEXT')
            if 'approached' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN approached INTEGER DEFAULT 0')
            if 'approached_at' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN approached_at TEXT')
            if 'headline' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN headline TEXT')
            if 'github_url' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN github_url TEXT')
            if 'github_last_scanned' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN github_last_scanned TEXT')
            conn.commit()

    def is_profile_sent(self, linkedin_url):
        with self._conn() as conn:
            result = conn.execute(
                'SELECT 1 FROM sent_profiles WHERE linkedin_url = ?', (linkedin_url,)
            ).fetchone()
        return result is not None

    def mark_profiles_sent(self, profiles):
        with self._conn() as conn:
            now = datetime.now().isoformat()
            for p in profiles:
                conn.execute(
                    'INSERT OR IGNORE INTO sent_profiles (linkedin_url, name, sent_at) VALUES (?, ?, ?)',
                    (p['linkedin_url'], p['name'], now)
                )
            conn.commit()

    def add_person(self, name, linkedin_url=None, source='linkedin_search'):
        with self._conn() as conn:
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

    def get_person_by_name(self, name):
        with self._conn() as conn:
            result = conn.execute(
                'SELECT id, name, linkedin_url, signal_tier, status FROM tracked_people WHERE name = ? AND status = ?',
                (name, 'active')
            ).fetchone()
        return result

    def get_person_by_linkedin(self, url):
        with self._conn() as conn:
            result = conn.execute(
                'SELECT id FROM tracked_people WHERE linkedin_url = ?', (url,)
            ).fetchone()
        return result[0] if result else None

    def get_active_people(self):
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            results = conn.execute(
                'SELECT * FROM tracked_people WHERE status = ? ORDER BY signal_tier DESC, added_at DESC',
                ('active',)
            ).fetchall()
        return [dict(r) for r in results]

    def record_signal(self, person_id, signal_type, tier, description, source_url=None):
        with self._conn() as conn:
            conn.execute(
                'INSERT INTO signal_history (person_id, signal_type, signal_tier, description, source_url, detected_at) VALUES (?, ?, ?, ?, ?, ?)',
                (person_id, signal_type, tier, description, source_url, datetime.now().isoformat())
            )
            conn.execute(
                'UPDATE tracked_people SET signal_tier = ?, last_signal = ?, last_scanned = ? WHERE id = ?',
                (tier, description, datetime.now().isoformat(), person_id)
            )
            conn.commit()

    def get_signals_since(self, since_date):
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            results = conn.execute(
                '''SELECT sh.*, tp.name, tp.linkedin_url
                   FROM signal_history sh
                   JOIN tracked_people tp ON sh.person_id = tp.id
                   WHERE sh.detected_at >= ?
                   ORDER BY sh.signal_tier ASC, sh.detected_at DESC''',
                (since_date,)
            ).fetchall()
        return [dict(r) for r in results]

    def get_rotation_queue(self, max_queries):
        """Select queries due to run based on priority intervals."""
        now = datetime.now()
        with self._conn() as conn:
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

        # Sort: high first, then medium, then low
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        queue.sort(key=lambda x: priority_order[x[1]])

        return [key for key, _ in queue[:max_queries]]

    def update_rotation(self, query_key):
        with self._conn() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO search_rotation (query_key, last_run, run_count) VALUES (?, ?, COALESCE((SELECT run_count FROM search_rotation WHERE query_key = ?), 0) + 1)',
                (query_key, datetime.now().isoformat(), query_key)
            )
            conn.commit()

    def log_scan(self, scan_type, queries_run=0, people_found=0, signals_detected=0):
        with self._conn() as conn:
            conn.execute(
                'INSERT INTO scan_log (scan_type, started_at, completed_at, queries_run, people_found, signals_detected) VALUES (?, ?, ?, ?, ?, ?)',
                (scan_type, datetime.now().isoformat(), datetime.now().isoformat(), queries_run, people_found, signals_detected)
            )
            conn.commit()

    def dismiss_person(self, person_id):
        with self._conn() as conn:
            conn.execute('UPDATE tracked_people SET status = ? WHERE id = ?', ('dismissed', person_id))
            conn.commit()

    def get_stats(self):
        with self._conn() as conn:
            active = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ?', ('active',)).fetchone()[0]
            high = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ? AND signal_tier = ?', ('active', 'high')).fetchone()[0]
            medium = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ? AND signal_tier = ?', ('active', 'medium')).fetchone()[0]
            low = conn.execute('SELECT COUNT(*) FROM tracked_people WHERE status = ? AND signal_tier = ?', ('active', 'low')).fetchone()[0]
            total_signals = conn.execute('SELECT COUNT(*) FROM signal_history').fetchone()[0]
            total_scans = conn.execute('SELECT COUNT(*) FROM scan_log').fetchone()[0]
        return {
            'active': active, 'high': high, 'medium': medium, 'low': low,
            'total_signals': total_signals, 'total_scans': total_scans,
        }

    def set_hubspot_contact_id(self, person_id, contact_id):
        with self._conn() as conn:
            conn.execute(
                'UPDATE tracked_people SET hubspot_contact_id = ? WHERE id = ?',
                (str(contact_id), person_id)
            )
            conn.commit()

    def mark_approached(self, person_id):
        with self._conn() as conn:
            conn.execute(
                'UPDATE tracked_people SET approached = 1, approached_at = ? WHERE id = ?',
                (datetime.now().isoformat(), person_id)
            )
            conn.commit()

    def search_person_by_name(self, name):
        """Fuzzy search for a person by name (case-insensitive, partial match)."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            results = conn.execute(
                "SELECT * FROM tracked_people WHERE status = 'active' AND LOWER(name) LIKE ?",
                (f'%{name.lower()}%',)
            ).fetchall()
        return [dict(r) for r in results]

    def get_unapproached_leads(self, limit=50):
        """Get active people not yet approached, for dashboard display."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            results = conn.execute(
                '''SELECT * FROM tracked_people
                   WHERE status = 'active'
                   ORDER BY
                     CASE signal_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     added_at DESC
                   LIMIT ?''',
                (limit,)
            ).fetchall()
        return [dict(r) for r in results]

    def set_github_url(self, person_id, github_url):
        with self._conn() as conn:
            conn.execute(
                'UPDATE tracked_people SET github_url = ? WHERE id = ?',
                (github_url, person_id)
            )
            conn.commit()

    def update_github_scanned(self, person_id):
        with self._conn() as conn:
            conn.execute(
                'UPDATE tracked_people SET github_last_scanned = ? WHERE id = ?',
                (datetime.now().isoformat(), person_id)
            )
            conn.commit()

    def get_people_with_github(self):
        """Get active people who have a GitHub URL."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            results = conn.execute(
                "SELECT * FROM tracked_people WHERE status = 'active' AND github_url IS NOT NULL ORDER BY github_last_scanned ASC NULLS FIRST",
                ()
            ).fetchall()
        return [dict(r) for r in results]


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


def _strip_aria_chrome(aria_text):
    """Strip LinkedIn navigation chrome from ARIA snapshot, keeping profile content.

    Extracts only lines containing useful profile info (name, headline, experience,
    about, education, etc.) and removes verbose ARIA tree structure.
    """
    useful_lines = []
    in_profile = False
    for line in aria_text.split('\n'):
        stripped = line.strip()
        # Skip empty lines and pure structure lines
        if not stripped or stripped.startswith('- none') or stripped.startswith('- generic'):
            continue
        # Detect start of profile content (past the nav bar)
        if 'heading "' in stripped and not in_profile:
            # Check if this is the person's name heading (first real heading after nav)
            if any(kw in stripped.lower() for kw in ['experience', 'about', 'education']):
                in_profile = True
            elif 'LinkedIn' not in stripped and 'Navigation' not in stripped:
                in_profile = True
        if not in_profile:
            continue
        # Extract text content from ARIA lines
        if 'StaticText "' in stripped:
            text = re.search(r'StaticText "([^"]*)"', stripped)
            if text:
                useful_lines.append(text.group(1))
        elif 'heading "' in stripped:
            text = re.search(r'heading "([^"]*)"', stripped)
            if text:
                useful_lines.append(f"\n## {text.group(1)}")
        elif 'link "' in stripped:
            text = re.search(r'link "([^"]*)"', stripped)
            if text and len(text.group(1)) > 3:
                useful_lines.append(text.group(1))
    return '\n'.join(useful_lines)


def linkedin_profile_lookup(url):
    """Look up a LinkedIn profile using the browser skill. Returns cleaned profile text."""
    try:
        subprocess.run(
            ['openclaw', 'browser', 'navigate', '--browser-profile', LINKEDIN_BROWSER_PROFILE, url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(5)

        result = subprocess.run(
            ['openclaw', 'browser', 'snapshot', '--browser-profile', LINKEDIN_BROWSER_PROFILE,
             '--format', 'aria', '--limit', '1000'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0 or not result.stdout:
            return None
        return _strip_aria_chrome(result.stdout)
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
            # Skip navigation links, "View X's profile" links, and junk entries
            if (name.startswith('View ') or name.startswith('Provides ')
                    or len(name) > 50
                    or name in ('LinkedIn', 'Home', 'My Network', 'Jobs', 'Messaging', 'Notifications')):
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


def filter_relevant_profiles(profiles):
    """Filter profiles by headline keywords — only keep people clearly starting something new.

    Uses deterministic keyword matching instead of Claude (which can't distinguish
    established founders from new ones based on short headlines alone).
    """
    if not profiles:
        return []

    # Positive signals — headline must contain at least one of these
    POSITIVE_SIGNALS = [
        'stealth', 'stealth mode',
        'building something', 'building the future', 'building a ', 'building in ',
        'new venture', 'new startup', 'new company',
        'next chapter', "what's next", 'whats next', 'exploring next',
        'launching', 'just launched',
        'pre-seed', 'pre seed', 'preseed',
        'in formation', 'day one', 'day 1',
        'working on something new', 'starting something',
        'left to start', 'left to build', 'left to found',
        'formerly at', 'formerly @',  # "formerly at X" + no current title = signal
    ]

    # Negative signals — remove even if positive signal matches
    NEGATIVE_TITLES = [
        'investor', 'venture capital', 'vc ', ' vc', 'partner at',
        'managing partner', 'general partner', 'limited partner',
        'angel investor', 'board member', 'board of directors',
        'advisor', 'adviser', 'consultant', 'consulting',
        'mentor', 'coach', 'speaker', 'author',
        'professor', 'lecturer', 'academic', 'researcher',
        'journalist', 'reporter', 'editor',
        'recruiter', 'talent', 'hiring',
    ]

    # Known established companies — founders/CEOs at these are NOT new founders
    ESTABLISHED_COMPANIES = [
        'wix', 'monday', 'check point', 'checkpoint', 'nice', 'amdocs',
        'fiverr', 'similarweb', 'taboola', 'outbrain', 'playtika',
        'ironource', 'ironsource', 'jvp', 'jerusalem venture',
        'viola', 'pitango', 'magma', 'vertex', 'aleph', 'grove ventures',
        'insight partners', 'sequoia', 'a16z', 'ycombinator', 'y combinator',
        'qumra', 'glilot', 'entree capital', 'ourcrowd', 'leumitech',
        'microsoft', 'google', 'meta', 'facebook', 'amazon', 'apple',
        'intel', 'nvidia', 'salesforce', 'oracle', 'ibm', 'cisco',
        'paypal', 'stripe', 'tiktok', 'bytedance', 'uber', 'airbnb',
        'mobileye', 'mellanox', 'cyberark', 'varonis', 'sapiens',
        'elbit', 'rafael', 'iai ', 'israel aerospace',
    ]

    filtered = []
    for p in profiles:
        headline = (p.get('headline') or '').lower().strip()
        if not headline or headline == 'no headline':
            continue

        # Check for negative signals first
        has_negative = any(neg in headline for neg in NEGATIVE_TITLES)
        if has_negative:
            print(f"  Filtered out (negative): {p['name']} — {headline}", file=sys.stderr)
            continue

        # Check for established companies — but skip this check if headline
        # indicates they LEFT that company (ex-, former, formerly, left)
        has_left_prefix = any(prefix in headline for prefix in ['ex-', 'former ', 'formerly ', 'left '])
        if not has_left_prefix:
            at_established = any(co in headline for co in ESTABLISHED_COMPANIES)
            if at_established:
                print(f"  Filtered out (established co): {p['name']} — {headline}", file=sys.stderr)
                continue

        # Check for positive signals
        has_positive = any(sig in headline for sig in POSITIVE_SIGNALS)
        if has_positive:
            print(f"  Kept (positive signal): {p['name']} — {headline}", file=sys.stderr)
            filtered.append(p)
        else:
            print(f"  Filtered out (no signal): {p['name']} — {headline}", file=sys.stderr)

    return filtered


def analyze_linkedin_profile(name, profile_text, linkedin_url, claude_calls_remaining):
    """Analyze a LinkedIn profile snapshot — is this person starting something new?

    Returns dict with: name, relevant (bool), summary, current_title, linkedin_url.
    Uses full profile data (experience, about, headline) for accurate assessment.
    """
    if claude_calls_remaining <= 0:
        return None

    system_prompt = (
        "You are a VC scout for a first-check fund. Your job is to determine whether "
        "a person is CURRENTLY starting a new company (founded in the last 6 months) or "
        "is clearly about to. You have access to their full LinkedIn profile."
    )
    prompt = f"""Analyze this LinkedIn profile. Is this person starting a NEW company?

NAME: {name}
LINKEDIN URL: {linkedin_url}

PROFILE DATA:
{profile_text[:4000]}

Answer with ONLY valid JSON (no markdown):
{{"name": "{name}", "relevant": true/false, "summary": "1-2 sentence explanation", "current_title": "their current role", "linkedin_url": "{linkedin_url}"}}

RELEVANT (true) means:
- They recently founded or co-founded a new company (last ~6 months)
- They are at a stealth startup or building something unnamed
- Their profile explicitly says they are starting something new

NOT RELEVANT (false) means:
- They are a founder/CEO at an ESTABLISHED company (founded years ago)
- They are an investor, VC partner, advisor, or consultant
- They left a job but are not clearly starting something new
- They are at a known company in a senior role
- They are a serial entrepreneur promoting past exits, not a current new venture
- Any ambiguity — when in doubt, return false"""

    response = call_claude(prompt, system_prompt, max_tokens=300)
    if not response:
        return None

    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        print(f"  Could not parse Claude response for {name}: {response[:200]}", file=sys.stderr)
    return None


# send_email and send_whatsapp imported from lib/


# --- Formatting ---

def format_scan_email(recipient_name, profiles):
    """Format daily scan email with relevant profiles."""
    now = datetime.now()
    date_str = now.strftime('%b %d, %Y')

    lines = [
        f"Hi {recipient_name},",
        "",
        f"Today's LinkedIn scout results ({date_str}):",
        "",
    ]

    if profiles:
        lines.append(f"{len(profiles)} relevant profiles found:")
        lines.append("-" * 40)
        for i, p in enumerate(profiles, 1):
            headline = p.get('headline') or ''
            summary = p.get('analysis_summary') or ''
            title = p.get('current_title') or ''
            lines.append(f"{i}. {p['name']}")
            if title:
                lines.append(f"   {title}")
            elif headline:
                lines.append(f"   {headline}")
            if summary:
                lines.append(f"   Why: {summary}")
            lines.append(f"   {p['linkedin_url']}")
            lines.append("")
    else:
        lines.append("No relevant profiles found today.")
        lines.append("")

    lines.extend([
        f"-- {config.assistant_name}",
    ])

    return '\n'.join(lines)


def format_scan_whatsapp(recipient_name, profiles):
    """Format compact WhatsApp daily scan summary."""
    lines = [
        "Founder Scout Daily",
        "",
        f"Hi {recipient_name}, today's scan found {len(profiles)} relevant profiles.",
        "",
    ]

    for i, p in enumerate(profiles[:5], 1):
        summary = p.get('analysis_summary') or ''
        title = p.get('current_title') or p.get('headline') or ''
        entry = f"{i}. {p['name']}"
        if title:
            entry += f" — {title[:50]}"
        if summary:
            entry += f"\n   {summary[:80]}"
        lines.append(entry)

    if len(profiles) > 5:
        lines.append(f"... and {len(profiles) - 5} more")

    lines.extend(["", "Full list sent to your email."])
    return '\n'.join(lines)


def format_briefing_email(recipient_name, high_signals, medium_signals, stats):
    """Format weekly briefing email for watchlist signals."""
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime('%b %d')
    week_end = now.strftime('%b %d, %Y')

    lines = [
        f"Hi {recipient_name},",
        "",
        f"Founder Scout weekly watchlist update ({week_start} - {week_end}).",
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

    if medium_signals:
        lines.append("MEDIUM SIGNAL")
        lines.append("-" * 40)
        for i, s in enumerate(medium_signals, 1):
            lines.append(f"{i}. {s['name']}")
            if s.get('linkedin_url'):
                lines.append(f"   LinkedIn: {s['linkedin_url']}")
            lines.append(f"   Signal: {s.get('description', 'N/A')}")
            lines.append("")

    if not high_signals and not medium_signals:
        lines.append("No new signals on watchlist this week.")
        lines.append("")

    lines.extend([
        f"Watchlist: {stats.get('active', 0)} active people tracked",
        "",
        f"-- {config.assistant_name}",
    ])

    return '\n'.join(lines)


# --- Main Actions ---

def run_daily_scan():
    """Run daily LinkedIn search rotation and send results to team."""
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

    all_new_profiles = []
    seen_urls = set()  # Deduplicate across queries

    for query_key in queue:
        info = SEARCH_QUERIES[query_key]
        query = info['query']
        print(f"    [{query_key}] Searching LinkedIn: {query}...")

        search_snapshot = linkedin_search(query)
        db.update_rotation(query_key)
        time.sleep(LINKEDIN_NAV_DELAY)

        if not search_snapshot:
            print(f"      No search results returned.")
            continue

        profiles = extract_profiles_from_search(search_snapshot)

        # Deduplicate across queries and across previous days
        new_profiles = []
        for p in profiles:
            url = p['linkedin_url']
            if url in seen_urls:
                continue
            if db.is_profile_sent(url):
                continue
            seen_urls.add(url)
            new_profiles.append(p)

        skipped = len(profiles) - len(new_profiles)
        msg = f"      Found {len(new_profiles)} new profiles"
        if skipped:
            msg += f" ({skipped} already seen)"
        print(msg)
        all_new_profiles.extend(new_profiles)

    if not all_new_profiles:
        print("\n  No new profiles found today.")
        db.log_scan('daily_search', queries_run=len(queue))
        return

    # Phase 1: Keyword filter on headlines (fast, removes obvious non-matches)
    print(f"\n  Phase 1: Keyword filtering {len(all_new_profiles)} profiles...")
    keyword_matches = filter_relevant_profiles(all_new_profiles)
    print(f"  {len(keyword_matches)} passed keyword filter (out of {len(all_new_profiles)})")

    # Mark ALL profiles as sent (including filtered-out ones, so they don't reappear)
    db.mark_profiles_sent(all_new_profiles)

    if not keyword_matches:
        print("\n  No relevant profiles found today, skipping email.")
        db.log_scan('daily_search', queries_run=len(queue), people_found=0)
        print(f"\n  Scan complete: {len(queue)} searches, 0 relevant profiles")
        return

    # Phase 2: Visit each profile + Claude deep filter (accurate, ~15s per profile)
    print(f"\n  Phase 2: Visiting {len(keyword_matches)} profiles for deep analysis...")
    relevant = []
    for i, p in enumerate(keyword_matches, 1):
        name = p['name']
        url = p['linkedin_url']
        print(f"    [{i}/{len(keyword_matches)}] Visiting {name}...")

        profile_text = linkedin_profile_lookup(url)
        time.sleep(LINKEDIN_NAV_DELAY)

        if not profile_text:
            print(f"      Could not load profile, skipping.")
            continue

        analysis = analyze_linkedin_profile(name, profile_text, url, MAX_CLAUDE_CALLS_PER_SCAN - len(relevant))
        if not analysis:
            print(f"      Claude analysis failed, skipping.")
            continue

        if analysis.get('relevant'):
            summary = analysis.get('summary', '')
            title = analysis.get('current_title', '')
            print(f"      RELEVANT: {summary}")
            p['analysis_summary'] = summary
            p['current_title'] = title
            # Extract GitHub URL from profile
            gh_url = extract_github_from_linkedin(profile_text)
            if gh_url:
                p['github_url'] = gh_url
                print(f"      Found GitHub: {gh_url}")
            relevant.append(p)
        else:
            summary = analysis.get('summary', 'Not relevant')
            print(f"      Filtered out: {summary}")

    print(f"\n  {len(relevant)} confirmed relevant (out of {len(keyword_matches)} keyword matches)")

    # Send results to team
    if relevant:
        date_str = datetime.now().strftime('%b %d, %Y')
        subject = f"Founder Scout — {date_str}"

        print(f"\n  Sending results ({len(relevant)} people) to team...")
        for recipient in SCOUT_RECIPIENTS:
            email_body = format_scan_email(recipient['first_name'], relevant)
            send_email(recipient['email'], subject, email_body)

            wa_message = format_scan_whatsapp(recipient['first_name'], relevant)
            send_whatsapp(recipient['phone'], wa_message)
    else:
        print("\n  No relevant profiles after deep analysis, skipping email.")

    db.log_scan('daily_search', queries_run=len(queue), people_found=len(relevant))
    print(f"\n  Scan complete: {len(queue)} searches, {len(relevant)} relevant profiles")


def run_weekly_briefing():
    """Send weekly watchlist update — signals from tracked people."""
    print(f"[{datetime.now()}] Sending Founder Scout weekly briefing...")

    db = ScoutDatabase(DB_PATH)
    since = (datetime.now() - timedelta(days=7)).isoformat()
    recent_signals = db.get_signals_since(since)

    high_signals = [s for s in recent_signals if s['signal_tier'] == 'high']
    medium_signals = [s for s in recent_signals if s['signal_tier'] == 'medium']

    db_stats = db.get_stats()
    stats = {'active': db_stats['active']}

    week_str = datetime.now().strftime('%b %d, %Y')
    subject = f"Founder Scout Weekly — {week_str}"

    for recipient in SCOUT_RECIPIENTS:
        email_body = format_briefing_email(
            recipient['first_name'], high_signals, medium_signals, stats
        )
        print(f"  Sending email to {recipient['email']}...")
        send_email(recipient['email'], subject, email_body)

    db.log_scan('weekly_briefing', signals_detected=len(recent_signals))
    print(f"  Briefing sent: {len(high_signals)} high, {len(medium_signals)} medium")


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
                    with db._conn() as conn:
                        conn.execute(
                            'UPDATE tracked_people SET linkedin_url = ? WHERE id = ?',
                            (linkedin_url, person['id'])
                        )
                        conn.commit()
                    time.sleep(LINKEDIN_NAV_DELAY)
                    profile_text = linkedin_profile_lookup(linkedin_url)
                    profile_lookups += 1

        if not profile_text:
            with db._conn() as conn:
                conn.execute(
                    'UPDATE tracked_people SET last_scanned = ? WHERE id = ?',
                    (datetime.now().isoformat(), person['id'])
                )
                conn.commit()
            continue

        # Extract GitHub URL from LinkedIn profile if not already known
        if not person.get('github_url'):
            gh_url = extract_github_from_linkedin(profile_text)
            if gh_url:
                db.set_github_url(person['id'], gh_url)
                print(f"      Found GitHub: {gh_url}")

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
        with db._conn() as conn:
            conn.execute(
                'UPDATE tracked_people SET last_scanned = ? WHERE id = ?',
                (datetime.now().isoformat(), person['id'])
            )
            conn.commit()

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
            approached = " ✓approached" if p.get('approached') else ""
            hs = f" [HS:{p['hubspot_contact_id']}]" if p.get('hubspot_contact_id') else ""
            print(f"    {tier_label} {p['name']}{approached}{hs}{li}{signal}")
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


# --- HubSpot Sync ---

def run_sync_hubspot():
    """Sync tracked people to HubSpot as contacts (leads)."""
    print(f"[{datetime.now()}] Syncing Founder Scout leads to HubSpot...")

    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()

    if not people:
        print("  No active people to sync.")
        return

    created = 0
    updated = 0
    skipped = 0

    for person in people:
        name = person['name']
        linkedin_url = person.get('linkedin_url')
        hubspot_id = person.get('hubspot_contact_id')

        # Already synced — update lead status if approached
        if hubspot_id:
            props = {}
            if person.get('approached'):
                props['hs_lead_status'] = 'ATTEMPTED_TO_CONTACT'
            if props:
                update_contact(hubspot_id, props)
                updated += 1
            else:
                skipped += 1
            continue

        # Search by LinkedIn URL first, then by name
        existing = None
        if linkedin_url:
            existing = search_contact(linkedin_url=linkedin_url)
        if not existing:
            existing = search_contact(name=name)

        if existing:
            hubspot_id = existing['id']
            db.set_hubspot_contact_id(person['id'], hubspot_id)
            props = {'lifecyclestage': 'lead'}
            if person.get('approached'):
                props['hs_lead_status'] = 'ATTEMPTED_TO_CONTACT'
            update_contact(hubspot_id, props)
            updated += 1
            print(f"  Linked existing: {name} → {hubspot_id}")
            continue

        # Create new contact
        parts = name.split(None, 1)
        firstname = parts[0]
        lastname = parts[1] if len(parts) > 1 else ''

        extra_props = {}
        if person.get('approached'):
            extra_props['hs_lead_status'] = 'ATTEMPTED_TO_CONTACT'

        contact_id = create_contact(firstname, lastname, linkedin_url, extra_props)
        if contact_id:
            db.set_hubspot_contact_id(person['id'], contact_id)
            created += 1
        else:
            print(f"  Failed to create contact for {name}", file=sys.stderr)

    # Auto-detect approached: check if any tracked person matches a HubSpot deal
    auto_approached = _auto_detect_approached(db, people)

    print(f"  Sync complete: {created} created, {updated} updated, {skipped} skipped, {auto_approached} auto-approached")


def _auto_detect_approached(db, people):
    """Cross-reference tracked people against HubSpot deals to auto-mark approached.

    Searches all active pipeline deals and checks if any founder name appears
    in a deal name (e.g. deal "Fluent.ai" matches founder at Fluent.ai).
    Also matches by first+last name in deal names/notes.
    """
    unapproached = [p for p in people if not p.get('approached')]
    if not unapproached:
        return 0

    # Fetch all deals from active pipeline stages
    all_deal_names = set()
    try:
        from lib.config import config
        pipeline_config = config._data.get('hubspot', {}).get('pipelines', [{}])[0]
        stages = pipeline_config.get('stages', {})
        for stage_id in stages:
            deals = fetch_deals_by_stage(stage_id, properties=['dealname'])
            for d in deals:
                name = d.get('properties', {}).get('dealname', '')
                if name:
                    all_deal_names.add(name.lower().strip())
    except Exception as e:
        print(f"  Auto-detect: failed to fetch deals: {e}", file=sys.stderr)
        return 0

    if not all_deal_names:
        return 0

    count = 0
    for person in unapproached:
        name = person['name'].lower()
        parts = name.split()
        # Check: person's last name in any deal name, or person's full name
        matched = False
        for deal_name in all_deal_names:
            # Match by last name (most common — deal is named after company, founder's last name often matches)
            if len(parts) > 1 and parts[-1] in deal_name:
                matched = True
                break
            # Match by full name
            if name in deal_name:
                matched = True
                break

        if matched:
            db.mark_approached(person['id'])
            hubspot_id = person.get('hubspot_contact_id')
            if hubspot_id:
                update_contact(hubspot_id, {'hs_lead_status': 'ATTEMPTED_TO_CONTACT'})
            print(f"  Auto-approached: {person['name']} (matched deal)")
            count += 1

    return count


def run_approach(name_query):
    """Mark a person as approached (by name search). Updates local DB + HubSpot."""
    db = ScoutDatabase(DB_PATH)
    matches = db.search_person_by_name(name_query)

    if not matches:
        print(f"No active person found matching '{name_query}'.")
        print("Tip: use 'founder-scout status' to see the full watchlist.")
        sys.exit(1)

    if len(matches) > 1:
        print(f"Multiple matches for '{name_query}':")
        for m in matches:
            tier = f"[{m['signal_tier'].upper()}]" if m.get('signal_tier') else "[---]"
            approached = " (approached)" if m.get('approached') else ""
            print(f"  id={m['id']} {tier} {m['name']}{approached}")
        print("\nUse a more specific name or 'founder-scout approach-id <id>'.")
        return

    person = matches[0]
    person_id = person['id']
    name = person['name']

    # Mark in local DB
    db.mark_approached(person_id)
    print(f"Marked {name} as approached.")

    # Update HubSpot if contact exists
    hubspot_id = person.get('hubspot_contact_id')
    if hubspot_id:
        update_contact(hubspot_id, {'hs_lead_status': 'ATTEMPTED_TO_CONTACT'})
        print(f"  HubSpot contact {hubspot_id} updated: hs_lead_status → ATTEMPTED_TO_CONTACT")
    else:
        print(f"  No HubSpot contact yet. Run 'founder-scout sync-hubspot' to create it.")


def run_approach_by_id(person_id):
    """Mark a person as approached by DB id."""
    db = ScoutDatabase(DB_PATH)
    with db._conn() as conn:
        conn.row_factory = sqlite3.Row
        person = conn.execute(
            'SELECT * FROM tracked_people WHERE id = ?', (int(person_id),)
        ).fetchone()

    if not person:
        print(f"No person found with id={person_id}")
        sys.exit(1)

    person = dict(person)
    db.mark_approached(person['id'])
    print(f"Marked {person['name']} (id={person_id}) as approached.")

    hubspot_id = person.get('hubspot_contact_id')
    if hubspot_id:
        update_contact(hubspot_id, {'hs_lead_status': 'ATTEMPTED_TO_CONTACT'})
        print(f"  HubSpot contact {hubspot_id} updated: hs_lead_status → ATTEMPTED_TO_CONTACT")


# --- GitHub Scanning ---

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')  # Optional, for higher rate limits

def _github_headers():
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'GroundUp-FounderScout'}
    if GITHUB_TOKEN:
        headers['Authorization'] = f'Bearer {GITHUB_TOKEN}'
    return headers


def github_username_from_url(url):
    """Extract GitHub username from a URL like https://github.com/username."""
    if not url:
        return None
    m = re.match(r'https?://github\.com/([A-Za-z0-9_-]+)/?$', url.strip())
    return m.group(1) if m else None


def github_fetch_events(username, max_pages=2):
    """Fetch recent public events for a GitHub user."""
    events = []
    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(
                f"{GITHUB_API_BASE}/users/{username}/events/public?per_page=100&page={page}",
                headers=_github_headers(), timeout=10
            )
            if resp.status_code == 404:
                print(f"    GitHub user {username}: not found", file=sys.stderr)
                return []
            if resp.status_code == 403:
                print(f"    GitHub API rate limited", file=sys.stderr)
                return events
            if resp.status_code != 200:
                print(f"    GitHub API error: {resp.status_code}", file=sys.stderr)
                return events
            page_events = resp.json()
            if not page_events:
                break
            events.extend(page_events)
        except Exception as e:
            print(f"    GitHub fetch error: {e}", file=sys.stderr)
            break
    return events


def github_fetch_repos(username, sort='created', per_page=10):
    """Fetch recent repos for a GitHub user, sorted by creation date."""
    try:
        resp = requests.get(
            f"{GITHUB_API_BASE}/users/{username}/repos?sort={sort}&direction=desc&per_page={per_page}&type=owner",
            headers=_github_headers(), timeout=10
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def github_fetch_orgs(username):
    """Fetch public organizations for a GitHub user."""
    try:
        resp = requests.get(
            f"{GITHUB_API_BASE}/users/{username}/orgs",
            headers=_github_headers(), timeout=10
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def analyze_github_activity(username, person_name, last_scanned=None):
    """
    Analyze a GitHub user's recent activity for startup signals.

    Returns list of signals: [{"type": "...", "tier": "high|medium|low", "description": "...", "url": "..."}]
    """
    signals = []
    cutoff = datetime.fromisoformat(last_scanned) if last_scanned else datetime.now() - timedelta(days=30)

    # 1. Check for new repos (strongest signal)
    repos = github_fetch_repos(username, sort='created', per_page=20)
    new_repos = []
    for repo in repos:
        created = datetime.fromisoformat(repo['created_at'].replace('Z', '+00:00')).replace(tzinfo=None)
        if created > cutoff and not repo.get('fork'):
            new_repos.append(repo)

    for repo in new_repos:
        name = repo['name']
        desc = repo.get('description') or ''
        lang = repo.get('language') or ''
        stars = repo.get('stargazers_count', 0)
        has_pages = repo.get('has_pages', False)
        homepage = repo.get('homepage') or ''
        repo_url = repo['html_url']

        # Score the repo — is this a product/startup or just a personal project?
        is_product = False
        product_hints = ['landing', 'website', 'app', 'platform', 'api', 'sdk', 'saas', 'demo']
        if any(h in name.lower() or h in desc.lower() for h in product_hints):
            is_product = True
        if has_pages or (homepage and 'github.io' not in homepage):
            is_product = True
        if stars >= 5:
            is_product = True

        # High tier: product-looking repo with description or custom domain
        if is_product and (desc or homepage):
            tier = 'high'
            description = f"New repo '{name}'"
            if desc:
                description += f": {desc[:100]}"
            if homepage:
                description += f" ({homepage})"
            signals.append({'type': 'github_new_repo', 'tier': tier, 'description': description, 'url': repo_url})
        elif desc or lang:
            tier = 'medium'
            description = f"New repo '{name}'"
            if desc:
                description += f": {desc[:100]}"
            elif lang:
                description += f" ({lang})"
            signals.append({'type': 'github_new_repo', 'tier': tier, 'description': description, 'url': repo_url})
        else:
            # Bare repo, low signal
            signals.append({'type': 'github_new_repo', 'tier': 'low', 'description': f"New repo '{name}'", 'url': repo_url})

    # 2. Check for new organizations (strong signal — might be a new company)
    orgs = github_fetch_orgs(username)
    for org in orgs:
        org_url = f"https://github.com/{org['login']}"
        # We can't easily tell when they joined, so check org creation date
        try:
            org_resp = requests.get(
                f"{GITHUB_API_BASE}/orgs/{org['login']}",
                headers=_github_headers(), timeout=10
            )
            if org_resp.status_code == 200:
                org_data = org_resp.json()
                created = datetime.fromisoformat(org_data['created_at'].replace('Z', '+00:00')).replace(tzinfo=None)
                if created > cutoff:
                    desc = org_data.get('description') or org_data.get('name', org['login'])
                    signals.append({
                        'type': 'github_new_org',
                        'tier': 'high',
                        'description': f"New GitHub org '{org['login']}': {desc[:100]}",
                        'url': org_url,
                    })
        except Exception:
            pass

    # 3. Detect activity spikes from events
    events = github_fetch_events(username, max_pages=1)
    recent_events = [
        e for e in events
        if datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')).replace(tzinfo=None) > cutoff
    ]

    if len(recent_events) >= 30:
        # Activity spike — 30+ events since last scan
        event_types = {}
        for e in recent_events:
            event_types[e['type']] = event_types.get(e['type'], 0) + 1
        top_types = sorted(event_types.items(), key=lambda x: -x[1])[:3]
        summary = ', '.join(f"{count} {t.replace('Event','')}" for t, count in top_types)
        signals.append({
            'type': 'github_activity_spike',
            'tier': 'medium',
            'description': f"GitHub activity spike: {len(recent_events)} events ({summary})",
            'url': f"https://github.com/{username}",
        })

    return signals


def extract_github_from_linkedin(profile_text):
    """Try to extract a GitHub URL from LinkedIn profile text."""
    if not profile_text:
        return None
    m = re.search(r'(https?://github\.com/[A-Za-z0-9_-]+)(?:\s|$|[)\]<])', profile_text)
    return m.group(1) if m else None


def run_github_scan():
    """Scan GitHub activity of tracked founders who have GitHub URLs."""
    print(f"[{datetime.now()}] Running Founder Scout GitHub scan...")

    db = ScoutDatabase(DB_PATH)
    people = db.get_people_with_github()

    if not people:
        print("  No tracked people with GitHub URLs.")
        print("  Tip: GitHub URLs are extracted from LinkedIn profiles during watchlist-update.")
        db.log_scan('github_scan')
        return

    print(f"  Scanning {len(people)} GitHub profiles...")
    total_signals = 0

    for person in people:
        name = person['name']
        github_url = person['github_url']
        username = github_username_from_url(github_url)
        if not username:
            print(f"    {name}: invalid GitHub URL '{github_url}', skipping")
            continue

        print(f"    [{person['id']}] {name} (@{username})...")
        last_scanned = person.get('github_last_scanned')

        signals = analyze_github_activity(username, name, last_scanned)

        for sig in signals:
            db.record_signal(person['id'], sig['type'], sig['tier'], sig['description'], sig.get('url'))
            total_signals += 1
            tier_label = sig['tier'].upper()
            print(f"      [{tier_label}] {sig['description'][:80]}")

        db.update_github_scanned(person['id'])
        time.sleep(1)  # Be polite to GitHub API

    print(f"  GitHub scan complete: {len(people)} profiles, {total_signals} signals detected.")
    db.log_scan('github_scan', queries_run=len(people), signals_detected=total_signals)

    # Send alerts for high-tier GitHub signals
    if total_signals > 0:
        recent = db.get_signals_since((datetime.now() - timedelta(minutes=10)).isoformat())
        github_signals = [s for s in recent if s.get('signal_type', '').startswith('github_')]
        high_signals = [s for s in github_signals if s['signal_tier'] == 'high']

        if high_signals and SCOUT_RECIPIENTS:
            subject = f"🐙 GitHub Alert: {len(high_signals)} new signal{'s' if len(high_signals) > 1 else ''}"
            body_lines = [f"<h3>GitHub Signals Detected</h3>"]
            for s in high_signals:
                url = s.get('source_url', '')
                body_lines.append(
                    f"<p><b>{s['name']}</b>: {s['description']}"
                    + (f' — <a href="{url}">{url}</a>' if url else '')
                    + "</p>"
                )

            for recip in SCOUT_RECIPIENTS:
                send_email(recip['email'], subject, '\n'.join(body_lines))
                print(f"  Emailed {recip['first_name']}")


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

    elif action == 'sync-hubspot':
        run_sync_hubspot()

    elif action == 'approach':
        if len(sys.argv) < 3:
            print("Usage: scout.py approach <name>")
            sys.exit(1)
        run_approach(' '.join(sys.argv[2:]))

    elif action == 'approach-id':
        if len(sys.argv) < 3:
            print("Usage: scout.py approach-id <id>")
            sys.exit(1)
        run_approach_by_id(sys.argv[2])

    elif action == 'github-scan':
        run_github_scan()

    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
