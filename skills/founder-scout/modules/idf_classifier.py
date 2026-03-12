"""
IDF Unit Classifier — Infers Israeli founders' likely military unit background
from LinkedIn profile text using weighted signal analysis.

Designed for GroundUp Ventures' Founder Scout pipeline. Self-contained module:
receives profile text and sqlite3 connections from the caller (scout.py).
"""

import re
import json
from datetime import datetime


# ---------------------------------------------------------------------------
# Confidence levels
# ---------------------------------------------------------------------------

CONFIDENCE_CONFIRMED = "CONFIRMED"       # 100+
CONFIDENCE_HIGHLY_LIKELY = "HIGHLY_LIKELY"  # 70-99
CONFIDENCE_PROBABLE = "PROBABLE"          # 40-69
CONFIDENCE_POSSIBLE = "POSSIBLE"          # 20-39
CONFIDENCE_UNKNOWN = "UNKNOWN"            # <20


def _confidence_level(score):
    if score >= 100:
        return CONFIDENCE_CONFIRMED
    elif score >= 70:
        return CONFIDENCE_HIGHLY_LIKELY
    elif score >= 40:
        return CONFIDENCE_PROBABLE
    elif score >= 20:
        return CONFIDENCE_POSSIBLE
    return CONFIDENCE_UNKNOWN


# ---------------------------------------------------------------------------
# Unit name patterns (English + Hebrew transliterations)
# ---------------------------------------------------------------------------

# Each entry: (unit_key, compiled_regex)
# Patterns are case-insensitive and use word boundaries where appropriate.

UNIT_DIRECT_PATTERNS = [
    # Unit 8200
    ("8200", re.compile(
        r"(?i)\b(?:"
        r"8200|8[\-\s]?200|unit\s*8200|יחידה\s*8200"
        r"|שמונה\s*מאתיים|שמונה[\-\s]מאתיים"
        r"|eight\s*two\s*hundred"
        r")\b"
    )),
    # Talpiot
    ("Talpiot", re.compile(
        r"(?i)\b(?:"
        r"talpiot|talpiott|talpiyot"
        r"|טלפיות|תלפיות|תלפיו[תט]"
        r"|idf\s+talpiot|talpiot\s+program"
        r")\b"
    )),
    # Unit 81
    ("Unit 81", re.compile(
        r"(?i)\b(?:"
        r"unit\s*81|יחידה\s*81"
        r"|שמונים\s*ואח[תד]"
        r")\b"
    )),
    # Mamram
    ("Mamram", re.compile(
        r"(?i)\b(?:"
        r"mamram|mamr[ae]m"
        r"|ממר[\"״]ם|ממרם"
        r"|מרכז\s*מחשבים"
        r"|center\s*of\s*computing"
        r"|idf\s+computing"
        r")\b"
    )),
    # Ofek
    ("Ofek", re.compile(
        r"(?i)\b(?:"
        r"unit\s+ofek|ofek\s+unit|ofek\s+intelligence"
        r"|יחידת\s*אופק|אופק"
        r")\b"
    )),
    # Matzov (cyber defense)
    ("Matzov", re.compile(
        r"(?i)\b(?:"
        r"matzov|matz[oa]v"
        r"|מצו[\"״]?ב|מצוב"
        r"|cyber\s+defense\s+unit"
        r")\b"
    )),
    # Lotem (C4I)
    ("Lotem", re.compile(
        r"(?i)\b(?:"
        r"lotem\b|unit\s+lotem|lotem\s+c4i"
        r"|לוטם"
        r"|c4i\s+lotem"
        r")"
    )),
]

# Indirect / vague military mentions that suggest intelligence/tech units
INDIRECT_PATTERNS = [
    re.compile(r"(?i)\bidf\s*[-–—]\s*intelligence\s+corps\b"),
    re.compile(r"(?i)\bidf\s*[-–—]\s*technology\s+unit\b"),
    re.compile(r"(?i)\bidf\s*[-–—]\s*special\s+unit\b"),
    re.compile(r"(?i)\bidf\s*[-–—]\s*classified\s+unit\b"),
    re.compile(r"(?i)\bisraeli\s+intelligence\b"),
    re.compile(r"(?i)\bisrael\s+defense\s+forces?\s*[-–—]\s*intelligence\b"),
    re.compile(r"(?i)\bisraeli\s+military\s+intelligence\b"),
    re.compile(r"(?i)\baman\b.*\bidf\b|\bidf\b.*\baman\b"),
    re.compile(r"(?i)\b(?:אמ[\"״]?ן|אגף\s*המודיעין)\b"),
    re.compile(r"(?i)\bidf\s*[-–—]\s*c4i\b"),
    re.compile(r"(?i)\bidf\s*[-–—]\s*cyber\b"),
]

