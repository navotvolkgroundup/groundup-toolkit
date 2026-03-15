"""
Company Registrar Monitor — Tracks new company registrations in Israel via
the public Companies Registrar (Rasham HaChavarot) API.

Scans for newly registered companies and cross-references directors/shareholders
against the Founder Scout watchlist. Also flags companies whose stated purpose
contains tech/startup keywords, even without a name match.

Data source: https://data.gov.il/dataset/companies-registry
API endpoint: https://data.gov.il/api/3/action/datastore_search
Resource ID: f004176c-b85f-4542-8901-7b3176f9a054
"""

import re
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_ENDPOINT = "https://data.gov.il/api/3/action/datastore_search"
RESOURCE_ID = "f004176c-b85f-4542-8901-7b3176f9a054"

TECH_KEYWORDS_EN = [
    "software", "technology", "platform", "AI", "artificial intelligence",
    "machine learning", "cyber", "SaaS", "cloud", "data", "analytics",
    "blockchain", "fintech", "healthtech", "medtech", "biotech", "robotics",
    "autonomous", "drone", "IoT", "API",
]

TECH_KEYWORDS_HE = [
    "טכנולוגיה", "תוכנה", "פלטפורמה", "בינה מלאכותית", "סייבר",
    "ענן", "נתונים", "אנליטיקה", "פינטק", "רובוטיקה", "אוטונומי",
]

# Combined regex for fast matching (case-insensitive for English keywords)
_EN_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in TECH_KEYWORDS_EN) + r")\b",
    re.IGNORECASE,
)
_HE_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in TECH_KEYWORDS_HE)
)


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

CREATE_COMPANY_REGISTRATIONS = """
CREATE TABLE IF NOT EXISTS company_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    company_name_en TEXT,
    registration_number TEXT UNIQUE,
    registration_date TEXT,
    company_type TEXT,
    stated_purpose TEXT,
    directors TEXT,
    matched_person_id INTEGER,
    signal_level TEXT,
    created_at TEXT NOT NULL
)
"""


def init_registrar_tables(conn):
    """Create company_registrations table."""
    conn.execute(CREATE_COMPANY_REGISTRATIONS)
    conn.commit()


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------

def _api_request(params):
    """Make a GET request to the data.gov.il CKAN datastore API.

    Args:
        params: dict of query parameters.

    Returns:
        Parsed JSON response dict, or None on failure.
    """
    url = API_ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "GroundUp-FounderScout/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                return data.get("result", {})
            logger.warning("API returned success=false: %s", data)
            return None
    except Exception as e:
        logger.error("Failed to query data.gov.il: %s", e)
        return None


def fetch_recent_registrations(since_date=None):
    """Query data.gov.il API for recent company registrations.

    The API uses CKAN datastore_search. Filters by registration date >= since_date.

    Args:
        since_date: ISO date string (YYYY-MM-DD). Defaults to yesterday.

    Returns:
        List of company dicts with keys: company_name, company_name_en,
        registration_number, registration_date, company_type, stated_purpose,
        directors.

    NOTE: The API returns Hebrew data. Company names and purposes will be in Hebrew.
    """
    if since_date is None:
        since_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    all_records = []
    offset = 0
    limit = 100

    while True:
        params = {
            "resource_id": RESOURCE_ID,
            "limit": limit,
            "offset": offset,
            # CKAN datastore_search supports SQL-like filters via 'q' for full-text
            # or 'filters' for exact match. For date range we use the SQL interface.
        }
        # Use datastore_search_sql for date filtering when possible.
        # Fall back to fetching all and filtering client-side if the resource
        # does not support SQL (some resources on data.gov.il restrict it).
        result = _api_request(params)
        if result is None:
            break

        records = result.get("records", [])
        if not records:
            break

        for rec in records:
            reg_date = _extract_date(rec)
            if reg_date and reg_date >= since_date:
                all_records.append(_normalize_record(rec))
            elif reg_date and reg_date < since_date:
                # Records are generally ordered by date; if we hit old ones
                # we may still have newer ones mixed in, so continue but track.
                pass

        # Check if there are more pages
        total = result.get("total", 0)
        offset += limit
        if offset >= total:
            break

        # Safety cap to avoid runaway pagination
        if offset >= 50000:
            logger.warning("Reached pagination cap of 50000 records (total=%d)", total)
            break

    return all_records


