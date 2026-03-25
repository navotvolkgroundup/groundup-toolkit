#!/usr/bin/env python3
"""
US Founder Scout — Automated discovery pipeline for US tech founders about to start
new companies. Uses LinkedIn and Twitter/X browser signals to identify founders in
stealth mode, between ventures, or showing acquisition exit signals.

JORDAN-ONLY ACCESS — This skill only runs for Jordan Odinsky.

How it works:

  1. DISCOVER (daily scan)
     Rotates through LinkedIn keyword searches targeting deep tech alumni
     (Anduril, Shield AI, Figure AI, etc.) and Ground Up portfolio alumni.
     Uses headless Chromium + Claude to analyze profiles for founding signals.
     Confirmed founders are added to the watchlist and trigger alerts.

  2. TWITTER/X SIGNAL SCAN (daily)
     Monitors tracked founders' Twitter activity for:
     - "stealth", "building something", "day 1" posts
     - "left [company]", "chapter 2", "new chapter" posts
     - Spikes in engagement with other founders/investors
     - Uses Twitter/X search API via browser automation

  3. MONITOR (watchlist update, Mon/Wed/Fri)
     Re-visits tracked founders' LinkedIn profiles to detect:
     - Role changes
     - New ventures or company announcements
     - Stealth mode hints
     - Updated bio/headline changes

  4. LOCAL TRACKING (SQLite)
     All data stored in local SQLite DB — no CRM sync.
     Tracks: name, LinkedIn URL, Twitter handle, signals, approach status.
     Allows manual "approach" tracking for Jordan's outreach.

Commands:
  scan              Daily LinkedIn rotation + signal analysis
  briefing          Weekly summary of HIGH/MEDIUM signals
  watchlist-update  Re-scan tracked founders for changes
  status            Print current watchlist state
  add <name> <url>  Manually add a founder
  dismiss <id>      Remove a founder from tracking
  approach <name>   Mark founder as approached
  approach-id <id>  Mark founder as approached by DB ID

Usage:
  python3 scout.py scan
  python3 scout.py briefing
  python3 scout.py watchlist-update
  python3 scout.py status
  python3 scout.py add "Jake Saper" "https://linkedin.com/in/jakesaper"
  python3 scout.py dismiss 5
  python3 scout.py approach "Jake Saper"
"""

import sys
import os
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import re

# Access control: Jordan only
JORDAN_ONLY = True
ALLOWED_USER = "jordan"

# Add parent paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from lib.structured_log import get_logger
    from lib.config import config
    from lib.claude import call_claude
    from lib.email import send_email
    from lib.whatsapp import send_whatsapp
except ImportError as e:
    print(f"Error: Missing shared library. {e}")
    print("Make sure you're running from the toolkit root or have PYTHONPATH set.")
    sys.exit(1)

# Import local modules
try:
    from modules.linkedin import (
        linkedin_browser_available, linkedin_search, linkedin_profile_lookup,
        extract_profiles_from_search, filter_relevant_profiles,
        analyze_linkedin_profile, extract_github_from_linkedin,
        LINKEDIN_NAV_DELAY
    )
    from modules.twitter import (
        twitter_browser_available, twitter_search, twitter_profile_timeline,
        extract_signal_keywords, analyze_twitter_activity
    )
except ImportError as e:
    print(f"Warning: Could not import local modules: {e}")
    # Graceful degradation - modules will be used if available

log = get_logger("us-founder-scout")

# ============================================================================
# CONFIG & CONSTANTS
# ============================================================================

DATA_DIR = Path.home() / ".openclaw" / "data"
DB_PATH = DATA_DIR / "us-founder-scout.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEEP_TECH_COMPANIES = {
    "Defense": [
        "Anduril", "Shield AI", "Epirus", "Rebellion Defense", "Vannevar Labs",
        "Onebrief", "Sarcos"
    ],
    "Robotics": [
        "Figure AI", "Physical Intelligence", "Apptronik", "Mytra", "Gecko Robotics",
        "Agility Robotics", "Hadrian", "Machina Labs"
    ],
    "Energy": [
        "X-energy", "Koloma", "Commonwealth Fusion", "Antora Energy", "Form Energy",
        "Electric Hydrogen", "Solugen"
    ],
    "Space": [
        "Astranis", "Varda Space", "Hermeus", "Relativity Space", "Albedo",
        "True Anomaly", "Apex Space"
    ],
    "Mobility": [
        "Waabi", "Gatik", "Kodiak Robotics", "Nuro", "Einride", "Plus.ai"
    ],
    "Agriculture": [
        "Plenty", "Monarch Tractor", "Field AI", "AppHarvest"
    ]
}

