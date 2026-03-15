#!/usr/bin/env python3
"""
Signal-to-Deal Pipeline — Convert a Founder Scout signal into a HubSpot deal.

Takes a person_id from founder-scout DB and:
  1. Creates/finds HubSpot company from person's company name
  2. Creates HubSpot deal associated with that company
  3. Associates the founder's HubSpot contact (if synced)
  4. Adds relationship graph connections as a deal note
  5. Returns deal URL/ID

Usage:
    python3 scripts/signal_to_deal.py <person_id>
    python3 scripts/signal_to_deal.py <person_id> --json
    python3 scripts/signal_to_deal.py <person_id> --dry-run
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import config

log = logging.getLogger("signal-to-deal")
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")

TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..'))
SCOUT_DB_PATH = os.path.join(TOOLKIT_ROOT, 'data', 'founder-scout.db')

# Pipeline config
MATON_API_KEY = config.maton_api_key
MATON_BASE_URL = 'https://gateway.maton.ai/hubspot'
DEFAULT_PIPELINE = config.hubspot_default_pipeline
DEFAULT_STAGE = config.hubspot_deal_stage
OWNER_IDS = {m['email']: m.get('hubspot_owner_id', '') for m in config.team_members}


def get_person(person_id):
    """Fetch person from founder-scout DB."""
    conn = sqlite3.connect(SCOUT_DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        '''SELECT id, name, linkedin_url, headline, signal_tier, last_signal,
                  hubspot_contact_id, github_url
           FROM tracked_people WHERE id = ?''',
        (person_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def get_person_company(person):
    """Extract company name from person data."""
    headline = person.get('headline') or ''
    # Try to extract company from "Role at Company" pattern
    if ' at ' in headline:
        return headline.split(' at ')[-1].strip()
    if ' @ ' in headline:
        return headline.split(' @ ')[-1].strip()
    # Fall back to last_signal which often mentions company
    signal = person.get('last_signal') or ''
    if 'company' in signal.lower():
        # Look for "Company: Name" or "company name" patterns
        for part in signal.split(','):
            part = part.strip()
            if part.lower().startswith('company'):
                return part.split(':', 1)[-1].strip() if ':' in part else ''
    return ''


def get_thesis_match(person):
    """Check thesis match for this person."""
    try:
        sys.path.insert(0, os.path.join(TOOLKIT_ROOT, 'skills', 'founder-scout'))
        from modules.scoring import apply_thesis_matching

        thesis_path = os.path.join(TOOLKIT_ROOT, 'skills', 'founder-scout', 'thesis.yaml')
        try:
            import yaml
            with open(thesis_path, 'r') as f:
                thesis_config = yaml.safe_load(f)
        except ImportError:
            return None, None

        profile_text = f"{person.get('headline', '')} {person.get('last_signal', '')}"
        _, match = apply_thesis_matching(50, profile_text, thesis_config)
        return match, thesis_config
    except Exception as e:
        log.warning("Thesis matching failed: %s", e)
        return None, None


def get_relationship_context(person):
    """Query relationship graph for this person's connections."""
    try:
        from lib.relationship_graph import RelationshipGraph
        graph = RelationshipGraph()

        identifier = person.get('linkedin_url') or person.get('name')
        connections = graph.get_connections(identifier, limit=5)
        if not connections:
            return ""

        lines = ["Connected via:"]
        for c in connections[:3]:
            p = c.get('person', {})
            name = p.get('name', 'Unknown')
            rel = c.get('rel_type', '')
            strength = c.get('strength', 1)
            lines.append(f"  • {name} ({rel}, strength {strength})")
        return '\n'.join(lines)
    except Exception as e:
        log.warning("Relationship graph query failed: %s", e)
        return ""


