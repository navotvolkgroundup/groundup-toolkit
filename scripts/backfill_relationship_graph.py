#!/usr/bin/env python3
"""
Backfill Relationship Graph from existing data sources.

Populates the relationship graph by scanning:
  1. HubSpot deals — team member <-> associated contacts
  2. Founder Scout DB — tracked people with HubSpot contacts or high signal tiers
  3. Meeting metadata JSON files — pairwise attendee relationships

Usage:
    python3 scripts/backfill_relationship_graph.py [--dry-run] [--json]
"""

import argparse
import glob
import json
import logging
import os
import sqlite3
import sys

# Ensure repo root is importable
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from lib.config import config
from lib.relationship_graph import RelationshipGraph

_DATA_DIR = os.environ.get(
    "TOOLKIT_DATA",
    os.path.join(_REPO_ROOT, "data"),
)

log = logging.getLogger("backfill_relationship_graph")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _owner_id_to_member(owner_id):
    """Resolve a HubSpot owner ID to a team member dict, or None."""
    if not owner_id:
        return None
    owner_id = str(owner_id)
    for m in config.team_members:
        if str(m.get("hubspot_owner_id", "")) == owner_id:
            return m
    return None


def _member_person_dict(member):
    """Convert a config team member to a person dict for the graph."""
    return {
        "name": member["name"],
        "email": member["email"],
        "role": "team",
    }


# ---------------------------------------------------------------------------
# 1. HubSpot Deals
# ---------------------------------------------------------------------------

def backfill_hubspot_deals(graph, dry_run=False):
    """For each HubSpot deal, link deal owner (team) to associated contacts."""
    from lib.hubspot import _session, _url, _HEADERS, MATON_API_KEY

    if not MATON_API_KEY:
        log.warning("MATON_API_KEY not set — skipping HubSpot deals backfill")
        return {"skipped": True, "reason": "no API key"}

    stats = {"deals_scanned": 0, "relationships_created": 0, "errors": 0}

    # Search all deals (paginate via 'after' cursor)
    properties = ["dealname", "hubspot_owner_id", "pipeline", "dealstage"]
    after = None
    all_deals = []

    log.info("Fetching deals from HubSpot...")
    while True:
        body = {
            "filterGroups": [],
            "properties": properties,
            "limit": 100,
        }
        if after:
            body["after"] = after

        try:
            resp = _session.post(
                _url("crm/v3/objects/deals/search"),
                headers=_HEADERS,
                json=body,
                timeout=30,
            )
            if resp.status_code != 200:
                log.error("Deal search failed: %s %s", resp.status_code, resp.text[:200])
                stats["errors"] += 1
                break

            data = resp.json()
            results = data.get("results", [])
            all_deals.extend(results)

            paging = data.get("paging", {}).get("next", {})
            after = paging.get("after")
            if not after or not results:
                break
        except Exception as exc:
            log.error("Deal search error: %s", exc)
            stats["errors"] += 1
            break

    log.info("Found %d deals", len(all_deals))

    for deal in all_deals:
        deal_id = deal["id"]
        props = deal.get("properties", {})
        deal_name = props.get("dealname", f"Deal {deal_id}")
        owner_id = props.get("hubspot_owner_id")

        member = _owner_id_to_member(owner_id)
        if not member:
            # Can't create a team edge without knowing the owner
            continue

        team_person = _member_person_dict(member)

        # Get associated contacts for this deal
        try:
            assoc_resp = _session.get(
                _url(f"crm/v4/objects/deals/{deal_id}/associations/contacts"),
                headers=_HEADERS,
                timeout=10,
            )
            if assoc_resp.status_code != 200:
                continue

            contact_ids = [r["toObjectId"] for r in assoc_resp.json().get("results", [])]
        except Exception as exc:
            log.debug("Association fetch error for deal %s: %s", deal_id, exc)
            stats["errors"] += 1
            continue

        if not contact_ids:
            continue

        # Fetch contact details
        for cid in contact_ids:
            try:
                c_resp = _session.get(
                    _url(f"crm/v3/objects/contacts/{cid}"),
                    headers=_HEADERS,
                    params={"properties": "firstname,lastname,email,hs_linkedin_url,company"},
                    timeout=10,
                )
                if c_resp.status_code != 200:
                    continue

                cp = c_resp.json().get("properties", {})
                contact_name = f"{cp.get('firstname', '')} {cp.get('lastname', '')}".strip()
                if not contact_name:
                    contact_name = cp.get("email", f"Contact {cid}")

                contact_person = {
                    "name": contact_name,
                    "email": cp.get("email"),
                    "linkedin_url": cp.get("hs_linkedin_url"),
                    "company": cp.get("company"),
                    "role": "founder",
                    "hubspot_contact_id": str(cid),
                }

                if dry_run:
                    log.info("[DRY-RUN] deal edge: %s <-> %s (deal: %s)",
                             member["name"], contact_name, deal_name)
                else:
                    graph.add_relationship(
                        person_a=team_person,
                        person_b=contact_person,
                        rel_type="deal",
                        context=deal_name,
                        source="hubspot",
                    )

                stats["relationships_created"] += 1

            except Exception as exc:
                log.debug("Contact fetch error %s: %s", cid, exc)
                stats["errors"] += 1

        stats["deals_scanned"] += 1

    log.info("HubSpot deals: scanned=%d, relationships=%d, errors=%d",
             stats["deals_scanned"], stats["relationships_created"], stats["errors"])
    return stats


