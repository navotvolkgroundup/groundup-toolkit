"""
Domain Monitor — Detect domain registrations that may signal startup formation.

Since we lack a WHOIS API key, this module uses free approaches:
- DNS lookups to check if name-based domains resolve
- GitHub repo scanning for custom domain references (CNAME, homepage)
- Brave Search for recently registered domains mentioning watchlist members

Limitations are real: DNS only tells us a domain exists, not when it was registered
or by whom. Combined with other signals (going dark, stealth employment) this still
adds value.
"""

import re
import json
import socket
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Domain name patterns to probe
# ---------------------------------------------------------------------------

DOMAIN_SUFFIXES = [
    '.com', '.io', '.ai', '.co', '.dev', '.tech', '.app',
]

def _normalize_name(name):
    """Split a person name into (first, last) lowercased, ASCII-safe parts.

    Returns tuple of (first, last) or None if name can't be parsed.
    """
    if not name or not name.strip():
        return None

    parts = name.strip().lower().split()
    # Filter out single-char particles, titles, etc.
    parts = [p for p in parts if len(p) > 1]

    if len(parts) < 2:
        return None

    first = re.sub(r'[^a-z]', '', parts[0])
    last = re.sub(r'[^a-z]', '', parts[-1])

    if not first or not last:
        return None

    return (first, last)


def generate_candidate_domains(person_name):
    """Generate list of domain patterns to check for a person name.

    Produces combinations like:
        firstlast.com, lastfirst.com, lastname.io, lastai.com,
        firstlast.ai, first-last.com, etc.

    Args:
        person_name: Full name string.

    Returns:
        List of domain name strings.
    """
    parsed = _normalize_name(person_name)
    if not parsed:
        return []

    first, last = parsed
    candidates = []

    # Core patterns
    bases = [
        f'{first}{last}',
        f'{last}{first}',
        f'{first}-{last}',
        f'{last}',
        f'{last}ai',
        f'{first}{last}ai',
        f'{last}labs',
        f'{last}tech',
        f'{first}{last}labs',
    ]

    for base in bases:
        for suffix in DOMAIN_SUFFIXES:
            candidates.append(f'{base}{suffix}')

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for d in candidates:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    return unique


# ---------------------------------------------------------------------------
# DNS-based domain existence check
# ---------------------------------------------------------------------------

def check_domain_exists(domain, timeout=3):
    """DNS lookup to check if domain resolves. Returns bool.

    This only tells us the domain exists and has DNS records — not who owns
    it or when it was registered. False negatives are possible (e.g. domain
    registered but not yet pointed anywhere).

    Args:
        domain: Domain name string (e.g. 'johndoe.com').
        timeout: Socket timeout in seconds.

    Returns:
        True if the domain resolves, False otherwise.
    """
    original_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(domain, None)
        return True
    except (socket.gaierror, socket.timeout, OSError):
        return False
    finally:
        socket.setdefaulttimeout(original_timeout)


# ---------------------------------------------------------------------------
# GitHub domain scanning
# ---------------------------------------------------------------------------

def scan_github_domains(repos_data):
    """Check GitHub repos for custom domain references.

    Looks for:
    - CNAME file contents (GitHub Pages custom domain)
    - Homepage field in repo metadata
    - Custom domain patterns in repo descriptions

    Args:
        repos_data: List of dicts with GitHub repo info. Expected keys:
            - name: repo name
            - homepage: homepage URL or None
            - description: repo description or None
            - has_pages: bool (optional)

    Returns:
        List of dicts with discovered domains:
            {domain, source_repo, source_field}
    """
    if not repos_data:
        return []

    found = []
    domain_pattern = re.compile(
        r'(?:https?://)?([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
        r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*'
        r'\.[a-zA-Z]{2,})'
    )

    # Skip common hosting domains that aren't custom
    skip_domains = {
        'github.io', 'github.com', 'githubusercontent.com',
        'vercel.app', 'netlify.app', 'herokuapp.com',
        'npmjs.com', 'pypi.org', 'readthedocs.io',
    }

    for repo in repos_data:
        repo_name = repo.get('name', 'unknown')

        # Check homepage field
        homepage = repo.get('homepage') or ''
        if homepage:
            m = domain_pattern.search(homepage)
            if m:
                domain = m.group(1).lower()
                if not any(domain.endswith(skip) for skip in skip_domains):
                    found.append({
                        'domain': domain,
                        'source_repo': repo_name,
                        'source_field': 'homepage',
                    })

        # Check description for URLs
        description = repo.get('description') or ''
        if description:
            for m in domain_pattern.finditer(description):
                domain = m.group(1).lower()
                if not any(domain.endswith(skip) for skip in skip_domains):
                    found.append({
                        'domain': domain,
                        'source_repo': repo_name,
                        'source_field': 'description',
                    })

    # Deduplicate by domain
    seen = set()
    unique = []
    for entry in found:
        if entry['domain'] not in seen:
            seen.add(entry['domain'])
            unique.append(entry)

    return unique


