"""
Social Graph — Detect founding team formation patterns.

Works with what's actually available: LinkedIn profile text (from ARIA
snapshots), Brave Search results, and cross-referencing watchlist members.

Key detection patterns:
- Multiple watchlist members listing the same stealth/unnamed company
- Shared recent employer (2+ people who left the same company recently)
- Connections to known startup lawyers, VCs, and service providers
- Co-appearances in news or events
- Mutual recommendations between watchlist members

The core insight: startups don't form in isolation. When 2-3 strong founders
start interacting with startup lawyers, accountants, and each other in new
ways, formation is likely underway.
"""

import re
import json
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Known Israeli startup ecosystem players
# ---------------------------------------------------------------------------

STARTUP_LAW_FIRMS = [
    'Meitar',
    'GKH',
    'Gross Kleinhendler Hodak',
    'Gross Kleinhendler',
    'Pearl Cohen',
    'ELTA',
    'Naschitz Brandes Amir',
    'Naschitz Brandes',
    'Fischer Behar Chen',
    'Fischer Behar',
    'Herzog Fox Neeman',
    'Herzog Fox',
    'Yigal Arnon',
    'Goldfarb Gross Seligman',
    'Goldfarb Seligman',
    'Shibolet',
    'Amit Pollak Matalon',
    'Gornitzky',
    'S. Horowitz',
    'Tadmor Levy',
]

STARTUP_ACCOUNTANTS = [
    'Fahn Kanne',
    'Grant Thornton Israel',
    'BDO Israel',
    'BDO startup',
    'Kesselman & Kesselman',
    'Kesselman Kesselman',
    'PwC Israel',
    'Deloitte Israel',
    'Somekh Chaikin',
    'KPMG Israel',
    'EY Israel',
    'Ernst & Young Israel',
    'Brightman Almagor Zohar',
]

# Build compiled patterns for fast matching
_LAW_PATTERNS = [
    re.compile(r'(?i)\b' + re.escape(firm) + r'\b')
    for firm in STARTUP_LAW_FIRMS
]

_ACCOUNTANT_PATTERNS = [
    re.compile(r'(?i)\b' + re.escape(firm) + r'\b')
    for firm in STARTUP_ACCOUNTANTS
]


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

def init_social_tables(conn):
    """Create connection_signals and team_formation_alerts tables."""
    conn.execute('''CREATE TABLE IF NOT EXISTS connection_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        related_person TEXT,
        related_title TEXT,
        related_company TEXT,
        signal_type TEXT,
        detected_date TEXT NOT NULL,
        details TEXT
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS team_formation_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        persons TEXT,
        shared_signals TEXT,
        signal_strength TEXT,
        created_at TEXT NOT NULL
    )''')
    conn.commit()


# ---------------------------------------------------------------------------
# Profile text analysis
# ---------------------------------------------------------------------------