# ---------------------------------------------------------------------------
# 2. Founder Scout DB
# ---------------------------------------------------------------------------

def backfill_founder_scout(graph, dry_run=False):
    """Import tracked people from founder-scout.db into the relationship graph."""
    db_path = os.path.join(_DATA_DIR, "founder-scout.db")
    if not os.path.exists(db_path):
        log.warning("Founder Scout DB not found at %s — skipping", db_path)
        return {"skipped": True, "reason": "db not found"}

    stats = {"people_scanned": 0, "hubspot_lead_edges": 0, "high_signal_edges": 0, "errors": 0}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        log.error("Cannot open founder-scout.db: %s", exc)
        return {"skipped": True, "reason": str(exc)}

    try:
        rows = conn.execute(
            """SELECT id, name, linkedin_url, hubspot_contact_id, signal_tier,
                      headline, status
               FROM tracked_people
               WHERE status = 'active' OR status IS NULL"""
        ).fetchall()
    except Exception as exc:
        log.error("Query error on tracked_people: %s", exc)
        conn.close()
        return {"skipped": True, "reason": str(exc)}

    log.info("Founder Scout: %d active tracked people", len(rows))

    # We attribute scout-sourced people to the whole team generically
    # using the first team member as the default relationship anchor.
    # In practice each person may have been scouted by different members,
    # but we don't have that mapping — so we use "founder-scout" source.
    default_team = _member_person_dict(config.team_members[0]) if config.team_members else None

    for row in rows:
        stats["people_scanned"] += 1
        person = {
            "name": row["name"],
            "linkedin_url": row["linkedin_url"],
            "role": "founder",
            "hubspot_contact_id": row["hubspot_contact_id"],
        }

        # If they have a hubspot_contact_id, create a "hubspot_lead" edge
        if row["hubspot_contact_id"] and default_team:
            if dry_run:
                log.info("[DRY-RUN] hubspot_lead: %s <-> %s", default_team["name"], row["name"])
            else:
                graph.add_relationship(
                    person_a=default_team,
                    person_b=person,
                    rel_type="hubspot_lead",
                    context=row["headline"] or "founder-scout tracked",
                    source="founder-scout",
                )
            stats["hubspot_lead_edges"] += 1

        # HIGH / CRITICAL signal tier — always create an edge
        tier = (row["signal_tier"] or "").upper()
        if tier in ("HIGH", "CRITICAL") and default_team:
            if dry_run:
                log.info("[DRY-RUN] scout_signal(%s): %s <-> %s",
                         tier, default_team["name"], row["name"])
            else:
                graph.add_relationship(
                    person_a=default_team,
                    person_b=person,
                    rel_type="scout_signal",
                    context=f"{tier}: {row['headline'] or 'tracked founder'}",
                    source="founder-scout",
                )
            stats["high_signal_edges"] += 1

    conn.close()
    log.info("Founder Scout: scanned=%d, hubspot_lead=%d, high_signal=%d",
             stats["people_scanned"], stats["hubspot_lead_edges"], stats["high_signal_edges"])
    return stats


# ---------------------------------------------------------------------------
# 3. Meeting Metadata (JSON files from meeting-bot)
# ---------------------------------------------------------------------------

def backfill_meeting_metadata(graph, dry_run=False):
    """Create pairwise 'meeting' relationships from meeting-bot metadata JSONs."""
    meta_dir = os.path.join(_DATA_DIR, "meeting-meta")
    if not os.path.isdir(meta_dir):
        log.warning("Meeting metadata directory not found at %s — skipping", meta_dir)
        return {"skipped": True, "reason": "directory not found"}

    stats = {"meetings_scanned": 0, "relationships_created": 0, "errors": 0}

    meta_files = glob.glob(os.path.join(meta_dir, "meeting-meta-*.json"))
    log.info("Found %d meeting metadata files", len(meta_files))

    for fpath in meta_files:
        try:
            with open(fpath) as f:
                meta = json.load(f)
        except Exception as exc:
            log.debug("Cannot read %s: %s", fpath, exc)
            stats["errors"] += 1
            continue

        title = meta.get("title", "Untitled Meeting")
        attendees = meta.get("allAttendees", [])

        if len(attendees) < 2:
            continue

        stats["meetings_scanned"] += 1

        # Build person dicts for each attendee
        people = []
        for att in attendees:
            email = att.get("email", "")
            name = att.get("name", "")
            if not email and not name:
                continue
            role = "team" if email.endswith("@" + config.team_domain) else "external"
            people.append({"name": name or email.split("@")[0], "email": email, "role": role})

        # Create pairwise relationships
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                if dry_run:
                    log.info("[DRY-RUN] meeting: %s <-> %s (%s)",
                             people[i]["name"], people[j]["name"], title)
                else:
                    graph.add_relationship(
                        person_a=people[i],
                        person_b=people[j],
                        rel_type="meeting",
                        context=title,
                        source="meeting-bot",
                    )
                stats["relationships_created"] += 1

    log.info("Meetings: scanned=%d, relationships=%d, errors=%d",
             stats["meetings_scanned"], stats["relationships_created"], stats["errors"])
    return stats


