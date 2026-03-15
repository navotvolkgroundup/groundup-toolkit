#!/usr/bin/env python3
"""
Thesis Market Scanner — Daily intelligence digest for investment thesis areas.

Loads thesis areas from founder-scout/thesis.yaml, searches for recent funding
news matching each area, deduplicates against seen results, and sends a WhatsApp
digest grouped by thesis area.

Usage:
    python3 scripts/thesis_scanner.py          # run scan + send digest
    python3 scripts/thesis_scanner.py --dry-run # preview without sending
    python3 scripts/thesis_scanner.py --json    # output JSON only

Cron: daily at 8am.
"""

import os
import sys
import json
import hashlib
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.brave import brave_search
from lib.atomic_write import atomic_json_write
from lib.config import config
from lib.whatsapp import send_whatsapp

log = logging.getLogger("thesis-scanner")
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")

TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..'))
THESIS_PATH = os.path.join(TOOLKIT_ROOT, 'skills', 'founder-scout', 'thesis.yaml')
SEEN_PATH = os.path.join(TOOLKIT_ROOT, 'data', 'thesis-news-seen.json')
SCOUT_DB_PATH = os.path.join(TOOLKIT_ROOT, 'data', 'founder-scout.db')


def load_thesis():
    """Load thesis config from YAML."""
    try:
        import yaml
    except ImportError:
        # Fallback: parse simple YAML manually if PyYAML not available
        return _parse_thesis_fallback()

    with open(THESIS_PATH, 'r') as f:
        return yaml.safe_load(f)


def _parse_thesis_fallback():
    """Minimal YAML parser for thesis.yaml structure."""
    import re
    with open(THESIS_PATH, 'r') as f:
        content = f.read()

    areas = []
    current_area = None

    for line in content.split('\n'):
        name_match = re.match(r'\s+- name:\s*"(.+)"', line)
        if name_match:
            current_area = {'name': name_match.group(1), 'keywords': []}
            areas.append(current_area)
            continue

        kw_match = re.match(r'\s+- "(.+)"', line)
        if kw_match and current_area is not None:
            current_area['keywords'].append(kw_match.group(1))

        boost_match = re.match(r'\s+weight_boost:\s*([\d.]+)', line)
        if boost_match and current_area is not None:
            current_area['weight_boost'] = float(boost_match.group(1))

    return {'thesis_areas': areas}


def load_seen():
    """Load set of previously seen URL hashes."""
    try:
        with open(SEEN_PATH, 'r') as f:
            data = json.load(f)
            return set(data.get('seen', []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen_set):
    """Persist seen URL hashes."""
    atomic_json_write(SEEN_PATH, {'seen': list(seen_set), 'updated': datetime.now().isoformat()})


def url_hash(url):
    """Create a short hash for dedup."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def scan_thesis_area(area, seen):
    """Search for recent funding news matching a thesis area.

    Returns list of new results (not in seen set).
    """
    name = area.get('name', '')
    keywords = area.get('keywords', [])

    if len(keywords) < 2:
        return []

    # Build search query: pick top keywords + funding context
    core_keywords = keywords[:3]
    query = f'"{core_keywords[0]}" {" OR ".join(core_keywords[1:])} startup funding seed 2026'

    log.info("Searching: %s -> %s", name, query)
    results = brave_search(query, count=8)

    new_results = []
    for r in results:
        h = url_hash(r['url'])
        if h not in seen:
            seen.add(h)
            r['thesis_area'] = name
            new_results.append(r)

    return new_results


def cross_reference_scout(results):
    """Check if any results mention tracked Founder Scout people.

    Returns results with 'scout_match' field added where applicable.
    """
    try:
        import sqlite3
        if not os.path.exists(SCOUT_DB_PATH):
            return results

        conn = sqlite3.connect(SCOUT_DB_PATH)
        rows = conn.execute(
            "SELECT id, name, linkedin_url FROM tracked_people WHERE status = 'active'"
        ).fetchall()
        conn.close()

        if not rows:
            return results

        people = {r[1].lower(): {'id': r[0], 'name': r[1], 'linkedin_url': r[2]} for r in rows}

        for r in results:
            text = f"{r.get('title', '')} {r.get('description', '')}".lower()
            for name_lower, person in people.items():
                if name_lower in text:
                    r['scout_match'] = person
                    break

    except Exception as e:
        log.warning("Scout cross-reference failed: %s", e)

    return results


def format_digest(results_by_area):
    """Format WhatsApp digest message."""
    date_str = datetime.now().strftime('%b %d')
    total = sum(len(v) for v in results_by_area.values())

    if total == 0:
        return f"Thesis Scanner ({date_str})\n\nNo new market signals today."

    lines = [f"Thesis Scanner ({date_str})", f"{total} new items", ""]

    for area_name, results in results_by_area.items():
        if not results:
            continue
        lines.append(f"*{area_name}* ({len(results)})")
        for r in results[:4]:  # Cap per area for WhatsApp readability
            title = r.get('title', '')[:60]
            entry = f"  • {title}"
            if r.get('scout_match'):
                entry += f" 👀 {r['scout_match']['name']}"
            lines.append(entry)
        if len(results) > 4:
            lines.append(f"  + {len(results) - 4} more")
        lines.append("")

    return '\n'.join(lines)


def main():
    dry_run = '--dry-run' in sys.argv
    json_output = '--json' in sys.argv

    # Load thesis config
    thesis = load_thesis()
    areas = thesis.get('thesis_areas', [])
    if not areas:
        log.error("No thesis areas found in %s", THESIS_PATH)
        sys.exit(1)

    seen = load_seen()
    initial_seen_count = len(seen)

    # Scan each thesis area
    results_by_area = {}
    all_results = []
    for area in areas:
        new_results = scan_thesis_area(area, seen)
        area_name = area.get('name', 'Unknown')
        results_by_area[area_name] = new_results
        all_results.extend(new_results)

    # Cross-reference with Founder Scout
    all_results = cross_reference_scout(all_results)
    # Update results_by_area with scout matches
    for area_name in results_by_area:
        for r in results_by_area[area_name]:
            matching = [ar for ar in all_results if ar.get('url') == r.get('url')]
            if matching and matching[0].get('scout_match'):
                r['scout_match'] = matching[0]['scout_match']

    total_new = len(all_results)
    log.info("Found %d new items across %d thesis areas", total_new, len(areas))

    if json_output:
        output = {
            'date': datetime.now().isoformat(),
            'total_new': total_new,
            'areas': {name: results for name, results in results_by_area.items()},
        }
        print(json.dumps(output, indent=2))
        if not dry_run:
            save_seen(seen)
        return

    # Format and send digest
    digest = format_digest(results_by_area)

    if dry_run:
        print(digest)
        print(f"\n--- {total_new} new items, {len(seen) - initial_seen_count} newly seen ---")
        return

    # Save seen hashes
    save_seen(seen)

    if total_new == 0:
        log.info("No new items — skipping notification.")
        return

    # Send to team via WhatsApp
    team_phones = config.team_phones
    for phone in team_phones:
        send_whatsapp(phone, digest)
        log.info("Sent digest to %s", phone)

    log.info("Thesis scanner complete: %d new items sent", total_new)


if __name__ == "__main__":
    main()
