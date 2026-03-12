"""
Event Tracker — Monitor Israeli tech events for watchlist member appearances.

Uses Brave Search since scraping individual event sites is fragile and
rate-limited. Targets major Israeli startup events: Geektime, ICON, F2/Fusion,
Junction, Google for Startups Israel, Technion entrepreneurship programs.

Event appearances are a useful founding signal: a previously quiet engineer
suddenly appearing on speaker panels often precedes a launch announcement
by 2-4 months.
"""

import re
import json
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Known Israeli tech events
# ---------------------------------------------------------------------------

ISRAELI_TECH_EVENTS = [
    'Geektime',
    'ICON TLV',
    'ICON Israel',
    'F2 - Pair to Founder',
    'Fusion LA',
    'Junction TLV',
    'Google for Startups Israel',
    'Technion Entrepreneurship',
    'Techstars Tel Aviv',
    'Start-Up Nation Central',
    'DLD Tel Aviv',
    'Calcalist Tech',
    'Cybertech',
    'MIXiii Biomed',
    'OurCrowd Summit',
    'Mind the Tech',
    'GoForIsrael',
    'Startup Grind Tel Aviv',
    'SOSA Tel Aviv',
    'The Marker Hi-Tech',
]

# Role keywords that indicate meaningful participation (not just attendance)
SPEAKER_ROLE_PATTERNS = [
    re.compile(r'(?i)\b(?:speaker|panelist|keynote|moderator|presenter|pitch)\b'),
    re.compile(r'(?i)\b(?:judge|mentor|advisor)\b'),
    re.compile(r'(?i)\b(?:demo\s+day|pitch\s+competition|startup\s+battle)\b'),
    re.compile(r'(?i)\b(?:fireside\s+chat|interview|panel)\b'),
    re.compile(r'(?i)\b(?:workshop\s+lead|facilitator)\b'),
]

# Patterns that suggest someone is presenting a NEW venture
NEW_VENTURE_PATTERNS = [
    re.compile(r'(?i)\b(?:unveil|launch|announce|debut|introduce|reveal)\b'),
    re.compile(r'(?i)\b(?:stealth|new\s+venture|new\s+startup|founding|co-?found)\b'),
    re.compile(r'(?i)\b(?:pre-?seed|seed\s+stage|early\s+stage|first\s+time\s+founder)\b'),
    re.compile(r'(?i)\b(?:building\s+something\s+new|left.*to\s+start)\b'),
]


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

def init_event_tables(conn):
    """Create event_signals table."""
    conn.execute('''CREATE TABLE IF NOT EXISTS event_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_name TEXT,
        event_date TEXT,
        event_source TEXT,
        person_name TEXT,
        person_role TEXT,
        matched_person_id INTEGER,
        signal_level TEXT,
        created_at TEXT NOT NULL
    )''')
    conn.commit()


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def _extract_event_date(text):
    """Try to extract a date from event-related text.

    Looks for patterns like 'March 2026', '12/03/2026', '2026-03-12'.
    Returns ISO date string or None.
    """
    # ISO format
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)

    # Month Year
    month_names = {
        'january': '01', 'february': '02', 'march': '03', 'april': '04',
        'may': '05', 'june': '06', 'july': '07', 'august': '08',
        'september': '09', 'october': '10', 'november': '11', 'december': '12',
    }
    m = re.search(r'(?i)\b(' + '|'.join(month_names.keys()) + r')\s+(\d{4})\b', text)
    if m:
        month = month_names[m.group(1).lower()]
        year = m.group(2)
        return f'{year}-{month}-01'

    return None


def _classify_role(text):
    """Determine the person's role at an event from surrounding text.

    Returns tuple of (role_string, is_speaker_bool).
    """
    for pattern in SPEAKER_ROLE_PATTERNS:
        m = pattern.search(text)
        if m:
            return (m.group().strip().lower(), True)

    return ('mentioned', False)


def _assess_signal_level(text, is_speaker):
    """Determine signal level based on event context.

    Returns 'high', 'medium', or 'low'.
    """
    # New venture signals are always high
    for pattern in NEW_VENTURE_PATTERNS:
        if pattern.search(text):
            return 'high'

    # Speaking roles are medium
    if is_speaker:
        return 'medium'

    return 'low'


# ---------------------------------------------------------------------------
# Person-level search
# ---------------------------------------------------------------------------