# ---------------------------------------------------------------------------
# 4. Meeting Reminders DB (notified meetings — limited attendee data)
# ---------------------------------------------------------------------------

def backfill_meeting_reminders(graph, dry_run=False):
    """Extract co-meeting signals from meeting-reminders.db.

    The notified_meetings table has (event_id, email, meeting_start).
    Multiple emails sharing the same event_id were in the same meeting.
    """
    db_path = os.path.join(_DATA_DIR, "meeting-reminders.db")
    if not os.path.exists(db_path):
        log.warning("Meeting reminders DB not found at %s — skipping", db_path)
        return {"skipped": True, "reason": "db not found"}

    stats = {"events_scanned": 0, "relationships_created": 0, "errors": 0}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        log.error("Cannot open meeting-reminders.db: %s", exc)
        return {"skipped": True, "reason": str(exc)}

    try:
        # Group team emails by event — these are team members who had the same meeting
        rows = conn.execute(
            """SELECT event_id, GROUP_CONCAT(email) as emails
               FROM notified_meetings
               GROUP BY event_id
               HAVING COUNT(*) >= 2"""
        ).fetchall()
    except Exception as exc:
        log.error("Query error on meeting-reminders: %s", exc)
        conn.close()
        return {"skipped": True, "reason": str(exc)}

    log.info("Meeting reminders: %d events with 2+ notified members", len(rows))

    for row in rows:
        emails = row["emails"].split(",")
        people = []
        for email in emails:
            email = email.strip()
            member = config.get_member_by_email(email)
            if member:
                people.append(_member_person_dict(member))
            else:
                people.append({"name": email.split("@")[0], "email": email, "role": "external"})

        if len(people) < 2:
            continue

        stats["events_scanned"] += 1

        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                if dry_run:
                    log.info("[DRY-RUN] meeting_reminder: %s <-> %s",
                             people[i]["name"], people[j]["name"])
                else:
                    graph.add_relationship(
                        person_a=people[i],
                        person_b=people[j],
                        rel_type="meeting",
                        context="co-notified meeting",
                        source="meeting-reminders",
                    )
                stats["relationships_created"] += 1

    conn.close()
    log.info("Meeting reminders: events=%d, relationships=%d",
             stats["events_scanned"], stats["relationships_created"])
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Backfill relationship graph from HubSpot, founder-scout, and meeting data."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Log what would be done without writing to the graph DB.")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON (machine-readable).")
    args = parser.parse_args()

    level = logging.INFO
    fmt = "%(asctime)s %(name)s %(levelname)s  %(message)s"
    if args.json:
        logging.basicConfig(level=logging.WARNING, format=fmt)
    else:
        logging.basicConfig(level=level, format=fmt)

    graph = RelationshipGraph()
    if args.dry_run:
        log.info("=== DRY RUN — no data will be written ===")

    results = {}

    # 1. HubSpot deals
    log.info("--- Backfilling from HubSpot deals ---")
    results["hubspot_deals"] = backfill_hubspot_deals(graph, dry_run=args.dry_run)

    # 2. Founder Scout
    log.info("--- Backfilling from Founder Scout DB ---")
    results["founder_scout"] = backfill_founder_scout(graph, dry_run=args.dry_run)

    # 3. Meeting metadata (meeting-bot JSON files)
    log.info("--- Backfilling from meeting metadata ---")
    results["meeting_metadata"] = backfill_meeting_metadata(graph, dry_run=args.dry_run)

    # 4. Meeting reminders DB
    log.info("--- Backfilling from meeting reminders DB ---")
    results["meeting_reminders"] = backfill_meeting_reminders(graph, dry_run=args.dry_run)

    # Summary
    if not args.dry_run:
        results["graph_stats"] = graph.get_stats()

    graph.close()

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        log.info("=== Backfill complete ===")
        for source, stats in results.items():
            if source == "graph_stats":
                log.info("Graph totals: %d people, %d relationships",
                         stats["people"], stats["relationships"])
                for rtype, count in stats.get("by_type", {}).items():
                    log.info("  %s: %d", rtype, count)
            else:
                log.info("  %s: %s", source, stats)


if __name__ == "__main__":
    main()