def _extract_date(record):
    """Extract registration date from a raw API record.

    The field name varies between data.gov.il snapshots. Try common field names.

    Returns:
        ISO date string (YYYY-MM-DD) or None.
    """
    date_fields = [
        "registration_date",
        "תאריך_התאגדות",
        "תאריך התאגדות",
        "date_registered",
    ]
    for field in date_fields:
        val = record.get(field)
        if val:
            return _parse_date_flexible(str(val))
    return None


def _parse_date_flexible(text):
    """Parse a date string in various formats to YYYY-MM-DD.

    Handles: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DDTHH:MM:SS.
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # ISO format with optional time
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.match(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"

    return None


def _normalize_record(record):
    """Convert a raw API record into a standardized dict.

    Tries multiple field name variants since the data.gov.il schema can change.
    """
    def _get(keys, default=None):
        for k in keys:
            if k in record and record[k]:
                return str(record[k]).strip()
        return default

    company_name = _get([
        "company_name", "שם_חברה", "שם חברה", "company_name_hebrew",
    ], "")

    company_name_en = _get([
        "company_name_en", "company_name_english", "שם_באנגלית", "שם באנגלית",
    ])

    registration_number = _get([
        "registration_number", "company_number", "מספר_חברה", "מספר חברה",
    ], "")

    registration_date = _extract_date(record)

    company_type = _get([
        "company_type", "סוג_חברה", "סוג חברה", "type",
    ])

    stated_purpose = _get([
        "stated_purpose", "מטרת_החברה", "מטרת החברה", "purpose", "goal",
    ])

    # Directors may be in a separate field or require a follow-up API call
    directors_raw = _get([
        "directors", "בעלי_תפקידים", "בעלי תפקידים",
    ])
    directors = []
    if directors_raw:
        # May be JSON array or comma-separated string
        try:
            directors = json.loads(directors_raw)
        except (json.JSONDecodeError, TypeError):
            directors = [d.strip() for d in directors_raw.split(",") if d.strip()]

    return {
        "company_name": company_name,
        "company_name_en": company_name_en,
        "registration_number": registration_number,
        "registration_date": registration_date,
        "company_type": company_type,
        "stated_purpose": stated_purpose,
        "directors": directors,
    }


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def match_against_watchlist(registration, watchlist_names):
    """Check if any director/shareholder name matches the watchlist.

    Args:
        registration: dict with a 'directors' list of name strings.
        watchlist_names: list of name strings to match against.

    Uses fuzzy name matching since the registrar uses Hebrew names and the
    watchlist may have English transliterations. We normalize and compare
    tokens to handle ordering differences (e.g. "Cohen Yosef" vs "Yosef Cohen").

    Returns:
        The matched watchlist name, or None.
    """
    if not registration.get("directors") or not watchlist_names:
        return None

    def _normalize(name):
        """Lowercase, strip diacritics/punctuation, split into token set."""
        name = name.lower().strip()
        # Remove common Hebrew prefixes and punctuation
        name = re.sub(r'["\'\-.,;:()״׳]', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return set(name.split())

    watchlist_normalized = []
    for wn in watchlist_names:
        tokens = _normalize(wn)
        if tokens:
            watchlist_normalized.append((wn, tokens))

    for director in registration["directors"]:
        director_tokens = _normalize(str(director))
        if not director_tokens:
            continue

        for original_name, wl_tokens in watchlist_normalized:
            # Match if all tokens of the shorter name appear in the longer name.
            # This handles "Yosef Cohen" matching "Cohen Yosef" and also partial
            # matches like "Yosef" matching "Yosef Cohen" if the watchlist entry
            # is a single name (though that would be noisy — callers should use
            # full names).
            shorter, longer = (
                (wl_tokens, director_tokens)
                if len(wl_tokens) <= len(director_tokens)
                else (director_tokens, wl_tokens)
            )
            # Require at least 2 tokens to match, or all tokens if name has only 1
            if len(shorter) == 1:
                if shorter.issubset(longer) and len(longer) <= 2:
                    return original_name
            elif shorter.issubset(longer):
                return original_name

    return None


def is_tech_company(stated_purpose):
    """Check if company purpose suggests a tech/startup.

    Checks both Hebrew and English keywords against the stated purpose.

    Args:
        stated_purpose: Company's stated purpose string (may be Hebrew or English).

    Returns:
        True if tech keywords found, False otherwise.
    """
    if not stated_purpose:
        return False

    if _EN_PATTERN.search(stated_purpose):
        return True
    if _HE_PATTERN.search(stated_purpose):
        return True

    return False


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def _get_last_scan_date(conn):
    """Get the most recent registration date we've stored.

    Returns ISO date string or None.
    """
    row = conn.execute(
        "SELECT MAX(registration_date) FROM company_registrations"
    ).fetchone()
    if row and row[0]:
        return row[0]
    return None


def _store_registration(conn, reg, matched_person_id=None, signal_level=None):
    """Insert a company registration into the DB. Skips duplicates by registration_number."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    try:
        conn.execute(
            """INSERT OR IGNORE INTO company_registrations
               (company_name, company_name_en, registration_number, registration_date,
                company_type, stated_purpose, directors, matched_person_id,
                signal_level, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                reg.get("company_name", ""),
                reg.get("company_name_en"),
                reg.get("registration_number", ""),
                reg.get("registration_date"),
                reg.get("company_type"),
                reg.get("stated_purpose"),
                json.dumps(reg.get("directors", []), ensure_ascii=False),
                matched_person_id,
                signal_level,
                now,
            ),
        )
    except Exception as e:
        logger.error("Failed to store registration %s: %s",
                     reg.get("registration_number"), e)


def scan_registrar(conn, watchlist_people):
    """Main scan function for company registrar monitoring.

    1. Get last scan date from DB (or default to 24h ago)
    2. Fetch new registrations since then
    3. For each: check watchlist name match + tech keywords
    4. Store in DB
    5. Return list of signals

    Args:
        conn: SQLite connection (with company_registrations table initialized).
        watchlist_people: list of dicts with at least 'id' and 'name' keys.

    Returns:
        List of signal dicts:
        [{
            type: 'company_registration',
            tier: 'high' | 'medium' | 'low',
            description: str,
            registration_number: str,
            company_name: str,
            matched_person: str or None,
        }, ...]
    """
    # Determine scan window
    last_scan = _get_last_scan_date(conn)
    if last_scan:
        since_date = last_scan
    else:
        since_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info("Scanning registrar for companies registered since %s", since_date)

    # Build watchlist name lookup
    watchlist_names = [p["name"] for p in watchlist_people if p.get("name")]
    watchlist_by_name = {}
    for p in watchlist_people:
        if p.get("name"):
            watchlist_by_name[p["name"]] = p.get("id")

    # Fetch and process
    registrations = fetch_recent_registrations(since_date)
    logger.info("Fetched %d new registrations", len(registrations))

    signals = []

    for reg in registrations:
        matched_name = match_against_watchlist(reg, watchlist_names)
        tech = is_tech_company(reg.get("stated_purpose"))
        matched_person_id = None

        if matched_name:
            # Watchlist match — HIGH tier
            matched_person_id = watchlist_by_name.get(matched_name)
            tier = "high"
            company_display = reg.get("company_name_en") or reg.get("company_name", "")
            desc = (
                f"Watchlist match: {matched_name} is a director of newly registered "
                f"company '{company_display}' (#{reg.get('registration_number')})"
            )
            if tech:
                desc += " [tech keywords detected in purpose]"
        elif tech:
            # Tech company without watchlist match — MEDIUM tier
            tier = "medium"
            company_display = reg.get("company_name_en") or reg.get("company_name", "")
            purpose_snippet = (reg.get("stated_purpose") or "")[:120]
            desc = (
                f"New tech company registered: '{company_display}' "
                f"(#{reg.get('registration_number')}). "
                f"Purpose: {purpose_snippet}"
            )
        else:
            # No match, no tech keywords — store but don't signal
            _store_registration(conn, reg)
            continue

        signal_level = tier
        _store_registration(conn, reg, matched_person_id, signal_level)

        signals.append({
            "type": "company_registration",
            "tier": tier,
            "description": desc,
            "registration_number": reg.get("registration_number", ""),
            "company_name": reg.get("company_name", ""),
            "matched_person": matched_name,
        })

    conn.commit()
    logger.info("Registrar scan complete: %d signals generated", len(signals))
    return signals
