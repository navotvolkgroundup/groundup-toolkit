"""HubSpot CRM sync — push tracked founders to HubSpot as lead contacts."""

import logging
import sqlite3
from datetime import datetime

from lib.hubspot import (
    search_contact, create_contact, update_contact,
    fetch_deals_by_stage,
)

log = logging.getLogger("founder-scout")


def run_sync_hubspot(db, SCOUT_RECIPIENTS):
    """Sync tracked people to HubSpot as contacts (leads)."""
    log.info("Syncing Founder Scout leads to HubSpot...")

    people = db.get_active_people()

    if not people:
        log.info("No active people to sync.")
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
            props = {}
            if person.get('approached'):
                props['hs_lead_status'] = 'ATTEMPTED_TO_CONTACT'
            if props:
                update_contact(hubspot_id, props)
            updated += 1
            log.info("Linked existing: %s -> %s", name, hubspot_id)
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
            log.error("Failed to create contact for %s", name)

    # Auto-detect approached: check if any tracked person matches a HubSpot deal
    auto_approached = _auto_detect_approached(db, people)

    log.info("Sync complete: %d created, %d updated, %d skipped, %d auto-approached", created, updated, skipped, auto_approached)


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
        pipelines = config.hubspot_pipelines
        pipeline_config = pipelines[0] if pipelines else {}
        stages = pipeline_config.get('stages', {})
        for stage_id in stages:
            deals = fetch_deals_by_stage(stage_id, properties=['dealname'])
            for d in deals:
                name = d.get('properties', {}).get('dealname', '')
                if name:
                    all_deal_names.add(name.lower().strip())
    except Exception as e:
        log.error("Auto-detect: failed to fetch deals: %s", e)
        return 0

    if not all_deal_names:
        return 0

    count = 0
    for person in unapproached:
        name = person['name'].lower()
        parts = name.split()
        # Match requires full name in deal name, or both first AND last name present
        # (avoids false positives from common last names like "Cohen", "Lev", etc.)
        matched = False
        for deal_name in all_deal_names:
            # Match by full name (e.g. "yuval lev" in "Yuval Lev - Stealth")
            if name in deal_name:
                matched = True
                break
            # Match if both first AND last name appear in deal name (handles "Lev Labs" + "Yuval")
            if len(parts) >= 2 and all(p in deal_name for p in parts):
                matched = True
                break

        if matched:
            db.mark_approached(person['id'])
            hubspot_id = person.get('hubspot_contact_id')
            if hubspot_id:
                update_contact(hubspot_id, {'hs_lead_status': 'ATTEMPTED_TO_CONTACT'})
            log.info("Auto-approached: %s (matched deal)", person['name'])
            count += 1

    return count


def run_approach(db, name_query):
    """Mark a person as approached (by name search). Updates local DB + HubSpot."""
    import sys
    matches = db.search_person_by_name(name_query)

    if not matches:
        log.warning("No active person found matching '%s'.", name_query)
        log.info("Tip: use 'founder-scout status' to see the full watchlist.")
        sys.exit(1)

    if len(matches) > 1:
        log.warning("Multiple matches for '%s':", name_query)
        for m in matches:
            tier = f"[{m['signal_tier'].upper()}]" if m.get('signal_tier') else "[---]"
            approached = " (approached)" if m.get('approached') else ""
            log.info("id=%d %s %s%s", m['id'], tier, m['name'], approached)
        log.info("Use a more specific name or 'founder-scout approach-id <id>'.")
        return

    person = matches[0]
    person_id = person['id']
    name = person['name']

    # Mark in local DB
    db.mark_approached(person_id)
    log.info("Marked %s as approached.", name)

    # Update HubSpot if contact exists
    hubspot_id = person.get('hubspot_contact_id')
    if hubspot_id:
        update_contact(hubspot_id, {'hs_lead_status': 'ATTEMPTED_TO_CONTACT'})
        log.info("HubSpot contact %s updated: hs_lead_status -> ATTEMPTED_TO_CONTACT", hubspot_id)
    else:
        log.info("No HubSpot contact yet. Run 'founder-scout sync-hubspot' to create it.")


def run_approach_by_id(db, person_id):
    """Mark a person as approached by DB id."""
    import sys
    with db._conn() as conn:
        conn.row_factory = sqlite3.Row
        person = conn.execute(
            'SELECT * FROM tracked_people WHERE id = ?', (int(person_id),)
        ).fetchone()

    if not person:
        log.error("No person found with id=%s", person_id)
        sys.exit(1)

    person = dict(person)
    db.mark_approached(person['id'])
    log.info("Marked %s (id=%s) as approached.", person['name'], person_id)

    hubspot_id = person.get('hubspot_contact_id')
    if hubspot_id:
        update_contact(hubspot_id, {'hs_lead_status': 'ATTEMPTED_TO_CONTACT'})
        log.info("HubSpot contact %s updated: hs_lead_status -> ATTEMPTED_TO_CONTACT", hubspot_id)


def sync_new_leads_to_hubspot(db, profiles):
    """Push newly discovered profiles to HubSpot as leads (called from daily scan)."""
    from lib.hubspot import search_contact, create_contact
    log.info("Syncing %d leads to HubSpot...", len(profiles))
    for p in profiles:
        name = p.get('name', '')
        url = p.get('url', '')
        parts = name.split(None, 1)
        firstname = parts[0] if parts else name
        lastname = parts[1] if len(parts) > 1 else ''

        # Check if already exists
        existing = None
        if url:
            existing = search_contact(linkedin_url=url)
        if not existing:
            existing = search_contact(name=name)

        if existing:
            hubspot_id = existing['id']
            log.info("%s: already in HubSpot (%s)", name, hubspot_id)
        else:
            hubspot_id = create_contact(firstname, lastname, url, {'lifecyclestage': 'lead', 'hs_lead_status': 'NEW'})
            if hubspot_id:
                log.info("%s: created in HubSpot (%s)", name, hubspot_id)
            else:
                log.error("%s: failed to create in HubSpot", name)
                continue

        # Link to tracked person in local DB
        person = db.get_person_by_linkedin(url) if url else None
        person_id = person if isinstance(person, int) else (person['id'] if person and isinstance(person, dict) else None)
        if person_id and hubspot_id:
            db.set_hubspot_contact_id(person_id, str(hubspot_id))