# Alumni event / reunion patterns
ALUMNI_PATTERNS = [
    re.compile(r"(?i)\b(?:8200|talpiot|mamram|unit\s*81)\s+alumni\b"),
    re.compile(r"(?i)\balumni\s+(?:of\s+)?(?:8200|talpiot|mamram|unit\s*81)\b"),
    re.compile(r"(?i)\breunion\b.*\b(?:8200|talpiot|mamram|unit\s*81)\b"),
    re.compile(r"(?i)\b(?:8200|talpiot|mamram)\s+(?:reunion|gathering|event|meetup)\b"),
    re.compile(r"(?i)\b(?:8200|talpiot)\s+(?:graduates?|cohort|class\s+of)\b"),
]


# ---------------------------------------------------------------------------
# Known alumni-heavy companies per unit
# ---------------------------------------------------------------------------

UNIT_COMPANY_MAP = {
    "8200": [
        ("Check Point", "strong"),
        ("NSO Group", "strong"),
        ("Palo Alto Networks", "strong"),
        ("CyberArk", "strong"),
        ("Team8", "strong"),
        ("Wiz", "strong"),
        ("Orca Security", "strong"),
        ("Pentera", "strong"),
        ("Cybereason", "strong"),
        ("SentinelOne", "strong"),
        ("Armis", "strong"),
        ("Hunters", "moderate"),
        ("Axonius", "moderate"),
        ("Argus Cyber Security", "moderate"),
        ("Cato Networks", "moderate"),
        ("Claroty", "moderate"),
        ("Silverfort", "moderate"),
        ("Salt Security", "moderate"),
        ("Perimeter 81", "moderate"),
        ("Imperva", "moderate"),
        ("XM Cyber", "moderate"),
        ("Medigate", "weak"),
        ("Illusive Networks", "weak"),
        ("Deep Instinct", "weak"),
        ("Aqua Security", "weak"),
    ],
    "Talpiot": [
        ("Mobileye", "strong"),
        ("OrCam", "strong"),
        ("Lightricks", "strong"),
        ("Windward", "strong"),
        ("ironSource", "strong"),
        ("Iguazio", "strong"),
        ("Run:AI", "strong"),
        ("Hailo", "strong"),
        ("Innoviz", "moderate"),
        ("Anodot", "moderate"),
        ("Sight Diagnostics", "moderate"),
        ("CEVA", "moderate"),
        ("Applied Materials Israel", "moderate"),
        ("StoreDot", "moderate"),
        ("BreezoMeter", "weak"),
        ("Wiliot", "weak"),
    ],
    "Unit 81": [
        ("Rafael Advanced Defense Systems", "strong"),
        ("Elbit Systems", "strong"),
        ("IAI", "strong"),
        ("Israel Aerospace Industries", "strong"),
        ("Elisra", "moderate"),
        ("ELTA Systems", "moderate"),
        ("BIRD Aerosystems", "moderate"),
        ("DSIT Solutions", "moderate"),
        ("Magal Security Systems", "moderate"),
        ("Controp", "moderate"),
        ("Eltics", "weak"),
        ("Opgal", "weak"),
    ],
    "Mamram": [
        ("Amdocs", "strong"),
        ("NICE Systems", "strong"),
        ("SAP Israel", "moderate"),
        ("Microsoft Israel", "moderate"),
        ("IBM Israel", "moderate"),
        ("Matrix IT", "moderate"),
        ("Sapiens", "moderate"),
        ("Comverse", "moderate"),
        ("Verint", "moderate"),
        ("Gilat Satellite", "moderate"),
        ("AudioCodes", "moderate"),
        ("Ceragon", "weak"),
        ("Allot", "weak"),
        ("Radcom", "weak"),
    ],
    "Ofek": [
        ("Verint", "moderate"),
        ("Cellebrite", "moderate"),
        ("Cognyte", "moderate"),
        ("Mer Group", "moderate"),
        ("Elbit Systems", "weak"),
        ("NICE Systems", "weak"),
    ],
    "Matzov": [
        ("Check Point", "moderate"),
        ("CyberArk", "moderate"),
        ("Checkpoint", "moderate"),
        ("Israel National Cyber Directorate", "strong"),
        ("INCB", "moderate"),
        ("Rafael Cyber", "moderate"),
    ],
    "Lotem": [
        ("Elbit C4I", "strong"),
        ("Rafael C4I", "moderate"),
        ("IAI Elta", "moderate"),
        ("Motorola Solutions Israel", "moderate"),
        ("Elisra", "weak"),
        ("Tadiran", "weak"),
    ],
}

