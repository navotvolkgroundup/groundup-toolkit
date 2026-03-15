"""
Cluster Departure Detection — Flags when 2+ tracked people leave the same company
within a short time window.

When multiple senior people leave the same company around the same time, it's a
strong signal that something is happening — often a group starting a new venture
together. This module scans recent departure signals, extracts company names,
and groups them to detect clusters.
"""

import re
import logging
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Maximum days apart for departures to be considered a "cluster"
CLUSTER_WINDOW_DAYS = 90


def extract_company_from_description(description):
    """Extract a company name from a departure signal description.

    Handles patterns like:
        "Left Google as VP Engineering"
        "Departed from Meta"
        "Changed role — no longer at Amazon"
        "Recently left role at CyberArk"

    Returns:
        Company name string or None.
    """
    if not description:
        return None

    patterns = [
        r'(?:left|departed|leaving)\s+(?:from\s+)?(.+?)(?:\s+as\s+|\s+after\s+|\s*$)',
        r'no longer at\s+(.+?)(?:\s*$|\s*[,.])',
        r'left role at\s+(.+?)(?:\s*$|\s*[,.])',
        r'left\s+(.+?)(?:\s+to\s+|\s*$)',
    ]

    desc_lower = description.lower()
    for pattern in patterns:
        m = re.search(pattern, desc_lower, re.IGNORECASE)
        if m:
            company = m.group(1).strip().strip('.,;:"\' ')
            # Filter out noise
            if company and len(company) > 1 and len(company) < 60:
                # Skip if it looks like a role description rather than company
                role_words = {'their', 'role', 'position', 'job', 'the', 'a', 'an'}
                if company.split()[0] not in role_words:
                    return company.title()

    return None


def detect_cluster_departures(conn, days=90):
    """Scan recent departure signals for cluster patterns.

    Args:
        conn: SQLite connection with signal_history and tracked_people tables.
        days: How far back to look (default 90).

    Returns:
        List of cluster signal dicts:
        [{
            signal_type: 'cluster_departure',
            tier: 'high',
            company: str,
            people: [{'name': str, 'person_id': int, 'date': str}],
            description: str,
        }]
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # Get recent departure signals
    rows = conn.execute('''
        SELECT sh.person_id, tp.name, sh.description, sh.detected_at
        FROM signal_history sh
        JOIN tracked_people tp ON tp.id = sh.person_id
        WHERE sh.signal_type IN ('left_company', 'departed', 'role_change')
          AND sh.detected_at >= ?
        ORDER BY sh.detected_at DESC
    ''', (cutoff,)).fetchall()

    if not rows:
        return []

    # Group by extracted company name
    company_departures = defaultdict(list)
    for person_id, name, description, detected_at in rows:
        company = extract_company_from_description(description)
        if company:
            company_departures[company.lower()].append({
                'name': name,
                'person_id': person_id,
                'date': detected_at,
                'company_display': company,
            })

    # Find clusters (2+ people from same company)
    clusters = []
    for company_key, people in company_departures.items():
        if len(people) < 2:
            continue

        # Use the display name from first entry
        company_display = people[0]['company_display']

        names = [p['name'] for p in people]
        description = (
            f"{len(people)} tracked people recently left {company_display}: "
            f"{', '.join(names)}"
        )

        clusters.append({
            'signal_type': 'cluster_departure',
            'tier': 'high',
            'company': company_display,
            'people': people,
            'description': description,
        })

        logger.info("Cluster departure detected: %s (%d people)", company_display, len(people))

    return clusters