# ---------------------------------------------------------------------------
# Full scan for a person
# ---------------------------------------------------------------------------

def scan_domains_for_person(person_name, person_id=None, brave_search_fn=None):
    """Check candidate domains for a person. Returns list of signals.

    Runs DNS lookups on generated candidate domains and optionally uses
    Brave Search to find recently registered domains mentioning the person.

    Args:
        person_name: Full name string.
        person_id: Optional tracked_people ID for DB linking.
        brave_search_fn: Optional callable(query) -> list of search results.
            Each result should have 'title', 'url', 'description' keys.

    Returns:
        List of signal dicts:
            {domain_name, source, signal_level, details, person_id}
    """
    signals = []
    now = datetime.now().strftime('%Y-%m-%d')

    # Phase 1: DNS probing of candidate domains
    candidates = generate_candidate_domains(person_name)
    for domain in candidates:
        try:
            if check_domain_exists(domain):
                signals.append({
                    'domain_name': domain,
                    'registration_date': None,  # DNS can't tell us this
                    'registrant_info': None,
                    'matched_person_id': person_id,
                    'signal_level': 'low',  # Domain existing is weak on its own
                    'source': 'dns_probe',
                    'details': f'Domain {domain} resolves (name pattern match for {person_name})',
                    'created_at': now,
                })
        except Exception:
            # Don't let a single DNS failure break the scan
            continue

    # Phase 2: Brave Search for new domain registrations
    if brave_search_fn:
        queries = [
            f'"{person_name}" new domain startup site',
            f'"{person_name}" registered domain',
        ]
        for query in queries:
            try:
                results = brave_search_fn(query)
                if not results:
                    continue
                for result in results[:5]:
                    title = result.get('title', '')
                    url = result.get('url', '')
                    description = result.get('description', '')
                    combined = f'{title} {url} {description}'

                    # Only include if the person name appears in the result
                    name_parts = person_name.lower().split()
                    if not any(part in combined.lower() for part in name_parts if len(part) > 2):
                        continue

                    signals.append({
                        'domain_name': url,
                        'registration_date': None,
                        'registrant_info': None,
                        'matched_person_id': person_id,
                        'signal_level': 'medium',
                        'source': 'brave_search',
                        'details': f'Search result: {title[:120]}',
                        'created_at': now,
                    })
            except Exception:
                continue

    return signals


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

def init_domain_tables(conn):
    """Create domain_signals table."""
    conn.execute('''CREATE TABLE IF NOT EXISTS domain_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_name TEXT NOT NULL,
        registration_date TEXT,
        registrant_info TEXT,
        matched_person_id INTEGER,
        signal_level TEXT,
        source TEXT,
        created_at TEXT NOT NULL
    )''')
    conn.commit()


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def save_domain_signal(conn, signal):
    """Persist a single domain signal to the database.

    Args:
        conn: SQLite connection.
        signal: Dict with domain signal data.
    """
    conn.execute('''
        INSERT INTO domain_signals
            (domain_name, registration_date, registrant_info,
             matched_person_id, signal_level, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        signal.get('domain_name'),
        signal.get('registration_date'),
        signal.get('registrant_info'),
        signal.get('matched_person_id'),
        signal.get('signal_level'),
        signal.get('source'),
        signal.get('created_at', datetime.now().strftime('%Y-%m-%d')),
    ))
    conn.commit()


def get_domain_signals(conn, person_id=None, days=30):
    """Retrieve recent domain signals, optionally filtered by person.

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
            '''SELECT id, domain_name, registration_date, registrant_info,
                      matched_person_id, signal_level, source, created_at
               FROM domain_signals
               WHERE matched_person_id = ? AND created_at >= ?
               ORDER BY created_at DESC''',
            (person_id, cutoff)
        )
    else:
        cursor = conn.execute(
            '''SELECT id, domain_name, registration_date, registrant_info,
                      matched_person_id, signal_level, source, created_at
               FROM domain_signals
               WHERE created_at >= ?
               ORDER BY created_at DESC''',
            (cutoff,)
        )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
