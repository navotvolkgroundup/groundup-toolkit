"""
Retention Clock — Tracks founders whose startups were acquired and whose
retention/vesting period is nearing completion.

When a startup gets acquired, founders typically stay for 2-4 years of vesting.
This module monitors those timelines so GroundUp can reach out when founders
are about to become free agents — prime time for starting a new company.

Data sources:
- Brave Search API (passed as a function parameter to stay decoupled)
- Manual additions via add_acquisition / add_acquisition_founder

Vesting windows from acquisition date:
  Optimistic: +2 years
  Typical:    +3 years
  Conservative: +4 years

Status classifications:
  FAR:         >12 months to typical vesting end
  APPROACHING: 6-12 months
  IMMINENT:    0-6 months
  EXPIRED:     past typical vesting end
"""

import re
import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VEST_YEARS_OPTIMISTIC = 2
VEST_YEARS_TYPICAL = 3
VEST_YEARS_CONSERVATIVE = 4

STATUS_FAR = "FAR"
STATUS_APPROACHING = "APPROACHING"
STATUS_IMMINENT = "IMMINENT"
STATUS_EXPIRED = "EXPIRED"

# Search queries for finding Israeli startup acquisitions
ACQUISITION_SEARCH_QUERIES = [
    "Israeli startup acquired {year}",
    "Israel tech acquisition {year}",
    "Israeli company bought by {year}",
    "Israel startup acquisition deal {year}",
]

# Patterns for extracting acquisition details from search results
_ACQUIRED_BY_PATTERN = re.compile(
    r"(?i)(.+?)\s+(?:acquired|bought|purchased)\s+(?:by\s+)?(.+?)(?:\s+for\s+\$?([\d,.]+\s*[BMK]?))?",
)
_ACQUIRER_ACQUIRES_PATTERN = re.compile(
    r"(?i)(.+?)\s+(?:acquires?|buys?|purchases?)\s+(.+?)(?:\s+for\s+\$?([\d,.]+\s*[BMK]?))?",
)

# Month name mapping for date parsing
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

CREATE_ACQUISITIONS = """
CREATE TABLE IF NOT EXISTS acquisitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquired_company TEXT NOT NULL,
    acquiring_company TEXT NOT NULL,
    acquisition_date TEXT,
    deal_size TEXT,
    sector TEXT,
    source_url TEXT,
    created_at TEXT NOT NULL
)
"""

CREATE_ACQUISITION_FOUNDERS = """
CREATE TABLE IF NOT EXISTS acquisition_founders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_id INTEGER REFERENCES acquisitions(id),
    founder_name TEXT NOT NULL,
    founder_linkedin_url TEXT,
    role_at_acquired TEXT,
    vest_end_optimistic TEXT,
    vest_end_typical TEXT,
    vest_end_conservative TEXT,
    current_status TEXT DEFAULT 'FAR',
    last_checked TEXT,
    notes TEXT
)
"""


