#!/usr/bin/env python3
"""
Founder Scout — Automated discovery pipeline for Israeli tech founders about to start
new companies. Built for GroundUp Ventures (first-check fund).

How it works:

  1. DISCOVER (daily scan)
     Rotates through 8 LinkedIn keyword searches ("Israel founder stealth",
     "Israel CTO building something new", etc.) using headless Chromium.
     Two-phase filtering: fast keyword match on headlines, then full profile
     visit + Claude analysis to confirm the person is genuinely starting
     something new in the last ~6 months. Confirmed founders are automatically
     added to the watchlist and the team gets an email + WhatsApp alert.

  2. MONITOR (watchlist update, Tue/Thu/Sat)
     Re-visits LinkedIn profiles of everyone on the watchlist. Claude checks
     for changes since last scan: new role, stealth hints, fundraising signals,
     company announcements. Also extracts GitHub URLs from profiles when found.

  3. GITHUB SCAN (daily)
     For tracked founders with a GitHub URL, checks the GitHub API for:
     - New repos (scored HIGH if product-looking, MEDIUM otherwise)
     - New GitHub orgs (HIGH — may indicate a new company)
     - Activity spikes of 30+ events (MEDIUM)
     Emails the team immediately on HIGH-tier GitHub signals.

  4. SYNC TO CRM (daily, after scan)
     Pushes all tracked people to HubSpot as lead contacts. Cross-references
     against existing deals to auto-detect founders already approached.

  5. WEEKLY BRIEFING (Sundays)
     Compiles all HIGH and MEDIUM signals from the past 7 days into a
     summary email.

Data lives in SQLite (data/founder-scout.db). Signals are deduplicated
within a 7-day window. LinkedIn browser runs as Christina Chang via
OpenClaw browser automation.

Actions:
  scan              Daily LinkedIn search rotation + Claude analysis + alert
  briefing          Weekly email summary of all signals
  watchlist-update  Re-scan tracked people on LinkedIn for changes
  github-scan       Enhanced GitHub scan (repos, orgs, infra, npm, activity)
  registrar-scan    Scan Israeli Companies Registrar for new tech companies
  retention-update  Update acquisition retention clocks
  acquisition-scan  Search for new Israeli startup acquisitions (monthly)
  domain-scan       Check domain registrations for watchlist members
  event-scan        Search for watchlist members at startup events
  score-update      Recalculate composite scores for all tracked people
  digest            Send daily digest of CRITICAL/HIGH signals
  sync-hubspot      Push tracked people to HubSpot as lead contacts
  status            Print watchlist, scores, and signal counts
  add <name> [url]  Manually add a person to the watchlist
  dismiss <id>      Remove a person from the watchlist
  approach <name>   Mark a person as approached (DB + HubSpot)
  approach-id <id>  Mark a person as approached by DB id

Usage:
  python3 scout.py scan
  python3 scout.py briefing
  python3 scout.py watchlist-update
  python3 scout.py github-scan
  python3 scout.py registrar-scan
  python3 scout.py retention-update
  python3 scout.py acquisition-scan
  python3 scout.py domain-scan
  python3 scout.py event-scan
  python3 scout.py score-update
  python3 scout.py digest
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
import logging
import sqlite3
import contextlib
import tempfile
import subprocess
import requests
from datetime import datetime, timedelta

log = logging.getLogger("founder-scout")

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
from lib.brave import brave_search

# --- v2 Modules ---
from modules.idf_classifier import (
    classify_idf_unit, init_idf_tables, save_idf_profile, get_idf_profile, seed_company_mappings,
)
from modules.going_dark import (
    init_activity_tables, extract_activity_metrics, save_activity_snapshot, detect_going_dark,
)
from modules.advisor_tracker import (
    extract_advisory_roles, detect_advisory_accumulation, extract_verticals,
)
from modules.github_enhanced import enhanced_github_scan, search_github_user
from modules.scoring import (
    init_score_tables, calculate_composite_score, save_score, get_latest_score,
    get_score_changes, classify as classify_score,
)
from modules.registrar import init_registrar_tables, scan_registrar
from modules.retention_clock import (
    init_retention_tables, update_all_statuses, get_approaching_founders,
    scan_for_acquisitions, get_expiring_founders,
)
from modules.domain_monitor import init_domain_tables, scan_domains_for_person, save_domain_signal
from modules.event_tracker import init_event_tables, scan_events
from modules.social_graph import (
    init_social_tables, extract_connections_from_profile, detect_lawyer_vc_connections,
    detect_team_formation, scan_social_signals,
)
from modules.competitive_intel import (
    init_competitive_tables, extract_vc_mentions_from_profile, scan_competitive_signals,
)

# --- Extracted modules ---
from modules.linkedin import (
    linkedin_browser_available, linkedin_search, linkedin_profile_lookup,
    extract_profiles_from_search, filter_relevant_profiles,
    analyze_linkedin_profile, extract_github_from_linkedin,
    LINKEDIN_NAV_DELAY,
)
from modules.github_scan import (
    github_username_from_url, analyze_github_activity,
)
from modules.hubspot_sync import (
    run_sync_hubspot, run_approach, run_approach_by_id,
    sync_new_leads_to_hubspot,
)
from modules.notifications import (
    format_scan_email, format_scan_whatsapp, format_briefing_email,
    send_scan_results, send_github_alerts, send_registrar_alerts,
)
from modules.report import (
    run_weekly_briefing, run_daily_digest, run_status_v2,
)

# --- Configuration ---

# LinkedIn rate limits
MAX_LINKEDIN_LOOKUPS_PER_SCAN = 15
MAX_PROFILES_PER_SEARCH = 3

# Data directory
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, mode=0o700, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, 'founder-scout.db')
LOCK_PATH = os.path.join(_DATA_DIR, 'founder-scout.lock')

# Email recipients for scout reports (from config.yaml founder_scout.recipient_emails)
_SCOUT_EMAILS = set(config.founder_scout.get('recipient_emails', []))
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
            # v2 columns
            if 'advisory_count' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN advisory_count INTEGER DEFAULT 0')
            if 'advisory_roles_json' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN advisory_roles_json TEXT')
            if 'composite_score' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN composite_score INTEGER DEFAULT 0')
            if 'score_classification' not in cols:
                c.execute('ALTER TABLE tracked_people ADD COLUMN score_classification TEXT DEFAULT "WATCHING"')
            conn.commit()

            # Initialize v2 module tables
            init_idf_tables(conn)
            init_activity_tables(conn)
            init_score_tables(conn)
            init_registrar_tables(conn)
            init_retention_tables(conn)
            init_domain_tables(conn)
            init_event_tables(conn)
            init_social_tables(conn)
            init_competitive_tables(conn)
            seed_company_mappings(conn)
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
            # Dedup: skip if same person + type + description already exists in last 7 days
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            existing = conn.execute(
                '''SELECT 1 FROM signal_history
                   WHERE person_id = ? AND signal_type = ? AND description = ? AND detected_at >= ?''',
                (person_id, signal_type, description, week_ago)
            ).fetchone()
            if existing:
                return False

            conn.execute(
                'INSERT INTO signal_history (person_id, signal_type, signal_tier, description, source_url, detected_at) VALUES (?, ?, ?, ?, ?, ?)',
                (person_id, signal_type, tier, description, source_url, datetime.now().isoformat())
            )
            conn.execute(
                'UPDATE tracked_people SET signal_tier = ?, last_signal = ?, last_scanned = ? WHERE id = ?',
                (tier, description, datetime.now().isoformat(), person_id)
            )
            conn.commit()
            return True

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


# --- Main Actions ---

def run_daily_scan():
    """Run daily LinkedIn search rotation and send results to team."""
    log.info("Starting Founder Scout daily scan (LinkedIn-only)...")

    db = ScoutDatabase(DB_PATH)

    # LinkedIn browser is REQUIRED
    if not linkedin_browser_available():
        log.error("LinkedIn browser not available. Cannot run scan.")
        db.log_scan('daily_search')
        return

    log.info("LinkedIn browser: available")

    # Get queries due to run
    queue = db.get_rotation_queue(MAX_QUERIES_PER_SCAN)
    if not queue:
        log.info("No queries due to run today.")
        db.log_scan('daily_search')
        return

    log.info("Running %d LinkedIn searches...", len(queue))

    all_new_profiles = []
    seen_urls = set()  # Deduplicate across queries

    for query_key in queue:
        info = SEARCH_QUERIES[query_key]
        query = info['query']
        log.info("[%s] Searching LinkedIn: %s...", query_key, query)

        search_snapshot = linkedin_search(query)
        db.update_rotation(query_key)
        time.sleep(LINKEDIN_NAV_DELAY)

        if not search_snapshot:
            log.warning("No search results returned.")
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
        msg = f"Found {len(new_profiles)} new profiles"
        if skipped:
            msg += f" ({skipped} already seen)"
        log.info(msg)
        all_new_profiles.extend(new_profiles)

    if not all_new_profiles:
        log.info("No new profiles found today.")
        db.log_scan('daily_search', queries_run=len(queue))
        return

    # Phase 1: Keyword filter on headlines (fast, removes obvious non-matches)
    log.info("Phase 1: Keyword filtering %d profiles...", len(all_new_profiles))
    keyword_matches = filter_relevant_profiles(all_new_profiles)
    log.info("%d passed keyword filter (out of %d)", len(keyword_matches), len(all_new_profiles))

    # Mark ALL profiles as sent (including filtered-out ones, so they don't reappear)
    db.mark_profiles_sent(all_new_profiles)

    if not keyword_matches:
        log.info("No relevant profiles found today, skipping email.")
        db.log_scan('daily_search', queries_run=len(queue), people_found=0)
        log.info("Scan complete: %d searches, 0 relevant profiles", len(queue))
        return

    # Phase 2: Visit each profile + Claude deep filter (accurate, ~15s per profile)
    log.info("Phase 2: Visiting %d profiles for deep analysis...", len(keyword_matches))
    relevant = []
    for i, p in enumerate(keyword_matches, 1):
        name = p['name']
        url = p['linkedin_url']
        log.info("[%d/%d] Visiting %s...", i, len(keyword_matches), name)

        profile_text = linkedin_profile_lookup(url)
        time.sleep(LINKEDIN_NAV_DELAY)

        if not profile_text:
            log.warning("Could not load profile, skipping.")
            continue

        analysis = analyze_linkedin_profile(name, profile_text, url, MAX_CLAUDE_CALLS_PER_SCAN - len(relevant))
        if not analysis:
            log.warning("Claude analysis failed, skipping.")
            continue

        if analysis.get('relevant'):
            summary = analysis.get('summary', '')
            title = analysis.get('current_title', '')
            log.info("RELEVANT: %s", summary)
            p['analysis_summary'] = summary
            p['current_title'] = title

            # Add to watchlist (idempotent — INSERT OR IGNORE on linkedin_url)
            person_id = db.add_person(name, url, 'daily_scan')
            if person_id:
                db.record_signal(person_id, 'linkedin_new_founder', 'high', summary, url)
                headline = p.get('headline') or title
                if headline:
                    with db._conn() as conn:
                        conn.execute('UPDATE tracked_people SET headline = ? WHERE id = ?', (headline, person_id))
                        conn.commit()

            # Extract GitHub URL from profile
            gh_url = extract_github_from_linkedin(profile_text)
            if gh_url:
                p['github_url'] = gh_url
                log.info("Found GitHub: %s", gh_url)
                if person_id:
                    db.set_github_url(person_id, gh_url)

            relevant.append(p)
        else:
            summary = analysis.get('summary', 'Not relevant')
            log.debug("Filtered out: %s", summary)

    log.info("%d confirmed relevant (out of %d keyword matches)", len(relevant), len(keyword_matches))

    # Send results to team
    if relevant:
        send_scan_results(SCOUT_RECIPIENTS, relevant)
        # Push to HubSpot as leads
        sync_new_leads_to_hubspot(db, relevant)
    else:
        log.info("No relevant profiles after deep analysis, skipping email.")

    db.log_scan('daily_search', queries_run=len(queue), people_found=len(relevant))
    log.info("Scan complete: %d searches, %d relevant profiles", len(queue), len(relevant))


def run_watchlist_update():
    """Re-scan existing tracked people for new signals via LinkedIn."""
    log.info("Running Founder Scout watchlist update (LinkedIn-only)...")

    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()

    if not people:
        log.info("No active people in watchlist.")
        db.log_scan('watchlist_update')
        return

    # LinkedIn browser is REQUIRED
    if not linkedin_browser_available():
        log.error("LinkedIn browser not available. Cannot run watchlist update.")
        db.log_scan('watchlist_update')
        return

    log.info("LinkedIn browser: available")
    log.info("Re-scanning %d active people...", len(people))

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
        log.debug("Checking %s...", name)

        profile_text = None

        if linkedin_url:
            # Direct profile lookup
            time.sleep(LINKEDIN_NAV_DELAY)
            profile_text = linkedin_profile_lookup(linkedin_url)
            profile_lookups += 1
        else:
            # Try to find them via LinkedIn search
            log.debug("Searching LinkedIn for %s...", name)
            time.sleep(LINKEDIN_NAV_DELAY)
            search_text = linkedin_search(name)
            if search_text:
                li_match = re.search(
                    r'(https://www\.linkedin\.com/in/[a-zA-Z0-9_-]+)', search_text
                )
                if li_match:
                    linkedin_url = li_match.group(1)
                    log.info("Found profile: %s", linkedin_url)
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
                log.info("Found GitHub: %s", gh_url)

        # --- v2 piggyback analysis (no extra LinkedIn requests) ---
        try:
            # IDF unit classification
            idf_data = classify_idf_unit(profile_text, name)
            if idf_data and idf_data.get('score', 0) >= 20:
                with db._conn() as conn:
                    save_idf_profile(conn, person['id'], idf_data)
                    conn.commit()
                log.info("IDF: %s (%s)", idf_data.get('unit', '?'), idf_data.get('level', '?'))

            # Activity metrics for going-dark detection
            metrics = extract_activity_metrics(profile_text)
            if metrics:
                with db._conn() as conn:
                    save_activity_snapshot(conn, person['id'], metrics)
                    conn.commit()
                dark_signal = detect_going_dark(db._conn().__enter__(), person['id'])
                if dark_signal:
                    db.record_signal(person['id'], dark_signal['signal_type'],
                                     dark_signal['tier'], dark_signal['description'], linkedin_url)
                    new_signals += 1
                    log.info("Going dark: %s", dark_signal['description'][:60])

            # Advisory role tracking
            advisory_roles = extract_advisory_roles(profile_text)
            prev_count = person.get('advisory_count', 0)
            adv_signal = detect_advisory_accumulation(advisory_roles, prev_count)
            if advisory_roles is not None:
                with db._conn() as conn:
                    conn.execute(
                        'UPDATE tracked_people SET advisory_count = ?, advisory_roles_json = ? WHERE id = ?',
                        (len(advisory_roles), json.dumps([r for r in advisory_roles if r.get('is_advisory')]),
                         person['id'])
                    )
                    conn.commit()
            if adv_signal and adv_signal['tier'] in ('high', 'medium'):
                db.record_signal(person['id'], adv_signal['signal_type'],
                                 adv_signal['tier'], adv_signal['description'], linkedin_url)
                new_signals += 1
                log.info("Advisory: %s", adv_signal['description'][:60])

            # Social graph: lawyer/VC connections
            social_signals = detect_lawyer_vc_connections(profile_text, name)
            for ss in social_signals:
                db.record_signal(person['id'], ss.get('signal_type', 'social_connection'),
                                 ss.get('tier', 'medium'), ss.get('description', ''), linkedin_url)
                new_signals += 1

            # Competitive intel: VC mentions in profile
            vc_mentions = extract_vc_mentions_from_profile(profile_text)
            if vc_mentions:
                with db._conn() as conn:
                    for vm in vc_mentions:
                        conn.execute(
                            '''INSERT INTO competitive_signals
                               (person_id, vc_firm, vc_partner_name, signal_type, signal_detail, detected_date)
                               VALUES (?, ?, ?, ?, ?, ?)''',
                            (person['id'], vm.get('vc_firm', ''), vm.get('partner', ''),
                             'linkedin_mention', vm.get('detail', ''), datetime.now().isoformat())
                        )
                    conn.commit()
                log.info("VC mentions: %d", len(vc_mentions))
        except Exception as e:
            log.error("v2 analysis error: %s", e)

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
                            log.info("New signal: %s", new_summary[:60])
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
    log.info("Watchlist update complete: %d checked, %d new signals, %d Claude calls, %d LinkedIn lookups",
             len(people), new_signals, claude_calls, profile_lookups)


def run_add(name, linkedin_url=None):
    """Manually add a person to track."""
    db = ScoutDatabase(DB_PATH)
    person_id = db.add_person(name, linkedin_url or None, 'manual')
    if person_id:
        log.info("Added %s to watchlist (id=%d)", name, person_id)
        if linkedin_url:
            log.info("LinkedIn: %s", linkedin_url)
    else:
        log.warning("Could not add %s (may already exist)", name)


def run_dismiss(person_id):
    """Mark a person as dismissed."""
    db = ScoutDatabase(DB_PATH)
    db.dismiss_person(int(person_id))
    log.info("Dismissed person id=%s", person_id)


def run_github_scan():
    """Scan GitHub activity of tracked founders who have GitHub URLs."""
    log.info("Running Founder Scout GitHub scan...")

    db = ScoutDatabase(DB_PATH)
    people = db.get_people_with_github()

    if not people:
        log.info("No tracked people with GitHub URLs.")
        log.info("Tip: GitHub URLs are extracted from LinkedIn profiles during watchlist-update.")
        db.log_scan('github_scan')
        return

    log.info("Scanning %d GitHub profiles...", len(people))
    total_signals = 0

    for person in people:
        name = person['name']
        github_url = person['github_url']
        username = github_username_from_url(github_url)
        if not username:
            log.warning("%s: invalid GitHub URL '%s', skipping", name, github_url)
            continue

        log.debug("[%d] %s (@%s)...", person['id'], name, username)
        last_scanned = person.get('github_last_scanned')

        signals = analyze_github_activity(username, name, last_scanned)

        for sig in signals:
            db.record_signal(person['id'], sig['type'], sig['tier'], sig['description'], sig.get('url'))
            total_signals += 1
            log.info("[%s] %s", sig['tier'].upper(), sig['description'][:80])

        db.update_github_scanned(person['id'])
        time.sleep(1)  # Be polite to GitHub API

    log.info("GitHub scan complete: %d profiles, %d signals detected.", len(people), total_signals)
    db.log_scan('github_scan', queries_run=len(people), signals_detected=total_signals)

    # Send alerts for high-tier GitHub signals
    if total_signals > 0:
        recent = db.get_signals_since((datetime.now() - timedelta(minutes=10)).isoformat())
        github_signals = [s for s in recent if s.get('signal_type', '').startswith('github_')]
        high_signals = [s for s in github_signals if s['signal_tier'] == 'high']
        send_github_alerts(SCOUT_RECIPIENTS, high_signals)


# --- v2 Actions ---

def run_registrar_scan():
    """Scan Israeli Companies Registrar for new tech company registrations."""
    log.info("Running Companies Registrar scan...")
    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()
    with db._conn() as conn:
        signals = scan_registrar(conn, people)
        conn.commit()
    for sig in signals:
        person_id = sig.get('matched_person_id')
        if person_id:
            db.record_signal(person_id, 'company_registration', sig.get('tier', 'high'),
                             sig['description'], sig.get('registration_number'))
        log.info("[%s] %s", sig.get('tier', '?').upper(), sig['description'][:80])
    log.info("Registrar scan complete: %d signals.", len(signals))
    db.log_scan('registrar_scan', signals_detected=len(signals))

    # Immediate alert for company registration matches
    high_signals = [s for s in signals if s.get('tier') == 'high']
    send_registrar_alerts(SCOUT_RECIPIENTS, high_signals)


def run_retention_update():
    """Recalculate retention clock statuses for all acquisition founders."""
    log.info("Updating retention clocks...")
    db = ScoutDatabase(DB_PATH)
    with db._conn() as conn:
        changes = update_all_statuses(conn)
        conn.commit()
    if changes:
        for c in changes:
            log.info("Status change: %s -> %s", c.get('name', '?'), c.get('new_status', '?'))
    approaching = []
    with db._conn() as conn:
        approaching = get_approaching_founders(conn)
    log.info("%d founders approaching/imminent vesting end.", len(approaching))

    # Add approaching founders to watchlist if not already tracked
    for f in approaching:
        if f.get('founder_linkedin_url'):
            existing = db.get_person_by_linkedin(f['founder_linkedin_url'])
            if not existing:
                person_id = db.add_person(f['founder_name'], f['founder_linkedin_url'], 'retention_clock')
                if person_id:
                    db.record_signal(person_id, 'retention_clock',
                                     'high' if f.get('current_status') == 'IMMINENT' else 'medium',
                                     f"Vesting {f.get('current_status', '?')} at {f.get('acquiring_company', '?')} (acquired {f.get('acquired_company', '?')})",
                                     f.get('founder_linkedin_url'))
                    log.info("Added to watchlist: %s (%s)", f['founder_name'], f.get('current_status'))

    db.log_scan('retention_update', signals_detected=len(changes))


def run_acquisition_scan():
    """Monthly scan for new Israeli startup acquisitions via Brave Search."""
    log.info("Scanning for new acquisitions...")
    db = ScoutDatabase(DB_PATH)
    with db._conn() as conn:
        count = scan_for_acquisitions(conn, brave_search)
        conn.commit()
    log.info("Found %d new acquisitions.", count)
    db.log_scan('acquisition_scan', people_found=count)


def run_domain_scan():
    """Check domain registrations for watchlist members."""
    log.info("Running domain scan...")
    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()
    total_signals = 0
    for person in people:
        name = person['name']
        signals = scan_domains_for_person(name, person['id'], brave_search_fn=brave_search)
        for sig in signals:
            with db._conn() as conn:
                save_domain_signal(conn, sig)
                conn.commit()
            if sig.get('signal_level') in ('HIGH', 'MEDIUM'):
                db.record_signal(person['id'], 'domain_registration',
                                 sig['signal_level'].lower(), sig.get('description', f"Domain: {sig.get('domain_name')}"))
                total_signals += 1
                log.info("[%s] %s: %s", sig['signal_level'], person['name'], sig.get('domain_name'))
        time.sleep(0.5)  # Rate limiting for DNS lookups
    log.info("Domain scan complete: %d signals.", total_signals)
    db.log_scan('domain_scan', queries_run=len(people), signals_detected=total_signals)


def run_event_scan():
    """Weekly scan for watchlist members at startup events."""
    log.info("Running event/hackathon scan...")
    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()
    with db._conn() as conn:
        signals = scan_events(conn, people, brave_search)
        conn.commit()
    for sig in signals:
        person_id = sig.get('matched_person_id')
        if person_id:
            db.record_signal(person_id, 'event_appearance',
                             sig.get('signal_level', 'medium').lower(),
                             sig.get('description', ''))
    log.info("Event scan complete: %d signals.", len(signals))
    db.log_scan('event_scan', signals_detected=len(signals))


def run_score_update():
    """Recalculate composite scores for all tracked people."""
    log.info("Recalculating composite scores...")
    db = ScoutDatabase(DB_PATH)
    people = db.get_active_people()
    since_30d = (datetime.now() - timedelta(days=30)).isoformat()

    for person in people:
        try:
            # Gather all data for scoring
            with db._conn() as conn:
                signals = conn.execute(
                    '''SELECT * FROM signal_history WHERE person_id = ? AND detected_at >= ?''',
                    (person['id'], since_30d)
                ).fetchall()
                signals = [dict(zip([d[0] for d in conn.execute('PRAGMA table_info(signal_history)').fetchall()
                                     if d[0]], r)) if not isinstance(r, dict) else r for r in signals]
                # Simpler: just get as list of dicts
                conn.row_factory = __import__('sqlite3').Row
                signals = [dict(r) for r in conn.execute(
                    'SELECT * FROM signal_history WHERE person_id = ? AND detected_at >= ?',
                    (person['id'], since_30d)
                ).fetchall()]

                idf_data = get_idf_profile(conn, person['id'])

            # Detect going dark status
            going_dark = False
            with db._conn() as conn:
                dark = detect_going_dark(conn, person['id'])
                if dark:
                    going_dark = True

            advisory_count = person.get('advisory_count', 0)

            score_data = calculate_composite_score(
                person_data=person,
                signals=signals,
                idf_data=idf_data,
                going_dark=going_dark,
                advisory_count=advisory_count,
            )

            with db._conn() as conn:
                save_score(conn, person['id'], score_data)
                conn.execute(
                    'UPDATE tracked_people SET composite_score = ?, score_classification = ? WHERE id = ?',
                    (score_data['composite_score'], score_data['classification'], person['id'])
                )
                conn.commit()

            if score_data['classification'] in ('CRITICAL', 'HIGH'):
                log.info("%s: %d (%s)", person['name'], score_data['composite_score'], score_data['classification'])
        except Exception as e:
            log.error("Score error for %s: %s", person['name'], e)

    # Check for classification changes
    with db._conn() as conn:
        changes = get_score_changes(conn, days=1)
    if changes:
        log.info("Score changes today: %d", len(changes))

    db.log_scan('score_update', queries_run=len(people))
    log.info("Score update complete for %d people.", len(people))


def run_enhanced_github_scan():
    """Enhanced GitHub scan with deep repo analysis, npm tracking, and infra detection."""
    log.info("Running enhanced GitHub scan...")

    db = ScoutDatabase(DB_PATH)
    people = db.get_people_with_github()
    github_token = os.environ.get('GITHUB_TOKEN', '')

    if not people:
        log.info("No tracked people with GitHub URLs.")
        db.log_scan('github_scan')
        return

    # Also try to find GitHub for people without URLs
    no_github = [p for p in db.get_active_people() if not p.get('github_url')]
    for person in no_github[:5]:  # Limit to 5 per run to avoid rate limits
        gh_url = search_github_user(person['name'], token=github_token)
        if gh_url:
            db.set_github_url(person['id'], gh_url)
            log.info("Found GitHub for %s: %s", person['name'], gh_url)
            people.append(person)

    log.info("Scanning %d GitHub profiles...", len(people))
    total_signals = 0

    for person in people:
        name = person['name']
        github_url = person.get('github_url')
        if not github_url:
            continue
        username = github_username_from_url(github_url)
        if not username:
            continue

        log.debug("%s (@%s)...", name, username)
        last_scanned = person.get('github_last_scanned')

        # Use enhanced scan
        signals = enhanced_github_scan(username, name, last_scanned, token=github_token)

        for sig in signals:
            db.record_signal(person['id'], sig['type'], sig['tier'], sig['description'], sig.get('url'))
            total_signals += 1
            log.info("[%s] %s", sig['tier'].upper(), sig['description'][:80])

        db.update_github_scanned(person['id'])
        time.sleep(1)

    log.info("Enhanced GitHub scan complete: %d profiles, %d signals.", len(people), total_signals)
    db.log_scan('github_scan', queries_run=len(people), signals_detected=total_signals)

    # Immediate alerts for HIGH signals
    if total_signals > 0:
        recent = db.get_signals_since((datetime.now() - timedelta(minutes=10)).isoformat())
        github_signals = [s for s in recent if s.get('signal_type', '').startswith('github_')]
        high_signals = [s for s in github_signals if s['signal_tier'] == 'high']
        send_github_alerts(SCOUT_RECIPIENTS, high_signals)


# --- Entry Point ---

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("/var/log/founder-scout.log"),
        ],
    )

    if len(sys.argv) < 2:
        log.info(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action == 'scan':
        lock_file = open(LOCK_PATH, 'w')
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.warning("Another instance is running, skipping.")
            return
        try:
            run_daily_scan()
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()

    elif action == 'briefing':
        db = ScoutDatabase(DB_PATH)
        run_weekly_briefing(db, SCOUT_RECIPIENTS)

    elif action == 'watchlist-update':
        run_watchlist_update()

    elif action == 'status':
        db = ScoutDatabase(DB_PATH)
        run_status_v2(db)

    elif action == 'add':
        if len(sys.argv) < 3:
            log.error("Usage: scout.py add <name> [linkedin_url]")
            sys.exit(1)
        name = sys.argv[2]
        linkedin_url = sys.argv[3] if len(sys.argv) > 3 else None
        run_add(name, linkedin_url)

    elif action == 'dismiss':
        if len(sys.argv) < 3:
            log.error("Usage: scout.py dismiss <id>")
            sys.exit(1)
        run_dismiss(sys.argv[2])

    elif action == 'sync-hubspot':
        db = ScoutDatabase(DB_PATH)
        run_sync_hubspot(db, SCOUT_RECIPIENTS)

    elif action == 'approach':
        if len(sys.argv) < 3:
            log.error("Usage: scout.py approach <name>")
            sys.exit(1)
        db = ScoutDatabase(DB_PATH)
        run_approach(db, ' '.join(sys.argv[2:]))

    elif action == 'approach-id':
        if len(sys.argv) < 3:
            log.error("Usage: scout.py approach-id <id>")
            sys.exit(1)
        db = ScoutDatabase(DB_PATH)
        run_approach_by_id(db, sys.argv[2])

    elif action == 'github-scan':
        run_enhanced_github_scan()

    elif action == 'registrar-scan':
        run_registrar_scan()

    elif action == 'retention-update':
        run_retention_update()

    elif action == 'acquisition-scan':
        run_acquisition_scan()

    elif action == 'domain-scan':
        run_domain_scan()

    elif action == 'event-scan':
        run_event_scan()

    elif action == 'score-update':
        run_score_update()

    elif action == 'digest':
        db = ScoutDatabase(DB_PATH)
        run_daily_digest(db, SCOUT_RECIPIENTS)

    else:
        log.error("Unknown action: %s", action)
        log.info(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