def search_person_events(person_name, brave_search_fn):
    """Search for a person's appearance at startup events.

    Args:
        person_name: Full name string.
        brave_search_fn: Callable(query) -> list of search result dicts.
            Each result should have 'title', 'url', 'description' keys.

    Returns:
        List of event signal dicts:
            {event_name, event_date, event_source, person_name,
             person_role, signal_level, details}
    """
    if not brave_search_fn or not person_name:
        return []

    signals = []
    now = datetime.now().strftime('%Y-%m-%d')

    # Search for person + event keywords
    queries = [
        f'"{person_name}" speaker startup event Israel',
        f'"{person_name}" panelist conference Tel Aviv',
        f'"{person_name}" demo day pitch Israel',
    ]

    seen_urls = set()

    for query in queries:
        try:
            results = brave_search_fn(query)
        except Exception:
            continue

        if not results:
            continue

        for result in results[:5]:
            url = result.get('url', '')
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = result.get('title', '')
            description = result.get('description', '')
            combined = f'{title} {description}'

            # Verify the person is actually mentioned
            name_parts = person_name.lower().split()
            if not any(part in combined.lower() for part in name_parts if len(part) > 2):
                continue

            # Try to identify which event
            event_name = None
            for known_event in ISRAELI_TECH_EVENTS:
                if known_event.lower() in combined.lower():
                    event_name = known_event
                    break

            if not event_name:
                # Use the title as a fallback if it looks event-like
                event_keywords = re.compile(
                    r'(?i)\b(?:conference|summit|meetup|event|hackathon|demo\s+day|pitch)\b'
                )
                if event_keywords.search(combined):
                    event_name = title[:80]
                else:
                    continue  # Skip if we can't identify an event context

            role, is_speaker = _classify_role(combined)
            signal_level = _assess_signal_level(combined, is_speaker)
            event_date = _extract_event_date(combined)

            signals.append({
                'event_name': event_name,
                'event_date': event_date,
                'event_source': url,
                'person_name': person_name,
                'person_role': role,
                'signal_level': signal_level,
                'details': f'{title[:120]}',
                'created_at': now,
            })

    return signals


# ---------------------------------------------------------------------------
# Upcoming events discovery
# ---------------------------------------------------------------------------

def search_upcoming_events(brave_search_fn):
    """Find upcoming Israeli tech/startup events.

    Useful for proactively checking if watchlist members will appear at
    events we discover.

    Args:
        brave_search_fn: Callable(query) -> list of search result dicts.

    Returns:
        List of dicts: {event_name, event_date, event_source, details}
    """
    if not brave_search_fn:
        return []

    events = []
    seen_urls = set()

    queries = [
        'upcoming startup event Israel 2026',
        'tech conference Tel Aviv 2026',
        'startup demo day Israel upcoming',
        'Israeli tech meetup entrepreneur',
    ]

    for query in queries:
        try:
            results = brave_search_fn(query)
        except Exception:
            continue

        if not results:
            continue

        for result in results[:5]:
            url = result.get('url', '')
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = result.get('title', '')
            description = result.get('description', '')
            combined = f'{title} {description}'

            event_date = _extract_event_date(combined)

            events.append({
                'event_name': title[:100],
                'event_date': event_date,
                'event_source': url,
                'details': description[:200] if description else '',
            })

    return events


# ---------------------------------------------------------------------------
# Full watchlist scan
# ---------------------------------------------------------------------------

def scan_events(conn, watchlist_people, brave_search_fn):
    """Weekly scan: search for event appearances. Returns signals.

    Args:
        conn: SQLite connection.
        watchlist_people: List of dicts with at least {id, name}.
        brave_search_fn: Callable(query) -> list of search results.

    Returns:
        List of new signal dicts that were saved to the database.
    """
    if not brave_search_fn or not watchlist_people:
        return []

    new_signals = []
    now = datetime.now().strftime('%Y-%m-%d')

    for person in watchlist_people:
        person_name = person.get('name', '')
        person_id = person.get('id')

        if not person_name:
            continue

        try:
            signals = search_person_events(person_name, brave_search_fn)
        except Exception:
            continue

        for signal in signals:
            signal['matched_person_id'] = person_id

            # Avoid duplicates: check if we already have this event+person combo
            existing = conn.execute(
                '''SELECT 1 FROM event_signals
                   WHERE event_name = ? AND person_name = ?
                   AND created_at >= ?''',
                (signal.get('event_name'), person_name,
                 (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
            ).fetchone()

            if existing:
                continue

            conn.execute('''
                INSERT INTO event_signals
                    (event_name, event_date, event_source, person_name,
                     person_role, matched_person_id, signal_level, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal.get('event_name'),
                signal.get('event_date'),
                signal.get('event_source'),
                person_name,
                signal.get('person_role'),
                person_id,
                signal.get('signal_level'),
                now,
            ))
            new_signals.append(signal)

    conn.commit()
    return new_signals


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_event_signals(conn, person_id=None, days=30):
    """Retrieve recent event signals, optionally filtered by person.

    Args:
        conn: SQLite connection.
        person_id: Optional person ID filter.
        days: How far back to look (default 30).

    Returns:
        List of dicts with signal data.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    if person_id is not None:
        cursor = conn.execute(
            '''SELECT id, event_name, event_date, event_source, person_name,
                      person_role, matched_person_id, signal_level, created_at
               FROM event_signals
               WHERE matched_person_id = ? AND created_at >= ?
               ORDER BY created_at DESC''',
            (person_id, cutoff)
        )
    else:
        cursor = conn.execute(
            '''SELECT id, event_name, event_date, event_source, person_name,
                      person_role, matched_person_id, signal_level, created_at
               FROM event_signals
               WHERE created_at >= ?
               ORDER BY created_at DESC''',
            (cutoff,)
        )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
