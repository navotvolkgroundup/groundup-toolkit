"""
Competitive Intelligence — Track which Israeli VCs are engaging with watchlist founders.

Monitors VC engagement signals via Brave Search and LinkedIn profile analysis.
Knowing which VCs are circling a founder helps GroundUp time its outreach:
if Pitango or Aleph are already in conversations, the window is closing.

Data sources:
- Brave Search: news mentions, VC blog posts, podcast appearances
- LinkedIn profile text: advisory roles, recommendations from VC partners
- Event co-appearances: founder + VC at the same event
"""

import re
import json
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Israeli VC firms to track
# ---------------------------------------------------------------------------

VC_FIRMS = [
    {'name': 'Pitango', 'aliases': ['Pitango Venture Capital', 'Pitango VC']},
    {'name': 'TLV Partners', 'aliases': ['TLV Partners']},
    {'name': 'Aleph', 'aliases': ['Aleph VC', 'Aleph Venture Capital']},
    {'name': 'Entree Capital', 'aliases': ['Entree Capital', 'Entrée Capital']},
    {'name': 'Vertex Ventures', 'aliases': ['Vertex Ventures Israel', 'Vertex IL']},
    {'name': 'Team8', 'aliases': ['Team8 Capital', 'Team 8']},
    {'name': 'Cyberstarts', 'aliases': ['Cyberstarts VC']},
    {'name': 'Grove Ventures', 'aliases': ['Grove Ventures']},
    {'name': 'Viola Ventures', 'aliases': ['Viola Ventures', 'Viola Group', 'Viola Credit']},
    {'name': 'NFX', 'aliases': ['NFX Israel', 'NFX Capital']},
    {'name': 'YL Ventures', 'aliases': ['YL Ventures']},
    {'name': 'lool Ventures', 'aliases': ['lool ventures', 'lool vc']},
    {'name': 'Bessemer', 'aliases': ['Bessemer Venture Partners', 'Bessemer Israel', 'BVP Israel']},
    {'name': 'Insight Partners', 'aliases': ['Insight Partners Israel', 'Insight Partners']},
    {'name': 'State of Mind Ventures', 'aliases': ['State of Mind', 'SoMV']},
    {'name': 'MoreVC', 'aliases': ['MoreVC', 'More Venture Capital']},
    {'name': 'Cardumen Capital', 'aliases': ['Cardumen Capital']},
    {'name': 'Amiti Ventures', 'aliases': ['Amiti Ventures']},
    {'name': 'iAngels', 'aliases': ['iAngels']},
    {'name': 'OurCrowd', 'aliases': ['OurCrowd']},
    {'name': 'Glilot Capital', 'aliases': ['Glilot Capital Partners', 'Glilot Capital']},
    {'name': 'Qumra Capital', 'aliases': ['Qumra Capital']},
]


def get_vc_firms():
    """Return list of Israeli VC firms to track.

    Returns:
        List of dicts with 'name' and 'aliases' keys.
    """
    return VC_FIRMS


# Build compiled regex patterns for each VC firm
_VC_PATTERNS = []
for firm in VC_FIRMS:
    all_names = [firm['name']] + firm.get('aliases', [])
    # Build alternation pattern, longest first to avoid partial matches
    all_names.sort(key=len, reverse=True)
    escaped = [re.escape(n) for n in all_names]
    pattern = re.compile(r'(?i)\b(?:' + '|'.join(escaped) + r')\b')
    _VC_PATTERNS.append((firm['name'], pattern))


# ---------------------------------------------------------------------------
# Signal types for VC engagement
# ---------------------------------------------------------------------------

SIGNAL_TYPE_NEWS = 'news_mention'
SIGNAL_TYPE_BLOG = 'blog_post'
SIGNAL_TYPE_PODCAST = 'podcast'
SIGNAL_TYPE_EVENT = 'event'
SIGNAL_TYPE_LINKEDIN = 'linkedin_engagement'

# Patterns that suggest active engagement (not just casual mentions)
ENGAGEMENT_PATTERNS = [
    re.compile(r'(?i)\b(?:invest|funding|round|seed|series\s+[a-d]|raise|backed)\b'),
    re.compile(r'(?i)\b(?:portfolio|advisor|board|mentor)\b'),
    re.compile(r'(?i)\b(?:partnership|collaborate|join|announce)\b'),
    re.compile(r'(?i)\b(?:pitch|demo|meeting|office\s+hours)\b'),
]

# Patterns for specific content types
PODCAST_PATTERNS = re.compile(r'(?i)\b(?:podcast|episode|interview|show|listen)\b')
BLOG_PATTERNS = re.compile(r'(?i)\b(?:blog|post|article|wrote|writes|medium\.com)\b')


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