def extract_connections_from_profile(profile_text):
    """Extract visible connections, recommendations, shared companies from profile text.

    Parses LinkedIn ARIA snapshot text for:
    - Recommendations given/received (names + titles)
    - Companies mentioned
    - Stealth/vague employment indicators

    Args:
        profile_text: ARIA snapshot text from LinkedIn profile.

    Returns:
        dict with keys:
            companies: list of company name strings
            recommendations: list of {name, title, company} dicts
            stealth_indicators: list of strings describing vague/stealth signals
            current_title: str or None
            current_company: str or None
    """
    if not profile_text:
        return {
            'companies': [],
            'recommendations': [],
            'stealth_indicators': [],
            'current_title': None,
            'current_company': None,
        }

    text = profile_text
    companies = []
    recommendations = []
    stealth_indicators = []
    current_title = None
    current_company = None

    # --- Current position ---
    # ARIA snapshots often show the headline as early text
    headline_match = re.search(
        r'(?:heading|StaticText)\s*["\']?(.+?(?:at|@)\s+.+?)["\']?\s*$',
        text, re.MULTILINE
    )
    if headline_match:
        parts = re.split(r'\s+(?:at|@)\s+', headline_match.group(1), maxsplit=1)
        if len(parts) == 2:
            current_title = parts[0].strip()
            current_company = parts[1].strip()

    # --- Company extraction ---
    # Look for "at Company" or "Company · Full-time" patterns
    company_patterns = [
        re.compile(r'(?:at|@)\s+([A-Z][A-Za-z0-9\s&\-\.]+?)(?:\s*[·|]|\s*$)', re.MULTILINE),
        re.compile(r'([A-Z][A-Za-z0-9\s&\-\.]+?)\s*·\s*(?:Full-time|Part-time|Contract|Freelance)', re.MULTILINE),
    ]
    seen_companies = set()
    for pattern in company_patterns:
        for m in pattern.finditer(text):
            company = m.group(1).strip()
            if len(company) > 2 and company.lower() not in seen_companies:
                seen_companies.add(company.lower())
                companies.append(company)

    # --- Recommendation extraction ---
    rec_patterns = [
        re.compile(
            r'(?:Recommended|Recommendation)\s+(?:by\s+)?["\']?([A-Z][a-z]+\s+[A-Z][a-z]+)["\']?'
            r'(?:\s*,\s*|\s*[·|]\s*)([^"\n]+)',
            re.MULTILINE
        ),
        re.compile(
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:recommends?|endorsed)',
            re.MULTILINE
        ),
    ]
    for pattern in rec_patterns:
        for m in pattern.finditer(text):
            name = m.group(1).strip()
            title = m.group(2).strip() if m.lastindex >= 2 else ''
            rec_company = ''
            # Try to extract company from title
            title_parts = re.split(r'\s+(?:at|@)\s+', title, maxsplit=1)
            if len(title_parts) == 2:
                title = title_parts[0].strip()
                rec_company = title_parts[1].strip()

            recommendations.append({
                'name': name,
                'title': title,
                'company': rec_company,
            })

    # --- Stealth indicators ---
    stealth_patterns = [
        (re.compile(r'(?i)\bstealth\b'), 'Lists "stealth" company'),
        (re.compile(r'(?i)\bstealth\s+(?:mode|startup)\b'), 'Stealth mode/startup reference'),
        (re.compile(r'(?i)\bsomething\s+new\b'), '"Something new" in profile'),
        (re.compile(r'(?i)\bbuilding\s+(?:the\s+)?next\b'), '"Building next" reference'),
        (re.compile(r'(?i)\bco-?founder\s+at\s+(?:stealth|tbd|undisclosed|confidential)\b'),
         'Co-founder at undisclosed company'),
        (re.compile(r'(?i)\b(?:exploring|starting)\s+(?:a\s+)?new\s+(?:venture|chapter|journey)\b'),
         'New venture language'),
        (re.compile(r'(?i)\bformer(?:ly)?\s+(?:at|@)\b'), 'Recently left position'),
        (re.compile(r'(?i)\b(?:advisor|consulting)\s+(?:for\s+)?(?:early[\s-]stage|startups?)\b'),
         'Advising early-stage (possible soft launch)'),
    ]
    for pattern, description in stealth_patterns:
        if pattern.search(text):
            stealth_indicators.append(description)

    return {
        'companies': companies,
        'recommendations': recommendations,
        'stealth_indicators': stealth_indicators,
        'current_title': current_title,
        'current_company': current_company,
    }


def detect_lawyer_vc_connections(profile_text, person_name):
    """Check if profile mentions known startup lawyers or VCs.

    These connections often appear as recommendations, endorsements,
    or mutual connections visible in the ARIA snapshot.

    Args:
        profile_text: ARIA snapshot text.
        person_name: Name of the person whose profile this is.

    Returns:
        List of signal dicts:
            {related_person, related_company, signal_type, details}
    """
    if not profile_text:
        return []

    signals = []

    # Check for law firm mentions
    for i, pattern in enumerate(_LAW_PATTERNS):
        if pattern.search(profile_text):
            signals.append({
                'related_person': None,
                'related_title': None,
                'related_company': STARTUP_LAW_FIRMS[i],
                'signal_type': 'lawyer',
                'details': f'{person_name} profile mentions {STARTUP_LAW_FIRMS[i]}',
            })

    # Check for accounting firm mentions
    for i, pattern in enumerate(_ACCOUNTANT_PATTERNS):
        if pattern.search(profile_text):
            signals.append({
                'related_person': None,
                'related_title': None,
                'related_company': STARTUP_ACCOUNTANTS[i],
                'signal_type': 'accountant',
                'details': f'{person_name} profile mentions {STARTUP_ACCOUNTANTS[i]}',
            })

    return signals


# ---------------------------------------------------------------------------
# Team formation detection
# ---------------------------------------------------------------------------