def create_deal_for_person(person, company_name, dry_run=False):
    """Create HubSpot deal for this founder signal.

    Returns dict with deal_id, company_id, and context.
    """
    # Import CRM functions
    sys.path.insert(0, os.path.join(TOOLKIT_ROOT, 'scripts'))
    from email_to_deal.crm import (
        find_or_create_company, create_hubspot_deal,
        associate_deal_company, search_hubspot_deal,
    )

    name = person['name']
    deal_name = f"{company_name or name}"

    # Check for existing deal
    existing_deal = search_hubspot_deal(deal_name)
    if existing_deal:
        log.info("Deal already exists: %s (ID: %s)", deal_name, existing_deal)
        return {'deal_id': existing_deal, 'already_existed': True}

    if dry_run:
        return {'deal_id': 'DRY_RUN', 'deal_name': deal_name, 'already_existed': False}

    # Find or create company
    company_id = None
    if company_name:
        company_id = find_or_create_company(company_name)
        log.info("Company: %s -> %s", company_name, company_id)

    # Pick default owner (first team member)
    owner_email = list(OWNER_IDS.keys())[0] if OWNER_IDS else None

    # Create deal
    deal_id = create_hubspot_deal(
        deal_name, company_id, owner_email, DEFAULT_PIPELINE, DEFAULT_STAGE
    )

    if not deal_id:
        log.error("Failed to create deal for %s", name)
        return None

    # Associate founder contact if exists in HubSpot
    hubspot_contact_id = person.get('hubspot_contact_id')
    if hubspot_contact_id and deal_id:
        try:
            import requests
            url = f'{MATON_BASE_URL}/crm/v4/objects/deals/{deal_id}/associations/contacts/{hubspot_contact_id}'
            headers = {'Authorization': f'Bearer {MATON_API_KEY}', 'Content-Type': 'application/json'}
            payload = [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 3}]
            response = requests.put(url, headers=headers, json=payload, timeout=10)
            if response.ok:
                log.info("Associated contact %s with deal %s", hubspot_contact_id, deal_id)
        except Exception as e:
            log.warning("Failed to associate contact: %s", e)

    # Add context note
    relationship_ctx = get_relationship_context(person)
    thesis_match, _ = get_thesis_match(person)
    note_parts = [
        f"Deal created from Founder Scout signal.",
        f"Founder: {name}",
    ]
    if person.get('linkedin_url'):
        note_parts.append(f"LinkedIn: {person['linkedin_url']}")
    if person.get('signal_tier'):
        note_parts.append(f"Signal tier: {person['signal_tier'].upper()}")
    if thesis_match:
        note_parts.append(f"Thesis fit: {thesis_match}")
    if relationship_ctx:
        note_parts.append(f"\n{relationship_ctx}")

    note_text = '\n'.join(note_parts)

    if deal_id and company_id:
        try:
            import requests
            url = f'{MATON_BASE_URL}/crm/v3/objects/notes'
            headers = {'Authorization': f'Bearer {MATON_API_KEY}', 'Content-Type': 'application/json'}
            payload = {
                'properties': {
                    'hs_note_body': note_text,
                    'hs_timestamp': datetime.now().isoformat() + 'Z',
                },
                'associations': [{
                    'to': {'id': deal_id},
                    'types': [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 214}]
                }]
            }
            requests.post(url, headers=headers, json=payload, timeout=10)
            log.info("Added context note to deal")
        except Exception as e:
            log.warning("Failed to add note: %s", e)

    return {
        'deal_id': deal_id,
        'deal_name': deal_name,
        'company_id': company_id,
        'already_existed': False,
        'thesis_match': thesis_match,
        'note': note_text,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: signal_to_deal.py <person_id> [--json] [--dry-run]")
        sys.exit(1)

    person_id = int(sys.argv[1])
    json_output = '--json' in sys.argv
    dry_run = '--dry-run' in sys.argv

    person = get_person(person_id)
    if not person:
        log.error("Person not found: id=%d", person_id)
        sys.exit(1)

    company_name = get_person_company(person)
    log.info("Person: %s | Company: %s | Tier: %s",
             person['name'], company_name or '(unknown)', person.get('signal_tier', '?'))

    result = create_deal_for_person(person, company_name, dry_run=dry_run)

    if json_output:
        print(json.dumps(result or {'error': 'Failed to create deal'}, indent=2))
    elif result:
        if result.get('already_existed'):
            print(f"Deal already exists: {result['deal_id']}")
        elif dry_run:
            print(f"[DRY RUN] Would create deal: {result.get('deal_name', '?')}")
        else:
            print(f"Deal created: {result['deal_id']} ({result.get('deal_name', '')})")
            if result.get('thesis_match'):
                print(f"Thesis fit: {result['thesis_match']}")
    else:
        print("Failed to create deal.")
        sys.exit(1)


if __name__ == "__main__":
    main()