def init_competitive_tables(conn):
    """Create competitive_signals table."""
    conn.execute('''CREATE TABLE IF NOT EXISTS competitive_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        vc_firm TEXT,
        vc_partner_name TEXT,
        signal_type TEXT,
        signal_detail TEXT,
        detected_date TEXT NOT NULL
    )''')
    conn.commit()


# ---------------------------------------------------------------------------
# Search-based detection
# ---------------------------------------------------------------------------

def search_vc_engagement(person_name, brave_search_fn):
    """Search for VC engagement with a person via Brave Search.

    Queries Brave for the person's name alongside VC-related terms, then
    checks results for specific VC firm mentions.

    Args:
        person_name: Full name string.
        brave_search_fn: Callable(query) -> list of search result dicts.
            Each result should have 'title', 'url', 'description' keys.

    Returns:
        List of signal dicts:
            {vc_firm, vc_partner_name, signal_type, signal_detail}
    """
    if not brave_search_fn or not person_name:
        return []

    signals = []
    seen_keys = set()  # (vc_firm, signal_type) to deduplicate

    queries = [
        f'"{person_name}" venture capital Israel investment',
        f'"{person_name}" startup funding seed round',
        f'"{person_name}" VC Israel backed',
    ]

    for query in queries:
        try:
            results = brave_search_fn(query)
        except Exception:
            continue

        if not results:
            continue

        for result in results[:5]:
            title = result.get('title', '')
            url = result.get('url', '')
            description = result.get('description', '')
            combined = f'{title} {description}'

            # Verify the person is actually mentioned
            name_parts = person_name.lower().split()
            if not any(part in combined.lower() for part in name_parts if len(part) > 2):
                continue

            # Check which VC firms are mentioned
            for vc_name, vc_pattern in _VC_PATTERNS:
                match = vc_pattern.search(combined)
                if not match:
                    continue

                # Determine signal type
                signal_type = SIGNAL_TYPE_NEWS  # default
                if PODCAST_PATTERNS.search(combined):
                    signal_type = SIGNAL_TYPE_PODCAST
                elif BLOG_PATTERNS.search(combined):
                    signal_type = SIGNAL_TYPE_BLOG

                dedup_key = (vc_name, signal_type, url)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                # Check if this looks like active engagement
                is_active = any(p.search(combined) for p in ENGAGEMENT_PATTERNS)

                signals.append({
                    'vc_firm': vc_name,
                    'vc_partner_name': None,  # Can't reliably extract from search
                    'signal_type': signal_type,
                    'signal_detail': f'{title[:120]} ({url})',
                    'is_active_engagement': is_active,
                })

    return signals


# ---------------------------------------------------------------------------
# LinkedIn profile-based detection
# ---------------------------------------------------------------------------

def extract_vc_mentions_from_profile(profile_text):
    """Check LinkedIn profile for VC firm/partner mentions.

    Looks for VC firms in:
    - Experience section (advisory roles)
    - Recommendations
    - Endorsements
    - General profile text

    Args:
        profile_text: ARIA snapshot text from LinkedIn profile.

    Returns:
        List of signal dicts:
            {vc_firm, vc_partner_name, signal_type, signal_detail}
    """
    if not profile_text:
        return []

    signals = []
    seen_firms = set()

    for vc_name, vc_pattern in _VC_PATTERNS:
        match = vc_pattern.search(profile_text)
        if not match:
            continue

        if vc_name in seen_firms:
            continue
        seen_firms.add(vc_name)

        # Try to determine the context of the mention
        # Get surrounding text (up to 200 chars around the match)
        start = max(0, match.start() - 100)
        end = min(len(profile_text), match.end() + 100)
        context = profile_text[start:end]

        # Determine if this is an advisory/board role
        advisory_pattern = re.compile(
            r'(?i)\b(?:advisor|advisory|board|mentor|venture\s+partner|scout|eir|'
            r'entrepreneur\s+in\s+residence)\b'
        )
        is_advisory = advisory_pattern.search(context) is not None

        # Check for recommendation context
        rec_pattern = re.compile(r'(?i)\b(?:recommend|endorses?|endorsed)\b')
        is_recommendation = rec_pattern.search(context) is not None

        if is_advisory:
            detail = f'Advisory/board role connected to {vc_name}'
        elif is_recommendation:
            detail = f'Recommendation involving {vc_name}'
        else:
            detail = f'{vc_name} mentioned in profile'

        signals.append({
            'vc_firm': vc_name,
            'vc_partner_name': None,
            'signal_type': SIGNAL_TYPE_LINKEDIN,
            'signal_detail': detail,
        })

    return signals