GROUND_UP_PORTFOLIO = {
    "Fund I": [
        "402", "Accrue Savings", "Array", "BuildOps", "Daily.co", "Dandelion Energy",
        "Disco", "EliseAI", "Flyp", "Glass Imaging", "Jones", "Komodor", "Openlayer",
        "PDQ", "Pipe", "Postmoda", "Tolstoy", "TrueHold", "Tulu", "Upfort", "Younity"
    ],
    "Fund II": [
        "Axo Neurotech", "Baba", "Covenant", "Dialogue", "Dialogica", "Draftboard",
        "FutureLot", "G2", "Harbinger", "Hello Wonder", "HyWatts", "Kela", "Lenkie",
        "Meridian", "Nevona.AI", "Ownli", "Panjaya", "Phase Zero", "Pillar Security",
        "Portless", "PreQl", "Proov.ai", "Real", "Reap", "Refine Intelligence",
        "Ritual", "StarCloud", "TermScout", "ThreeFold", "TripleWhale", "Unit.AI",
        "Weave", "Zealthy", "Zeromark"
    ]
}

# ============================================================================
# ACCESS CONTROL
# ============================================================================

def check_access():
    """Enforce Jordan-only access."""
    if not JORDAN_ONLY:
        return True

    # Check for Jordan in config
    try:
        jordan = config.get_member_by_name("Jordan")
        if not jordan:
            log.error("ACCESS DENIED: Jordan not found in team config")
            print("ERROR: This skill is restricted to Jordan.")
            sys.exit(1)
        return True
    except Exception as e:
        log.error(f"ACCESS DENIED: {e}")
        print("ERROR: Could not verify access permissions.")
        sys.exit(1)

# ============================================================================
# DATABASE SETUP
# ============================================================================

