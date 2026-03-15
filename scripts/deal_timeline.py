#!/usr/bin/env python3
"""
Deal Activity Timeline — unified view of all touchpoints with a company.

Queries HubSpot notes, deal stage info, founder-scout signals, and Gmail threads
to build a chronological timeline for a given company or deal.

Usage:
    python3 scripts/deal_timeline.py --company "Acme Corp"
    python3 scripts/deal_timeline.py --deal-id 12345678
"""

import os
import sys
import json
import argparse
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import config
from lib.hubspot import (
    search_company, get_deals_for_company, get_company_for_deal,
    get_latest_note, _session, _url, _HEADERS,
)
from lib.gws import gws_gmail_search


SCOUT_DB = os.path.join(
    os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..')),
    'data', 'founder-scout.db'
)


def _get_hubspot_notes(company_id, limit=10):
    """Fetch recent notes associated with a company."""
    events = []
    try:
        resp = _session.get(
            _url(f"crm/v3/objects/companies/{company_id}/associations/notes"),
            headers=_HEADERS,
            params={"limit": limit},
            timeout=10,
        )
        if resp.status_code != 200:
            return events

        note_ids = [r["id"] for r in resp.json().get("results", [])]
        for nid in note_ids[:limit]:
            nr = _session.get(
                _url(f"crm/v3/objects/notes/{nid}"),
                headers=_HEADERS,
                params={"properties": "hs_note_body,hs_timestamp,hs_createdate"},
                timeout=10,
            )
            if nr.status_code == 200:
                props = nr.json().get("properties", {})
                body = props.get("hs_note_body", "")
                ts = props.get("hs_timestamp") or props.get("hs_createdate") or ""
                # Truncate body for timeline display
                summary = body[:300] + "..." if len(body) > 300 else body
                # Strip HTML tags
                import re
                summary = re.sub(r'<[^>]+>', '', summary).strip()
                events.append({
                    "type": "note",
                    "date": _parse_hs_timestamp(ts),
                    "summary": summary,
                    "source": "HubSpot",
                })
    except Exception as e:
        print(f"  Timeline notes error: {e}", file=sys.stderr)
    return events


def _get_deal_info(company_id):
    """Fetch deals associated with a company and their creation dates."""
    events = []
    try:
        deals = get_deals_for_company(company_id, limit=5)
        for deal in deals:
            props = deal.get("properties", {})
            name = props.get("dealname", "Unknown deal")
            stage = props.get("dealstage", "")
            created = props.get("createdate", "")
            events.append({
                "type": "deal_created",
                "date": _parse_hs_timestamp(created),
                "summary": f"Deal created: {name} (stage: {stage})",
                "source": "HubSpot",
            })
    except Exception as e:
        print(f"  Timeline deals error: {e}", file=sys.stderr)
    return events


def _get_scout_signals(company_name):
    """Fetch founder-scout signals matching a company name."""
    events = []
    if not os.path.exists(SCOUT_DB):
        return events
    try:
        conn = sqlite3.connect(SCOUT_DB)
        # Search tracked_people by name similarity and their signals
        rows = conn.execute('''
            SELECT tp.name, sh.signal_type, sh.description, sh.detected_at
            FROM signal_history sh
            JOIN tracked_people tp ON tp.id = sh.person_id
            WHERE LOWER(tp.name) LIKE ? OR LOWER(sh.description) LIKE ?
            ORDER BY sh.detected_at DESC
            LIMIT 10
        ''', (f'%{company_name.lower()}%', f'%{company_name.lower()}%')).fetchall()

        for name, sig_type, description, detected_at in rows:
            events.append({
                "type": "signal",
                "date": detected_at,
                "summary": f"[{sig_type}] {name}: {description[:200]}",
                "source": "Founder Scout",
            })
        conn.close()
    except Exception as e:
        print(f"  Timeline scout error: {e}", file=sys.stderr)
    return events


def _get_gmail_threads(company_name, days=90):
    """Search Gmail for recent threads mentioning the company."""
    events = []
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
        query = f'"{company_name}" after:{cutoff}'
        results = gws_gmail_search(query, max_results=10)
        if not results:
            return events

        threads = results.get("threads", [])
        for thread in threads[:10]:
            snippet = thread.get("snippet", "")
            # Thread ID can be used for reference but we just need the summary
            events.append({
                "type": "email",
                "date": _extract_thread_date(thread),
                "summary": snippet[:200],
                "source": "Gmail",
            })
    except Exception as e:
        print(f"  Timeline Gmail error: {e}", file=sys.stderr)
    return events


def _parse_hs_timestamp(ts):
    """Parse HubSpot timestamp (epoch ms or ISO) to ISO string."""
    if not ts:
        return datetime.now().isoformat()
    try:
        # Try epoch milliseconds
        if ts.isdigit():
            return datetime.fromtimestamp(int(ts) / 1000).isoformat()
        # Already ISO-ish
        return ts
    except Exception:
        return ts


def _extract_thread_date(thread):
    """Extract a date from a Gmail thread dict."""
    # historyId isn't a date — use internalDate if available
    internal = thread.get("internalDate")
    if internal:
        try:
            return datetime.fromtimestamp(int(internal) / 1000).isoformat()
        except Exception:
            pass
    return datetime.now().isoformat()


def build_timeline(company_name=None, deal_id=None):
    """Build a unified timeline for a company.

    Args:
        company_name: Company name to search for.
        deal_id: HubSpot deal ID (will resolve company from it).

    Returns:
        List of timeline events sorted by date (newest first).
    """
    company_id = None

    if deal_id:
        company = get_company_for_deal(deal_id)
        if company:
            company_id = company.get("id")
            company_name = company.get("properties", {}).get("name", company_name or "")
    elif company_name:
        company = search_company(name=company_name)
        if company:
            company_id = company.get("id")

    events = []

    # HubSpot notes
    if company_id:
        events.extend(_get_hubspot_notes(company_id))
        events.extend(_get_deal_info(company_id))

    # Founder Scout signals
    if company_name:
        events.extend(_get_scout_signals(company_name))

    # Gmail threads
    if company_name:
        events.extend(_get_gmail_threads(company_name))

    # Sort by date descending
    events.sort(key=lambda e: e.get("date", ""), reverse=True)

    return {
        "company": company_name or "",
        "companyId": company_id,
        "events": events[:30],  # Cap at 30 events
    }


def main():
    parser = argparse.ArgumentParser(description="Deal Activity Timeline")
    parser.add_argument("--company", help="Company name")
    parser.add_argument("--deal-id", help="HubSpot deal ID")
    args = parser.parse_args()

    if not args.company and not args.deal_id:
        parser.error("Must provide --company or --deal-id")

    result = build_timeline(company_name=args.company, deal_id=args.deal_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