def detect_team_formation(conn, watchlist_people):
    """Analyze watchlist for team formation patterns.

    Cross-references watchlist members to find:
    - 2+ people listing the same unknown/stealth company
    - 2+ people who left the same company within a 6-month window
    - Mutual recommendation patterns

    Args:
        conn: SQLite connection.
        watchlist_people: List of dicts with at least {id, name}.
            Optional keys: current_company, previous_company, left_date, profile_text.

    Returns:
        List of team formation alert dicts:
            {persons, shared_signals, signal_strength}
    """
    if not watchlist_people or len(watchlist_people) < 2:
        return []

    alerts = []
    now = datetime.now().strftime('%Y-%m-%d')

    # Group people by current company (looking for shared stealth/unknown)
    company_groups = {}
    for person in watchlist_people:
        company = (person.get('current_company') or '').strip()
        if not company:
            continue

        key = company.lower()
        if key not in company_groups:
            company_groups[key] = []
        company_groups[key].append(person)

    # Flag when 2+ watchlist members share a company (especially stealth)
    stealth_keywords = {'stealth', 'tbd', 'undisclosed', 'confidential', 'new venture'}
    for company_key, members in company_groups.items():
        if len(members) < 2:
            continue

        is_stealth = any(kw in company_key for kw in stealth_keywords)
        names = [m.get('name', 'Unknown') for m in members]

        signal_strength = 'high' if is_stealth else 'medium'
        shared = [f'Both at "{members[0].get("current_company", company_key)}"']
        if is_stealth:
            shared.append('Company appears to be in stealth')

        alerts.append({
            'persons': json.dumps(names),
            'shared_signals': json.dumps(shared),
            'signal_strength': signal_strength,
            'created_at': now,
        })

    # Group by previous company + recent departure
    prev_company_groups = {}
    for person in watchlist_people:
        prev = (person.get('previous_company') or '').strip()
        if not prev:
            continue

        key = prev.lower()
        if key not in prev_company_groups:
            prev_company_groups[key] = []
        prev_company_groups[key].append(person)

    for company_key, members in prev_company_groups.items():
        if len(members) < 2:
            continue

        # Check if departures are within ~6 months of each other
        dates = []
        for m in members:
            left = m.get('left_date')
            if left:
                try:
                    dates.append(datetime.strptime(left, '%Y-%m-%d'))
                except (ValueError, TypeError):
                    pass

        clustered = True
        if len(dates) >= 2:
            dates.sort()
            span = (dates[-1] - dates[0]).days
            clustered = span <= 180

        if clustered:
            names = [m.get('name', 'Unknown') for m in members]
            alerts.append({
                'persons': json.dumps(names),
                'shared_signals': json.dumps([
                    f'Both previously at "{members[0].get("previous_company", company_key)}"',
                    'Left within similar timeframe',
                ]),
                'signal_strength': 'medium',
                'created_at': now,
            })

    # Check connection_signals table for mutual connections
    try:
        person_ids = [p.get('id') for p in watchlist_people if p.get('id') is not None]
        if len(person_ids) >= 2:
            placeholders = ','.join('?' * len(person_ids))

            # Find people who share connections to the same person/company
            rows = conn.execute(f'''
                SELECT cs1.person_id, cs2.person_id,
                       cs1.related_person, cs1.related_company, cs1.signal_type
                FROM connection_signals cs1
                JOIN connection_signals cs2
                    ON cs1.related_company = cs2.related_company
                    AND cs1.person_id != cs2.person_id
                WHERE cs1.person_id IN ({placeholders})
                  AND cs2.person_id IN ({placeholders})
                  AND cs1.signal_type IN ('lawyer', 'accountant')
            ''', person_ids + person_ids).fetchall()

            # Group shared lawyer/accountant connections
            seen_pairs = set()
            for row in rows:
                pair = tuple(sorted([row[0], row[1]]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                # Look up names
                id_to_name = {p['id']: p.get('name', 'Unknown') for p in watchlist_people if p.get('id')}
                names = [id_to_name.get(pair[0], str(pair[0])),
                         id_to_name.get(pair[1], str(pair[1]))]

                alerts.append({
                    'persons': json.dumps(names),
                    'shared_signals': json.dumps([
                        f'Both connected to {row[4]}: {row[3]}',
                    ]),
                    'signal_strength': 'medium',
                    'created_at': now,
                })
    except Exception:
        # Table might not have data yet
        pass

    return alerts


# ---------------------------------------------------------------------------
# Full scan
# ---------------------------------------------------------------------------

def scan_social_signals(conn, watchlist_people, brave_search_fn=None):
    """Run social graph analysis. Returns signals.

    Performs:
    1. Cross-reference watchlist for team formation patterns
    2. Search for co-appearances in news (via Brave)
    3. Save new connection signals and team formation alerts

    Args:
        conn: SQLite connection.
        watchlist_people: List of dicts with at least {id, name}.
        brave_search_fn: Optional callable(query) -> list of search results.

    Returns:
        dict with keys:
            connection_signals: list of new connection signal dicts
            team_alerts: list of team formation alert dicts
    """
    if not watchlist_people:
        return {'connection_signals': [], 'team_alerts': []}

    now = datetime.now().strftime('%Y-%m-%d')
    new_connections = []
    all_alerts = []

    # Phase 1: Profile-based analysis for each person
    for person in watchlist_people:
        person_id = person.get('id')
        person_name = person.get('name', '')
        profile_text = person.get('profile_text', '')

        if profile_text:
            # Check for lawyer/VC connections
            lawyer_signals = detect_lawyer_vc_connections(profile_text, person_name)
            for signal in lawyer_signals:
                signal['person_id'] = person_id
                signal['detected_date'] = now

                # Deduplicate
                existing = conn.execute(
                    '''SELECT 1 FROM connection_signals
                       WHERE person_id = ? AND related_company = ? AND signal_type = ?''',
                    (person_id, signal.get('related_company'), signal.get('signal_type'))
                ).fetchone()

                if not existing:
                    conn.execute('''
                        INSERT INTO connection_signals
                            (person_id, related_person, related_title,
                             related_company, signal_type, detected_date, details)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        person_id,
                        signal.get('related_person'),
                        signal.get('related_title'),
                        signal.get('related_company'),
                        signal.get('signal_type'),
                        now,
                        signal.get('details'),
                    ))
                    new_connections.append(signal)

    # Phase 2: Brave Search for co-appearances
    if brave_search_fn and len(watchlist_people) >= 2:
        # Check pairs of watchlist members for co-appearances
        names = [p.get('name', '') for p in watchlist_people if p.get('name')]
        for i in range(min(len(names), 10)):
            for j in range(i + 1, min(len(names), 10)):
                try:
                    query = f'"{names[i]}" "{names[j]}" Israel startup'
                    results = brave_search_fn(query)
                    if results:
                        for result in results[:3]:
                            title = result.get('title', '')
                            url = result.get('url', '')
                            new_connections.append({
                                'person_id': watchlist_people[i].get('id'),
                                'related_person': names[j],
                                'related_title': None,
                                'related_company': None,
                                'signal_type': 'co_appearance',
                                'detected_date': now,
                                'details': f'Co-mentioned: {title[:120]} ({url})',
                            })
                except Exception:
                    continue

    # Phase 3: Team formation detection
    alerts = detect_team_formation(conn, watchlist_people)
    for alert in alerts:
        # Deduplicate
        existing = conn.execute(
            '''SELECT 1 FROM team_formation_alerts
               WHERE persons = ? AND created_at >= ?''',
            (alert['persons'], (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
        ).fetchone()

        if not existing:
            conn.execute('''
                INSERT INTO team_formation_alerts
                    (persons, shared_signals, signal_strength, created_at)
                VALUES (?, ?, ?, ?)
            ''', (
                alert['persons'],
                alert['shared_signals'],
                alert['signal_strength'],
                now,
            ))
            all_alerts.append(alert)

    conn.commit()

    return {
        'connection_signals': new_connections,
        'team_alerts': all_alerts,
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_connection_signals(conn, person_id=None, signal_type=None, days=30):
    """Retrieve recent connection signals.

    Args:
        conn: SQLite connection.
        person_id: Optional person ID filter.
        signal_type: Optional signal type filter.
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

    if signal_type is not None:
        conditions.append('signal_type = ?')
        params.append(signal_type)

    where = ' AND '.join(conditions)
    cursor = conn.execute(
        f'''SELECT id, person_id, related_person, related_title,
                   related_company, signal_type, detected_date, details
            FROM connection_signals
            WHERE {where}
            ORDER BY detected_date DESC''',
        params
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_team_formation_alerts(conn, days=30):
    """Retrieve recent team formation alerts.

    Args:
        conn: SQLite connection.
        days: How far back to look (default 30).

    Returns:
        List of dicts with alert data. persons and shared_signals are
        parsed from JSON into Python lists.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    cursor = conn.execute(
        '''SELECT id, persons, shared_signals, signal_strength, created_at
           FROM team_formation_alerts
           WHERE created_at >= ?
           ORDER BY created_at DESC''',
        (cutoff,)
    )

    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    # Parse JSON fields
    for row in rows:
        try:
            row['persons'] = json.loads(row['persons']) if row['persons'] else []
        except (json.JSONDecodeError, TypeError):
            row['persons'] = []
        try:
            row['shared_signals'] = json.loads(row['shared_signals']) if row['shared_signals'] else []
        except (json.JSONDecodeError, TypeError):
            row['shared_signals'] = []

    return rows