def init_db():
    """Initialize SQLite database for tracking founders."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS founders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            linkedin_url TEXT,
            twitter_handle TEXT,
            signal_tier TEXT DEFAULT 'LOW',
            last_signal TEXT,
            last_scanned TEXT,
            status TEXT DEFAULT 'OPEN',
            source TEXT,
            source_company TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            founder_id INTEGER NOT NULL,
            signal_type TEXT,
            description TEXT,
            tier TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (founder_id) REFERENCES founders(id)
        )
    ''')

    c.execute('''
        CREATE INDEX IF NOT EXISTS idx_status ON founders(status)
    ''')
    c.execute('''
        CREATE INDEX IF NOT EXISTS idx_signal_tier ON founders(signal_tier)
    ''')

    conn.commit()
    conn.close()

def get_db():
    """Get database connection."""
    return sqlite3.connect(str(DB_PATH))

# ============================================================================
# FOUNDER DISCOVERY
# ============================================================================

def analyze_profile_for_signals(name, linkedin_profile_text, twitter_activity=None):
    """Use Claude to analyze a founder's profile for founding signals."""

    prompt = f"""
You are analyzing a potential founder's profile for signals that they're starting a new company.

Profile: {name}
LinkedIn data: {linkedin_profile_text}
{f'Twitter activity: {twitter_activity}' if twitter_activity else ''}

Respond with JSON:
{{
  "is_founder_signal": true/false,
  "signal_tier": "HIGH" or "MEDIUM" or "LOW",
  "reasons": ["reason1", "reason2"],
  "confidence": 0.0-1.0
}}

HIGH = Left role + stealth tweets, co-founding announcement, "day 1" posts
MEDIUM = Open to work, recent exit, exploring opportunities
LOW = Accelerator completion, grants, advisory roles
"""

    try:
        response = call_claude(
            model="claude-haiku-4-5-20251001",
            system="You are an expert at identifying tech founders. Respond only with valid JSON.",
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse JSON from response
        text = response.content[0].text if response.content else ""
        data = json.loads(text)
        return data
    except Exception as e:
        log.error(f"Error analyzing profile for {name}: {e}")
        return {
            "is_founder_signal": False,
            "signal_tier": "LOW",
            "reasons": ["Analysis failed"],
            "confidence": 0.0
        }

def scan_deep_tech_alumni():
    """Search LinkedIn for deep tech company alumni with founding signals."""
    log.info("Starting deep tech alumni scan...")

    if not linkedin_browser_available():
        log.error("LinkedIn browser session not available")
        return []

    results = []

    # Rotate through a few companies each scan
    import random
    companies_to_scan = []
    for category, companies in DEEP_TECH_COMPANIES.items():
        if companies:
            companies_to_scan.append(random.choice(companies))

    for company in companies_to_scan[:3]:  # Limit to 3 per scan
        log.info(f"Scanning deep tech alumni from {company}...")

        # Search LinkedIn for recent ex-employees
        query = f"{company} founder leaving startup new venture"
        search_html = linkedin_search(query)

        if not search_html:
            log.warning(f"Failed to search for {company} alumni")
            continue

        # Extract profile URLs and names
        profiles = extract_profiles_from_search(search_html)
        log.info(f"Found {len(profiles)} potential profiles for {company}")

        # Filter and analyze top profiles
        filtered = filter_relevant_profiles(profiles)

        for profile in filtered[:5]:  # Limit lookups to 5 per company
            try:
                # Get full profile
                profile_text = linkedin_profile_lookup(profile['linkedin_url'])
                if not profile_text:
                    continue

                # Analyze with Claude
                analysis = analyze_linkedin_profile(profile['name'], profile_text)

                if analysis.get('is_founder_signal'):
                    results.append({
                        'name': profile['name'],
                        'linkedin_url': profile['linkedin_url'],
                        'headline': profile.get('headline', ''),
                        'signal_tier': analysis.get('signal_tier', 'LOW'),
                        'reasons': analysis.get('reasons', []),
                        'source': 'deeptech_alumni',
                        'source_company': company,
                        'github_url': extract_github_from_linkedin(profile_text)
                    })

                time.sleep(2)  # Rate limiting
            except Exception as e:
                log.error(f"Error analyzing {profile['name']}: {e}")
                continue

    log.info(f"Deep tech scan found {len(results)} potential founders")
    return results


def scan_gup_alumni():
    """Search for Ground Up portfolio company alumni with founding signals."""
    log.info("Starting Ground Up portfolio alumni scan...")

    if not linkedin_browser_available():
        log.error("LinkedIn browser session not available")
        return []

    results = []

    # Pick a few portfolio companies to scan
    import random
    portfolio_companies = []
    for fund, companies in GROUND_UP_PORTFOLIO.items():
        if companies:
            portfolio_companies.append(random.choice(companies))

    for company in portfolio_companies[:2]:  # Limit to 2 per scan
        log.info(f"Scanning GUP alumni from {company}...")

        query = f"{company} founder startup leaving"
        search_html = linkedin_search(query)

        if not search_html:
            log.warning(f"Failed to search for {company} alumni")
            continue

        profiles = extract_profiles_from_search(search_html)
        log.info(f"Found {len(profiles)} profiles from {company}")

        filtered = filter_relevant_profiles(profiles)

        for profile in filtered[:4]:
            try:
                profile_text = linkedin_profile_lookup(profile['linkedin_url'])
                if not profile_text:
                    continue

                analysis = analyze_linkedin_profile(profile['name'], profile_text)

                if analysis.get('is_founder_signal'):
                    results.append({
                        'name': profile['name'],
                        'linkedin_url': profile['linkedin_url'],
                        'headline': profile.get('headline', ''),
                        'signal_tier': analysis.get('signal_tier', 'LOW'),
                        'reasons': analysis.get('reasons', []),
                        'source': 'gup_alumni',
                        'source_company': company,
                        'github_url': extract_github_from_linkedin(profile_text)
                    })

                time.sleep(2)
            except Exception as e:
                log.error(f"Error analyzing {profile['name']}: {e}")
                continue

    log.info(f"GUP alumni scan found {len(results)} potential founders")
    return results


def scan_twitter_signals():
    """Monitor Twitter/X for founder keywords and tracked people."""
    log.info("Starting Twitter/X signal scan...")

    if not twitter_browser_available():
        log.warning("Twitter browser session not available")
        return []

    signals = []

    # Search for founding keywords
    founding_searches = [
        '"stealth" startup founder',
        '"building something" founder US',
        '"day 1" founder startup',
        'founder "left" startup 2024 2025'
    ]

    for query in founding_searches[:2]:  # Limit searches
        log.info(f"Twitter search: {query}")

        try:
            search_result = twitter_search(query)
            if search_result:
                signals.append({
                    'query': query,
                    'raw_text': search_result
                })

            time.sleep(3)  # Rate limiting
        except Exception as e:
            log.error(f"Twitter search error for '{query}': {e}")
            continue

    log.info(f"Twitter scan found {len(signals)} signal searches")
    return signals

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

def cmd_scan():
    """Run daily LinkedIn + Twitter scan."""
    log.info("Running daily scan...")

    init_db()
    conn = get_db()
    c = conn.cursor()

    all_founders = []
    high_signal_founders = []

    try:
        # Scan deep tech alumni
        results = scan_deep_tech_alumni()
        log.info(f"Found {len(results)} potential founders from deep tech alumni")
        all_founders.extend(results)

        # Scan Ground Up alumni
        gup_results = scan_gup_alumni()
        log.info(f"Found {len(gup_results)} potential founders from GUP alumni")
        all_founders.extend(gup_results)

        # Scan Twitter
        twitter_results = scan_twitter_signals()
        log.info(f"Found {len(twitter_results)} signal searches from Twitter/X")

        # Process and store results
        for founder in all_founders:
            try:
                # Check if already in database
                c.execute('SELECT id, status FROM founders WHERE linkedin_url = ?',
                         (founder['linkedin_url'],))
                existing = c.fetchone()

                if existing:
                    # Update existing
                    c.execute('''
                        UPDATE founders SET
                        signal_tier = ?, source = ?, source_company = ?,
                        last_scanned = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                        WHERE linkedin_url = ?
                    ''', (founder['signal_tier'], founder['source'],
                          founder.get('source_company', ''), founder['linkedin_url']))
                else:
                    # Insert new
                    c.execute('''
                        INSERT INTO founders
                        (name, linkedin_url, signal_tier, source, source_company, status, last_scanned)
                        VALUES (?, ?, ?, ?, ?, 'OPEN', CURRENT_TIMESTAMP)
                    ''', (founder['name'], founder['linkedin_url'],
                          founder['signal_tier'], founder['source'],
                          founder.get('source_company', '')))

                # Store signal
                founder_id = existing[0] if existing else c.lastrowid
                c.execute('''
                    INSERT INTO signals
                    (founder_id, signal_type, description, tier)
                    VALUES (?, ?, ?, ?)
                ''', (founder_id, 'linkedin_profile',
                      ', '.join(founder.get('reasons', [])),
                      founder['signal_tier']))

                if founder['signal_tier'] in ('HIGH', 'MEDIUM'):
                    high_signal_founders.append(founder)

            except Exception as e:
                log.error(f"Error storing founder {founder.get('name')}: {e}")

        conn.commit()

        # Send alerts for HIGH signal founders
        if high_signal_founders:
            alert_message = f"🚀 US Founder Scout: {len(high_signal_founders)} potential founders detected\n\n"
            for founder in high_signal_founders:
                alert_message += f"• {founder['name']} [{founder['signal_tier']}]\n"
                alert_message += f"  {founder.get('source_company', 'Unknown')}\n"

            try:
                jordan = config.get_member_by_name("Jordan")
                jordan_phone = jordan.get("phone") if jordan else None
                if jordan_phone:
                    send_whatsapp(jordan_phone, alert_message)
                else:
                    log.warning("Jordan's phone not found in config")
            except Exception as e:
                log.warning(f"Could not send WhatsApp alert: {e}")

        print(f"✅ Scan complete: {len(all_founders)} founders discovered ({len(high_signal_founders)} with HIGH/MEDIUM signals)")
        log.info(f"Daily scan complete: {len(all_founders)} founders, {len(high_signal_founders)} high signals")

    except Exception as e:
        log.error(f"Scan failed: {e}", exc_info=True)
        print(f"❌ Scan failed: {e}")
    finally:
        conn.close()

def cmd_briefing():
    """Generate weekly briefing of HIGH/MEDIUM signals."""
    log.info("Generating weekly briefing...")

    init_db()
    conn = get_db()
    c = conn.cursor()

    # Get signals from last 7 days
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()

    c.execute('''
        SELECT f.name, s.description, s.tier, s.detected_at
        FROM signals s
        JOIN founders f ON s.founder_id = f.id
        WHERE s.detected_at > ? AND s.tier IN ('HIGH', 'MEDIUM')
        ORDER BY s.tier DESC, s.detected_at DESC
    ''', (week_ago,))

    signals = c.fetchall()
    conn.close()

    if not signals:
        print("No HIGH or MEDIUM signals detected this week.")
        return

    print("\n=== US Founder Scout Weekly Briefing ===\n")

    high_count = sum(1 for s in signals if s[2] == 'HIGH')
    medium_count = sum(1 for s in signals if s[2] == 'MEDIUM')

    print(f"Summary: {high_count} HIGH signals, {medium_count} MEDIUM signals\n")

    for name, desc, tier, detected_at in signals:
        print(f"[{tier}] {name}")
        print(f"    {desc}")
        print(f"    Detected: {detected_at}\n")

def cmd_watchlist_update():
    """Re-scan tracked founders for signal changes."""
    log.info("Updating watchlist...")

    if not linkedin_browser_available():
        log.error("LinkedIn browser not available. Cannot run watchlist update.")
        print("ERROR: LinkedIn browser not available.")
        return

    init_db()
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT id, name, linkedin_url FROM founders WHERE status = "OPEN"')
    founders = c.fetchall()

    log.info(f"Re-scanning {len(founders)} tracked founders")
    print(f"Updating {len(founders)} founders on watchlist...")

    updated = 0
    for founder_id, name, linkedin_url in founders:
        if not linkedin_url:
            continue
        try:
            profile_text = linkedin_profile_lookup(linkedin_url)
            if not profile_text:
                log.warning(f"Could not fetch profile for {name}")
                continue

            analysis = analyze_profile_for_signals(name, profile_text)

            new_tier = analysis.get('signal_tier', 'LOW')
            reasons = ', '.join(analysis.get('reasons', []))

            c.execute('''
                UPDATE founders SET
                signal_tier = ?, last_signal = ?, last_scanned = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_tier, reasons, founder_id))

            if analysis.get('is_founder_signal'):
                c.execute('''
                    INSERT INTO signals (founder_id, signal_type, description, tier)
                    VALUES (?, 'watchlist_rescan', ?, ?)
                ''', (founder_id, reasons, new_tier))

            updated += 1
            log.info(f"Updated {name}: {new_tier}")
            time.sleep(2)
        except Exception as e:
            log.error(f"Error re-scanning {name}: {e}")

    conn.commit()
    conn.close()
    print(f"Updated {updated}/{len(founders)} founders")

def cmd_status():
    """Print current watchlist state."""
    init_db()
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT id, name, signal_tier, status FROM founders ORDER BY signal_tier DESC')
    founders = c.fetchall()
    conn.close()

    print("\n=== US Founder Scout Watchlist ===\n")

    if not founders:
        print("No founders tracked yet.")
        return

    for fid, name, tier, status in founders:
        status_str = "✓" if status == "APPROACHED" else "○"
        print(f"{status_str} [{tier:6s}] {name}")

    print(f"\nTotal: {len(founders)} founders")

def cmd_add(name, linkedin_url, twitter_handle=None):
    """Manually add a founder to tracking."""
    init_db()
    conn = get_db()
    c = conn.cursor()

    try:
        c.execute('''
            INSERT INTO founders (name, linkedin_url, twitter_handle, source, status)
            VALUES (?, ?, ?, 'manual', 'OPEN')
        ''', (name, linkedin_url, twitter_handle))

        conn.commit()
        founder_id = c.lastrowid
        conn.close()

        print(f"Added: {name} (ID: {founder_id})")
        log.info(f"Manually added founder: {name}")
    except Exception as e:
        log.error(f"Error adding founder: {e}")
        print(f"Error: {e}")

def cmd_dismiss(founder_id):
    """Remove a founder from tracking."""
    init_db()
    conn = get_db()
    c = conn.cursor()

    try:
        c.execute('SELECT name FROM founders WHERE id = ?', (founder_id,))
        result = c.fetchone()

        if not result:
            print(f"Founder ID {founder_id} not found.")
            return

        name = result[0]
        c.execute('DELETE FROM founders WHERE id = ?', (founder_id,))
        c.execute('DELETE FROM signals WHERE founder_id = ?', (founder_id,))

        conn.commit()
        conn.close()

        print(f"Dismissed: {name}")
        log.info(f"Dismissed founder: {name} (ID: {founder_id})")
    except Exception as e:
        log.error(f"Error dismissing founder: {e}")
        print(f"Error: {e}")

def cmd_approach(name):
    """Mark a founder as approached (by name)."""
    init_db()
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT id, name FROM founders WHERE name LIKE ?', (f"%{name}%",))
    results = c.fetchall()

    if not results:
        print(f"Founder '{name}' not found in watchlist.")
        conn.close()
        return

    if len(results) > 1:
        print(f"Multiple matches for '{name}':")
        for fid, fname in results:
            print(f"  {fid}: {fname}")
        print("Please use 'approach-id <id>' to specify.")
        conn.close()
        return

    founder_id = results[0][0]

    c.execute(
        'UPDATE founders SET status = "APPROACHED", updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (founder_id,)
    )
    conn.commit()
    conn.close()

    print(f"Marked as approached: {results[0][1]}")
    log.info(f"Marked founder as approached: {results[0][1]}")

def cmd_approach_id(founder_id):
    """Mark a founder as approached (by ID)."""
    init_db()
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT name FROM founders WHERE id = ?', (founder_id,))
    result = c.fetchone()

    if not result:
        print(f"Founder ID {founder_id} not found.")
        conn.close()
        return

    name = result[0]
    c.execute(
        'UPDATE founders SET status = "APPROACHED", updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (founder_id,)
    )
    conn.commit()
    conn.close()

    print(f"Marked as approached: {name}")
    log.info(f"Marked founder as approached: {name} (ID: {founder_id})")

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point."""
    # Access control first
    check_access()

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    try:
        if command == "scan":
            cmd_scan()
        elif command == "briefing":
            cmd_briefing()
        elif command == "watchlist-update":
            cmd_watchlist_update()
        elif command == "status":
            cmd_status()
        elif command == "add":
            if len(sys.argv) < 4:
                print("Usage: us-founder-scout add <name> <linkedin_url> [--twitter @handle]")
                sys.exit(1)
            name = sys.argv[2]
            url = sys.argv[3]
            twitter = None
            if len(sys.argv) > 5 and sys.argv[4] == "--twitter":
                twitter = sys.argv[5]
            cmd_add(name, url, twitter)
        elif command == "dismiss":
            if len(sys.argv) < 3:
                print("Usage: us-founder-scout dismiss <id>")
                sys.exit(1)
            cmd_dismiss(int(sys.argv[2]))
        elif command == "approach":
            if len(sys.argv) < 3:
                print("Usage: us-founder-scout approach <name>")
                sys.exit(1)
            name = " ".join(sys.argv[2:])
            cmd_approach(name)
        elif command == "approach-id":
            if len(sys.argv) < 3:
                print("Usage: us-founder-scout approach-id <id>")
                sys.exit(1)
            cmd_approach_id(int(sys.argv[2]))
        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        log.error(f"Error in {command}: {e}", exc_info=True)
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