# Flatten company -> [(unit, strength)] for fast lookup
_COMPANY_UNIT_LOOKUP = {}
for _unit, _companies in UNIT_COMPANY_MAP.items():
    for _company, _strength in _companies:
        _key = _company.lower()
        if _key not in _COMPANY_UNIT_LOOKUP:
            _COMPANY_UNIT_LOOKUP[_key] = []
        _COMPANY_UNIT_LOOKUP[_key].append((_unit, _strength))


# University pipelines — (regex, likely_units)
UNIVERSITY_PIPELINES = [
    (re.compile(r"(?i)\btechnion\b.*\b(?:electrical\s+engineering|EE|computer\s+science|CS)\b"),
     ["8200", "Talpiot"]),
    (re.compile(r"(?i)\b(?:hebrew\s+university|huji)\b.*\b(?:physics|math|computer\s+science)\b"),
     ["Talpiot"]),
    (re.compile(r"(?i)\b(?:tel\s*-?\s*aviv\s+university|tau)\b.*\b(?:exact\s+sciences?|physics|math|CS|computer\s+science)\b"),
     ["8200", "Talpiot"]),
    (re.compile(r"(?i)\b(?:weizmann)\b.*\b(?:physics|math|computer\s+science)\b"),
     ["Talpiot"]),
    (re.compile(r"(?i)\btechnion\b.*\b(?:software\s+engineering|information\s+systems)\b"),
     ["Mamram"]),
    (re.compile(r"(?i)\b(?:ben[\s-]?gurion|bgu)\b.*\b(?:electrical|software|cyber)\b"),
     ["8200", "Mamram"]),
    (re.compile(r"(?i)\b(?:technion|hebrew\s+university|huji)\b.*\b(?:aero|mechanical)\b"),
     ["Unit 81"]),
]

# Known Talpiot/8200 researchers for co-authorship signal
KNOWN_RESEARCHERS = [
    re.compile(r"(?i)\b(?:nadav\s+zafrir)\b"),       # 8200 commander, Team8 founder
    re.compile(r"(?i)\b(?:ehud\s+(?:barak|schneorson))\b"),
    re.compile(r"(?i)\b(?:amos\s+malka)\b"),
    re.compile(r"(?i)\b(?:yossi\s+(?:sariel|vardi))\b"),
    re.compile(r"(?i)\b(?:amnon\s+shashua)\b"),       # Talpiot, Mobileye
    re.compile(r"(?i)\b(?:avi\s+(?:wigderson|dichter))\b"),
    re.compile(r"(?i)\b(?:tamir\s+pardo)\b"),
    re.compile(r"(?i)\b(?:guy\s+(?:luzon|billion))\b"),
]


# ---------------------------------------------------------------------------
# Signal weights
# ---------------------------------------------------------------------------

WEIGHT_DIRECT_MENTION = 100
WEIGHT_INDIRECT_MENTION = 70
WEIGHT_ALUMNI_EVENT = 60
WEIGHT_SERVICE_DATES = 40
WEIGHT_EMPLOYER_HISTORY = 35
WEIGHT_UNIVERSITY_PIPELINE = 30
WEIGHT_ACADEMIC_COPUB = 30


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------