def init_retention_tables(conn):
    """Create acquisitions and acquisition_founders tables."""
    conn.execute(CREATE_ACQUISITIONS)
    conn.execute(CREATE_ACQUISITION_FOUNDERS)
    conn.commit()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_acquisition_date(text):
    """Parse a date from news articles / search results into YYYY-MM-DD.

    Handles various formats:
        "January 2023"      -> 2023-01-15
        "Jan 2023"          -> 2023-01-15
        "Q3 2022"           -> 2022-07-15
        "2023"              -> 2023-07-01
        "early 2024"        -> 2024-03-01
        "mid 2024"          -> 2024-06-15
        "late 2024"         -> 2024-10-01
        "2023-05-15"        -> 2023-05-15
        "May 15, 2023"      -> 2023-05-15
        "15 May 2023"       -> 2023-05-15

    Returns:
        ISO date string (YYYY-MM-DD) or None.
    """
    if not text:
        return None

    text = text.strip()

    # ISO format: YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # "Month DD, YYYY" or "Month YYYY"
    m = re.match(
        r"(?i)^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", text
    )
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"

    m = re.match(r"(?i)^([A-Za-z]+)\s+(\d{4})$", text)
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        if month:
            return f"{m.group(2)}-{month:02d}-15"

    # "DD Month YYYY"
    m = re.match(r"(?i)^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", text)
    if m:
        month = _MONTH_MAP.get(m.group(2).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"

    # Quarter: "Q1 2023", "Q3 2022"
    m = re.match(r"(?i)^Q([1-4])\s+(\d{4})$", text)
    if m:
        quarter = int(m.group(1))
        month = (quarter - 1) * 3 + 1  # Q1->1, Q2->4, Q3->7, Q4->10
        return f"{m.group(2)}-{month:02d}-15"

    # "early/mid/late YYYY"
    m = re.match(r"(?i)^(early|mid|late|end\s+of|beginning\s+of)\s+(\d{4})$", text)
    if m:
        qualifier = m.group(1).lower()
        year = m.group(2)
        if qualifier in ("early", "beginning of"):
            return f"{year}-03-01"
        elif qualifier == "mid":
            return f"{year}-06-15"
        else:  # late, end of
            return f"{year}-10-01"

    # Bare year: "2023"
    m = re.match(r"^(\d{4})$", text)
    if m:
        return f"{m.group(1)}-07-01"

    return None


def _extract_date_from_text(text):
    """Try to find and parse a date from a longer text string.

    Searches for date-like patterns within the text.

    Returns:
        ISO date string or None.
    """
    if not text:
        return None

    # Try full text first (in case it's already a date)
    direct = _parse_acquisition_date(text)
    if direct:
        return direct

    # Look for patterns within the text
    patterns = [
        # "in January 2023", "in Q3 2022"
        r"(?i)in\s+((?:Q[1-4]\s+)?\d{4})",
        r"(?i)in\s+([A-Za-z]+\s+\d{4})",
        r"(?i)in\s+(early|mid|late)\s+(\d{4})",
        # "on May 15, 2023"
        r"(?i)on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        # Standalone date patterns
        r"(\d{4}-\d{1,2}-\d{1,2})",
        r"(?i)([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        r"(?i)([A-Za-z]+\s+\d{4})",
        r"(?i)(Q[1-4]\s+\d{4})",
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if m:
            # For the "early/mid/late" pattern, reconstruct the string
            if m.lastindex and m.lastindex >= 2:
                candidate = f"{m.group(1)} {m.group(2)}"
            else:
                candidate = m.group(1)
            result = _parse_acquisition_date(candidate.strip())
            if result:
                return result

    return None


# ---------------------------------------------------------------------------
# Vesting calculations
# ---------------------------------------------------------------------------

def _add_years(date_str, years):
    """Add years to an ISO date string. Returns ISO date string."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        result = dt.replace(year=dt.year + years)
    except ValueError:
        # Handle Feb 29 -> Feb 28 when target year is not a leap year
        result = dt.replace(year=dt.year + years, day=28)
    return result.strftime("%Y-%m-%d")


def _calculate_vesting_windows(acquisition_date):
    """Calculate optimistic, typical, and conservative vesting end dates.

    Args:
        acquisition_date: ISO date string (YYYY-MM-DD).

    Returns:
        Tuple of (optimistic, typical, conservative) ISO date strings,
        or (None, None, None) if date is invalid.
    """
    if not acquisition_date:
        return None, None, None

    try:
        # Validate the date
        datetime.strptime(acquisition_date, "%Y-%m-%d")
    except ValueError:
        return None, None, None

    return (
        _add_years(acquisition_date, VEST_YEARS_OPTIMISTIC),
        _add_years(acquisition_date, VEST_YEARS_TYPICAL),
        _add_years(acquisition_date, VEST_YEARS_CONSERVATIVE),
    )


def calculate_retention_status(vest_end_typical):
    """Calculate current retention status based on typical vesting end date.

    Args:
        vest_end_typical: ISO date string (YYYY-MM-DD) for the typical vesting end.

    Returns:
        One of: FAR, APPROACHING, IMMINENT, EXPIRED.
    """
    if not vest_end_typical:
        return STATUS_FAR

    try:
        end_date = datetime.strptime(vest_end_typical, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return STATUS_FAR

    now = datetime.now(timezone.utc)
    months_remaining = (end_date - now).days / 30.44  # average days per month

    if months_remaining < 0:
        return STATUS_EXPIRED
    elif months_remaining <= 6:
        return STATUS_IMMINENT
    elif months_remaining <= 12:
        return STATUS_APPROACHING
    else:
        return STATUS_FAR


# ---------------------------------------------------------------------------
# Search and parsing
# ---------------------------------------------------------------------------

def parse_acquisition_from_search(title, description, url):
    """Try to extract acquisition details from a search result.

    Args:
        title: Search result title.
        description: Search result description/snippet.
        url: Source URL.

    Returns:
        Dict with {acquired_company, acquiring_company, acquisition_date,
        deal_size, sector} or None if extraction fails.
    """
    if not title and not description:
        return None

    combined = f"{title or ''} {description or ''}"
    acquired = None
    acquirer = None
    deal_size = None

    # Try "X acquires Y" pattern
    m = _ACQUIRER_ACQUIRES_PATTERN.search(combined)
    if m:
        acquirer = _clean_company_name(m.group(1))
        acquired = _clean_company_name(m.group(2))
        deal_size = m.group(3) if m.lastindex >= 3 else None

    # Try "X acquired by Y" pattern
    if not acquired:
        m = _ACQUIRED_BY_PATTERN.search(combined)
        if m:
            acquired = _clean_company_name(m.group(1))
            acquirer = _clean_company_name(m.group(2))
            deal_size = m.group(3) if m.lastindex >= 3 else None

    # Look for "$X billion/million" deal size if not found yet
    if not deal_size:
        m = re.search(r"\$\s*([\d,.]+)\s*(billion|million|B|M)\b", combined, re.IGNORECASE)
        if m:
            deal_size = f"${m.group(1)} {m.group(2)}"

    if not acquired or not acquirer:
        return None

    # Skip if names are too generic or clearly not company names
    if len(acquired) < 2 or len(acquirer) < 2:
        return None

    # Try to extract date
    acquisition_date = _extract_date_from_text(combined)

    # Infer sector from keywords
    sector = _infer_sector(combined)

    return {
        "acquired_company": acquired,
        "acquiring_company": acquirer,
        "acquisition_date": acquisition_date,
        "deal_size": deal_size,
        "sector": sector,
        "source_url": url,
    }


def _clean_company_name(name):
    """Clean up a company name extracted from text."""
    if not name:
        return name
    # Remove leading/trailing punctuation and common noise words
    name = name.strip(" \t\n\r\"'.,;:-")
    # Remove trailing qualifiers
    name = re.sub(r"\s*(?:Inc\.?|Ltd\.?|Corp\.?|LLC|Co\.?)$", "", name, flags=re.IGNORECASE)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Cap length to avoid capturing entire sentences
    if len(name) > 60:
        return None
    return name


def _infer_sector(text):
    """Infer the sector from text content."""
    text_lower = text.lower()
    sector_keywords = {
        "cybersecurity": ["cyber", "security", "infosec", "firewall", "endpoint"],
        "fintech": ["fintech", "financial", "banking", "payment", "insurance"],
        "healthtech": ["health", "medical", "clinical", "pharma", "biotech", "medtech"],
        "AI/ML": ["artificial intelligence", "machine learning", " ai ", "deep learning", "nlp"],
        "cloud": ["cloud", "infrastructure", "devops", "kubernetes", "saas"],
        "data": ["data", "analytics", "big data", "database"],
        "automotive": ["automotive", "autonomous", "self-driving", "mobility"],
        "enterprise": ["enterprise", "b2b", "workflow", "collaboration"],
        "consumer": ["consumer", "social", "gaming", "e-commerce", "marketplace"],
    }
    for sector, keywords in sector_keywords.items():
        for kw in keywords:
            if kw in text_lower:
                return sector
    return None


def search_acquisitions(brave_search_fn, since_year=2021):
    """Use Brave Search to find Israeli startup acquisitions.

    Args:
        brave_search_fn: Callable that takes a query string and returns search
            results. Expected to return a list of dicts with 'title',
            'description', and 'url' keys (matching lib.brave.brave_search).
        since_year: Search from this year onwards (default 2021).

    Returns:
        List of acquisition dicts (deduplicated by acquired company name).
    """
    seen_companies = set()
    acquisitions = []
    current_year = datetime.now().year

    for year in range(since_year, current_year + 1):
        for query_template in ACQUISITION_SEARCH_QUERIES:
            query = query_template.format(year=year)
            try:
                results = brave_search_fn(query)
            except Exception as e:
                logger.error("Brave search failed for '%s': %s", query, e)
                continue

            if not results:
                continue

            for result in results:
                title = result.get("title", "")
                description = result.get("description", "")
                url = result.get("url", "")

                parsed = parse_acquisition_from_search(title, description, url)
                if not parsed:
                    continue

                # Deduplicate by acquired company (case-insensitive)
                key = parsed["acquired_company"].lower()
                if key in seen_companies:
                    continue
                seen_companies.add(key)
                acquisitions.append(parsed)

    logger.info("Found %d unique acquisitions via search", len(acquisitions))
    return acquisitions


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def add_acquisition(conn, acquired, acquirer, date, deal_size=None,
                    sector=None, source_url=None):
    """Store an acquisition record.

    Args:
        conn: SQLite connection.
        acquired: Name of the acquired company.
        acquirer: Name of the acquiring company.
        date: Acquisition date (ISO string, flexible format, or None).
        deal_size: Optional deal size string (e.g. "$1.5 billion").
        sector: Optional sector string.
        source_url: Optional URL to the news source.

    Returns:
        acquisition_id (int).
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Normalize the date
    parsed_date = _parse_acquisition_date(str(date)) if date else None

    # Check for existing record (same acquired + acquirer)
    existing = conn.execute(
        "SELECT id FROM acquisitions WHERE LOWER(acquired_company) = ? AND LOWER(acquiring_company) = ?",
        (acquired.lower(), acquirer.lower()),
    ).fetchone()

    if existing:
        # Update if we have new info
        if parsed_date or deal_size or sector:
            updates = []
            params = []
            if parsed_date:
                updates.append("acquisition_date = ?")
                params.append(parsed_date)
            if deal_size:
                updates.append("deal_size = ?")
                params.append(deal_size)
            if sector:
                updates.append("sector = ?")
                params.append(sector)
            if source_url:
                updates.append("source_url = ?")
                params.append(source_url)
            if updates:
                params.append(existing[0])
                conn.execute(
                    f"UPDATE acquisitions SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                conn.commit()
        return existing[0]

    cur = conn.execute(
        """INSERT INTO acquisitions
           (acquired_company, acquiring_company, acquisition_date, deal_size,
            sector, source_url, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (acquired, acquirer, parsed_date, deal_size, sector, source_url, now),
    )
    conn.commit()
    return cur.lastrowid


def add_acquisition_founder(conn, acquisition_id, name, linkedin_url=None, role=None):
    """Add a founder to an acquisition record and calculate vesting windows.

    Args:
        conn: SQLite connection.
        acquisition_id: FK to acquisitions.id.
        name: Founder's full name.
        linkedin_url: Optional LinkedIn profile URL.
        role: Optional role at the acquired company (e.g. "CEO", "CTO").

    Returns:
        founder record id (int).
    """
    # Look up the acquisition date
    row = conn.execute(
        "SELECT acquisition_date FROM acquisitions WHERE id = ?",
        (acquisition_id,),
    ).fetchone()

    acq_date = row[0] if row else None
    vest_opt, vest_typ, vest_con = _calculate_vesting_windows(acq_date)
    status = calculate_retention_status(vest_typ)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Check for existing founder on this acquisition
    existing = conn.execute(
        "SELECT id FROM acquisition_founders WHERE acquisition_id = ? AND LOWER(founder_name) = ?",
        (acquisition_id, name.lower()),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE acquisition_founders
               SET founder_linkedin_url = COALESCE(?, founder_linkedin_url),
                   role_at_acquired = COALESCE(?, role_at_acquired),
                   vest_end_optimistic = ?, vest_end_typical = ?,
                   vest_end_conservative = ?, current_status = ?,
                   last_checked = ?
               WHERE id = ?""",
            (linkedin_url, role, vest_opt, vest_typ, vest_con, status, now,
             existing[0]),
        )
        conn.commit()
        return existing[0]

    cur = conn.execute(
        """INSERT INTO acquisition_founders
           (acquisition_id, founder_name, founder_linkedin_url, role_at_acquired,
            vest_end_optimistic, vest_end_typical, vest_end_conservative,
            current_status, last_checked)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (acquisition_id, name, linkedin_url, role,
         vest_opt, vest_typ, vest_con, status, now),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Status management
# ---------------------------------------------------------------------------

def update_all_statuses(conn):
    """Recalculate retention status for all founders.

    Returns:
        List of status change dicts:
        [{founder_name, acquisition, old_status, new_status}, ...]
    """
    rows = conn.execute(
        """SELECT af.id, af.founder_name, af.vest_end_typical, af.current_status,
                  a.acquired_company
           FROM acquisition_founders af
           JOIN acquisitions a ON a.id = af.acquisition_id"""
    ).fetchall()

    changes = []
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for row in rows:
        founder_id, name, vest_end, old_status, company = row
        new_status = calculate_retention_status(vest_end)

        if new_status != old_status:
            conn.execute(
                "UPDATE acquisition_founders SET current_status = ?, last_checked = ? WHERE id = ?",
                (new_status, now, founder_id),
            )
            changes.append({
                "founder_name": name,
                "acquisition": company,
                "old_status": old_status,
                "new_status": new_status,
            })
            logger.info("Status change: %s (%s) %s -> %s",
                        name, company, old_status, new_status)

    if changes:
        conn.commit()

    return changes


def get_expiring_founders(conn, status="IMMINENT"):
    """Get founders with the given retention status.

    Args:
        conn: SQLite connection.
        status: One of FAR, APPROACHING, IMMINENT, EXPIRED. Default IMMINENT.

    Returns:
        List of dicts with founder and acquisition details.
    """
    rows = conn.execute(
        """SELECT af.founder_name, af.founder_linkedin_url, af.role_at_acquired,
                  af.vest_end_optimistic, af.vest_end_typical, af.vest_end_conservative,
                  af.current_status, af.notes,
                  a.acquired_company, a.acquiring_company, a.acquisition_date,
                  a.deal_size, a.sector
           FROM acquisition_founders af
           JOIN acquisitions a ON a.id = af.acquisition_id
           WHERE af.current_status = ?
           ORDER BY af.vest_end_typical ASC""",
        (status,),
    ).fetchall()

    columns = [
        "founder_name", "linkedin_url", "role", "vest_optimistic",
        "vest_typical", "vest_conservative", "status", "notes",
        "acquired_company", "acquiring_company", "acquisition_date",
        "deal_size", "sector",
    ]
    return [dict(zip(columns, row)) for row in rows]


def get_approaching_founders(conn):
    """Get founders with APPROACHING or IMMINENT status.

    Returns:
        List of dicts with founder and acquisition details, sorted by
        vest_end_typical ascending (soonest first).
    """
    rows = conn.execute(
        """SELECT af.founder_name, af.founder_linkedin_url, af.role_at_acquired,
                  af.vest_end_optimistic, af.vest_end_typical, af.vest_end_conservative,
                  af.current_status, af.notes,
                  a.acquired_company, a.acquiring_company, a.acquisition_date,
                  a.deal_size, a.sector
           FROM acquisition_founders af
           JOIN acquisitions a ON a.id = af.acquisition_id
           WHERE af.current_status IN ('APPROACHING', 'IMMINENT')
           ORDER BY af.vest_end_typical ASC""",
    ).fetchall()

    columns = [
        "founder_name", "linkedin_url", "role", "vest_optimistic",
        "vest_typical", "vest_conservative", "status", "notes",
        "acquired_company", "acquiring_company", "acquisition_date",
        "deal_size", "sector",
    ]
    return [dict(zip(columns, row)) for row in rows]


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def scan_for_acquisitions(conn, brave_search_fn):
    """Monthly scan: search for new acquisitions and store them.

    Args:
        conn: SQLite connection (with tables initialized).
        brave_search_fn: Callable matching lib.brave.brave_search signature.

    Returns:
        Count of new acquisitions found and stored.
    """
    acquisitions = search_acquisitions(brave_search_fn)
    new_count = 0

    for acq in acquisitions:
        # Check if we already have this acquisition
        existing = conn.execute(
            "SELECT id FROM acquisitions WHERE LOWER(acquired_company) = ?",
            (acq["acquired_company"].lower(),),
        ).fetchone()

        if existing:
            continue

        acq_id = add_acquisition(
            conn,
            acquired=acq["acquired_company"],
            acquirer=acq["acquiring_company"],
            date=acq.get("acquisition_date"),
            deal_size=acq.get("deal_size"),
            sector=acq.get("sector"),
            source_url=acq.get("source_url"),
        )
        new_count += 1
        logger.info("New acquisition: %s by %s (id=%d)",
                     acq["acquired_company"], acq["acquiring_company"], acq_id)

    # Update statuses for all tracked founders
    changes = update_all_statuses(conn)
    if changes:
        logger.info("%d founder status changes detected", len(changes))

    return new_count