# ---------------------------------------------------------------------------
# Full scan
# ---------------------------------------------------------------------------

def scan_competitive_signals(conn, watchlist_people, brave_search_fn):
    """Run competitive intelligence scan. Returns signals.

    For each watchlist member:
    1. Search Brave for VC engagement mentions
    2. Check profile text for VC firm references
    3. Save new signals to the database

    Args:
        conn: SQLite connection.
        watchlist_people: List of dicts with at least {id, name}.
            Optional key: profile_text.
        brave_search_fn: Callable(query) -> list of search results.

    Returns:
        List of new signal dicts that were saved to the database.
    """
    if not watchlist_people:
        return []

    new_signals = []
    now = datetime.now().strftime('%Y-%m-%d')

    for person in watchlist_people:
        person_id = person.get('id')
        person_name = person.get('name', '')
        profile_text = person.get('profile_text', '')

        if not person_name:
            continue

        person_signals = []

        # Brave Search signals
        if brave_search_fn:
            try:
                search_signals = search_vc_engagement(person_name, brave_search_fn)
                person_signals.extend(search_signals)
            except Exception:
                pass

        # LinkedIn profile signals
        if profile_text:
            try:
                profile_signals = extract_vc_mentions_from_profile(profile_text)
                person_signals.extend(profile_signals)
            except Exception:
                pass

        # Save to database, deduplicating against recent entries
        for signal in person_signals:
            # Check for existing signal within the past 7 days
            existing = conn.execute(
                '''SELECT 1 FROM competitive_signals
                   WHERE person_id = ? AND vc_firm = ? AND signal_type = ?
                   AND detected_date >= ?''',
                (person_id, signal.get('vc_firm'),
                 signal.get('signal_type'),
                 (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
            ).fetchone()

            if existing:
                continue

            conn.execute('''
                INSERT INTO competitive_signals
                    (person_id, vc_firm, vc_partner_name, signal_type,
                     signal_detail, detected_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                person_id,
                signal.get('vc_firm'),
                signal.get('vc_partner_name'),
                signal.get('signal_type'),
                signal.get('signal_detail'),
                now,
            ))

            signal['person_id'] = person_id
            signal['detected_date'] = now
            new_signals.append(signal)

    conn.commit()
    return new_signals


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_competitive_signals(conn, person_id=None, vc_firm=None, days=30):
    """Retrieve recent competitive intelligence signals.

    Args:
        conn: SQLite connection.
        person_id: Optional person ID filter.
        vc_firm: Optional VC firm name filter.
        days: How far back to look (default 30).

    Returns:
        List of dicts with signal data.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    conditions = ['detected_date >= ?']
    params = [cutoff]

    if person_id is not None:
        conditions.append('person_id = ?')
        params.append(person_id)

    if vc_firm is not None:
        conditions.append('vc_firm = ?')
        params.append(vc_firm)

    where = ' AND '.join(conditions)
    cursor = conn.execute(
        f'''SELECT id, person_id, vc_firm, vc_partner_name,
                   signal_type, signal_detail, detected_date
            FROM competitive_signals
            WHERE {where}
            ORDER BY detected_date DESC''',
        params
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_vc_engagement_summary(conn, days=30):
    """Summarize VC engagement across the entire watchlist.

    Returns a dict keyed by VC firm name, with counts and person names.

    Args:
        conn: SQLite connection.
        days: How far back to look (default 30).

    Returns:
        Dict: {vc_firm: {count, signal_types, person_ids}}
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    cursor = conn.execute(
        '''SELECT vc_firm, signal_type, person_id
           FROM competitive_signals
           WHERE detected_date >= ?
           ORDER BY vc_firm''',
        (cutoff,)
    )

    summary = {}
    for row in cursor.fetchall():
        vc_firm = row[0]
        if vc_firm not in summary:
            summary[vc_firm] = {
                'count': 0,
                'signal_types': set(),
                'person_ids': set(),
            }
        summary[vc_firm]['count'] += 1
        summary[vc_firm]['signal_types'].add(row[1])
        if row[2] is not None:
            summary[vc_firm]['person_ids'].add(row[2])

    # Convert sets to lists for JSON serialization
    for vc_firm in summary:
        summary[vc_firm]['signal_types'] = list(summary[vc_firm]['signal_types'])
        summary[vc_firm]['person_ids'] = list(summary[vc_firm]['person_ids'])

    return summary