def classify_idf_unit(profile_text, person_name=None):
    """Analyze LinkedIn profile text for IDF unit signals.

    Args:
        profile_text: Full text scraped from a LinkedIn profile.
        person_name: Optional name (currently unused, reserved for
                     cross-referencing alumni databases in the future).

    Returns:
        dict with keys:
            unit    — best-guess unit name (str or None)
            score   — aggregate confidence score (int)
            level   — one of CONFIRMED / HIGHLY_LIKELY / PROBABLE / POSSIBLE / UNKNOWN
            signals — list of dicts, each with {signal, unit, weight, detail}
    """
    if not profile_text:
        return {"unit": None, "score": 0, "level": CONFIDENCE_UNKNOWN, "signals": []}

    signals = []
    unit_scores = {}  # unit -> cumulative score

    def _add(signal_type, unit, weight, detail):
        signals.append({
            "signal": signal_type,
            "unit": unit,
            "weight": weight,
            "detail": detail,
        })
        unit_scores[unit] = unit_scores.get(unit, 0) + weight

    # 1. Direct mention (score: 100)
    for unit_key, pattern in UNIT_DIRECT_PATTERNS:
        match = pattern.search(profile_text)
        if match:
            _add("direct_mention", unit_key, WEIGHT_DIRECT_MENTION,
                 f"Profile mentions '{match.group()}' directly")

    # 2. Indirect mention (score: 70)
    for pattern in INDIRECT_PATTERNS:
        match = pattern.search(profile_text)
        if match:
            # Indirect mention doesn't pinpoint a specific unit — attribute
            # to 8200 as the most common, but lower weight.
            _add("indirect_mention", "8200", WEIGHT_INDIRECT_MENTION,
                 f"Indirect reference: '{match.group().strip()}'")
            break  # count once

    # 3. Alumni event mentions (score: 60)
    for pattern in ALUMNI_PATTERNS:
        match = pattern.search(profile_text)
        if match:
            # Determine which unit from the matched text
            text = match.group().lower()
            if "8200" in text:
                _add("alumni_event", "8200", WEIGHT_ALUMNI_EVENT, match.group().strip())
            elif "talpiot" in text:
                _add("alumni_event", "Talpiot", WEIGHT_ALUMNI_EVENT, match.group().strip())
            elif "mamram" in text:
                _add("alumni_event", "Mamram", WEIGHT_ALUMNI_EVENT, match.group().strip())
            elif "81" in text:
                _add("alumni_event", "Unit 81", WEIGHT_ALUMNI_EVENT, match.group().strip())

    # 4. Service dates pattern (score: 40)
    # Look for ~3 year military service ending around age 21, then top university
    service_pattern = re.compile(
        r"(?i)(?:idf|israel\s+defense|military|army|צה[\"״]?ל)"
        r".*?(\d{4})\s*[-–—]\s*(\d{4})"
    )
    uni_pattern = re.compile(
        r"(?i)\b(?:technion|hebrew\s+university|huji|tel\s*-?\s*aviv\s+university|tau"
        r"|weizmann|ben[\s-]?gurion|bgu|interdisciplinary\s+center|idc|reichman)"
        r"\b.*?(?:computer\s+science|CS|electrical\s+engineering|EE|physics|math)"
    )
    service_match = service_pattern.search(profile_text)
    if service_match:
        try:
            start = int(service_match.group(1))
            end = int(service_match.group(2))
            duration = end - start
            if 2 <= duration <= 5:
                if uni_pattern.search(profile_text):
                    _add("service_dates", "8200", WEIGHT_SERVICE_DATES,
                         f"{duration}-year service ({start}-{end}) followed by "
                         f"top Israeli CS/EE university")
        except (ValueError, IndexError):
            pass

    # 5. University pipeline (score: 30)
    seen_uni_units = set()
    for pattern, units in UNIVERSITY_PIPELINES:
        if pattern.search(profile_text):
            for unit in units:
                if unit not in seen_uni_units:
                    seen_uni_units.add(unit)
                    _add("university_pipeline", unit, WEIGHT_UNIVERSITY_PIPELINE,
                         f"Studied at feeder institution for {unit}")

    # 6. Employer history (score: 35)
    text_lower = profile_text.lower()
    seen_employers = set()
    for company_lower, mappings in _COMPANY_UNIT_LOOKUP.items():
        if company_lower in text_lower and company_lower not in seen_employers:
            seen_employers.add(company_lower)
            for unit, strength in mappings:
                weight = WEIGHT_EMPLOYER_HISTORY
                if strength == "moderate":
                    weight = int(WEIGHT_EMPLOYER_HISTORY * 0.7)
                elif strength == "weak":
                    weight = int(WEIGHT_EMPLOYER_HISTORY * 0.4)
                _add("employer_history", unit, weight,
                     f"Worked at {company_lower} ({strength} {unit} signal)")

    # 7. Academic co-publications (score: 30)
    for pattern in KNOWN_RESEARCHERS:
        match = pattern.search(profile_text)
        if match:
            _add("academic_copub", "Talpiot", WEIGHT_ACADEMIC_COPUB,
                 f"Co-published with or mentions {match.group().strip()}")

    # Determine best unit
    if not unit_scores:
        return {"unit": None, "score": 0, "level": CONFIDENCE_UNKNOWN, "signals": signals}

    best_unit = max(unit_scores, key=unit_scores.get)
    best_score = unit_scores[best_unit]

    return {
        "unit": best_unit,
        "score": best_score,
        "level": _confidence_level(best_score),
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

CREATE_IDF_PROFILES = """
CREATE TABLE IF NOT EXISTS idf_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id       INTEGER NOT NULL,
    inferred_unit   TEXT,
    confidence_score INTEGER DEFAULT 0,
    confidence_level TEXT DEFAULT 'UNKNOWN',
    signals_json    TEXT,
    last_updated    TEXT,
    FOREIGN KEY (person_id) REFERENCES tracked_people(id)
)
"""

CREATE_UNIT_COMPANY_MAPPING = """
CREATE TABLE IF NOT EXISTS unit_company_mapping (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    likely_unit  TEXT NOT NULL,
    strength     TEXT NOT NULL CHECK(strength IN ('strong', 'moderate', 'weak'))
)
"""


def init_idf_tables(conn):
    """Create IDF-related tables if they don't already exist."""
    cur = conn.cursor()
    cur.execute(CREATE_IDF_PROFILES)
    cur.execute(CREATE_UNIT_COMPANY_MAPPING)
    conn.commit()


def get_idf_profile(conn, person_id):
    """Retrieve the stored IDF classification for a person.

    Returns:
        dict matching classify_idf_unit output, or None if not found.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT inferred_unit, confidence_score, confidence_level, signals_json, last_updated "
        "FROM idf_profiles WHERE person_id = ? ORDER BY last_updated DESC LIMIT 1",
        (person_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "unit": row[0],
        "score": row[1],
        "level": row[2],
        "signals": json.loads(row[3]) if row[3] else [],
        "last_updated": row[4],
    }


def save_idf_profile(conn, person_id, classification):
    """Insert or update the IDF classification for a person.

    Args:
        conn: sqlite3 connection.
        person_id: FK to tracked_people.id.
        classification: dict as returned by classify_idf_unit.
    """
    now = datetime.utcnow().isoformat()
    signals_json = json.dumps(classification.get("signals", []), ensure_ascii=False)
    cur = conn.cursor()

    # Check if a record already exists
    cur.execute("SELECT id FROM idf_profiles WHERE person_id = ?", (person_id,))
    existing = cur.fetchone()

    if existing:
        cur.execute(
            "UPDATE idf_profiles SET inferred_unit = ?, confidence_score = ?, "
            "confidence_level = ?, signals_json = ?, last_updated = ? "
            "WHERE person_id = ?",
            (classification.get("unit"), classification.get("score", 0),
             classification.get("level", CONFIDENCE_UNKNOWN), signals_json,
             now, person_id),
        )
    else:
        cur.execute(
            "INSERT INTO idf_profiles "
            "(person_id, inferred_unit, confidence_score, confidence_level, signals_json, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (person_id, classification.get("unit"), classification.get("score", 0),
             classification.get("level", CONFIDENCE_UNKNOWN), signals_json, now),
        )
    conn.commit()


def seed_company_mappings(conn):
    """Populate unit_company_mapping with known alumni-heavy companies.

    Idempotent: clears existing rows and re-inserts from the canonical
    UNIT_COMPANY_MAP so the table always reflects the latest codebase data.
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM unit_company_mapping")
    rows = []
    for unit, companies in UNIT_COMPANY_MAP.items():
        for company_name, strength in companies:
            rows.append((company_name, unit, strength))
    cur.executemany(
        "INSERT INTO unit_company_mapping (company_name, likely_unit, strength) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
