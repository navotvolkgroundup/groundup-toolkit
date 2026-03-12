"""
Advisory Role Tracker — Detects accumulation of advisory/angel roles as a
signal of transitioning to founder.

When someone starts stacking advisory positions (Board Advisor at X, Angel
Investor at Y, Mentor at Z), it often means they've left full-time work and
are exploring the ecosystem before launching their own company. This module
parses LinkedIn ARIA snapshots for advisory roles, tracks count changes over
time, and flags when accumulation crosses significance thresholds.
"""

import re
import json
from datetime import datetime, timedelta


# Advisory role keywords (case-insensitive matching)
_ADVISORY_KEYWORDS = [
    'advisor',
    'advisory',
    'board advisor',
    'angel investor',
    'angel',
    'mentor',
    'venture partner',
    'board member',
    'board of directors',
    'strategic advisor',
    'venture advisor',
    'startup advisor',
    'eir',
    'entrepreneur in residence',
]

# Compiled pattern: match any advisory keyword as a whole word (case-insensitive).
# Sorted longest-first so "board advisor" matches before "advisor".
_ADVISORY_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(kw) for kw in sorted(_ADVISORY_KEYWORDS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)

# Known vertical keywords for company classification
_VERTICAL_KEYWORDS = {
    'cybersecurity': [
        'cyber', 'cybersecurity', 'security', 'infosec', 'threat', 'endpoint',
        'siem', 'soc', 'vulnerability', 'penetration', 'zero trust',
    ],
    'fintech': [
        'fintech', 'financial', 'payments', 'banking', 'insurtech', 'lending',
        'neobank', 'defi', 'credit', 'trading',
    ],
    'AI/ML': [
        'ai', 'artificial intelligence', 'machine learning', 'ml', 'deep learning',
        'nlp', 'natural language', 'computer vision', 'generative ai', 'llm',
    ],
    'healthtech': [
        'health', 'healthtech', 'medtech', 'biotech', 'pharma', 'clinical',
        'telemedicine', 'digital health', 'diagnostics', 'therapeutics',
    ],
    'devtools': [
        'devtools', 'developer tools', 'devops', 'ci/cd', 'infrastructure',
        'observability', 'monitoring', 'platform engineering', 'sdk',
    ],
    'data': [
        'data', 'analytics', 'data engineering', 'data platform', 'data lake',
        'etl', 'business intelligence', 'bi', 'data warehouse',
    ],
    'cloud': [
        'cloud', 'cloud-native', 'kubernetes', 'serverless', 'saas', 'iaas',
        'paas', 'multi-cloud', 'cloud infrastructure',
    ],
    'ecommerce': [
        'ecommerce', 'e-commerce', 'commerce', 'marketplace', 'retail tech',
        'shopify', 'dtc', 'd2c',
    ],
    'enterprise': [
        'enterprise', 'b2b', 'workflow', 'automation', 'erp', 'crm',
        'collaboration', 'productivity',
    ],
    'defense': [
        'defense', 'defence', 'military', 'dual-use', 'aerospace', 'govtech',
        'homeland security', 'intelligence',
    ],
}


# ---------------------------------------------------------------------------
# Role extraction from ARIA snapshot text
# ---------------------------------------------------------------------------

def extract_advisory_roles(profile_text):
    """Parse LinkedIn profile ARIA snapshot for advisory/angel positions.

    The profile text is an ARIA accessibility tree dump with patterns like:
        ## Experience
        StaticText "Board Advisor"
        StaticText "Acme Corp"
        StaticText "Jan 2024 - Present"
        ...
        StaticText "Angel Investor"
        StaticText "Stealth Startup"

    Or structured as:
        - generic [ref=N]: Advisor at Acme Corp
        - generic [ref=N]: Angel Investor
        link "Acme Corp"

    Returns:
        List of dicts: [
            {'title': 'Board Advisor', 'company': 'Acme Corp', 'is_advisory': True},
            ...
        ]
    """
    if not profile_text:
        return []

    roles = []
    seen = set()  # Dedup by (title_lower, company_lower)
    lines = profile_text.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # --- Pattern 1: StaticText containing an advisory keyword ---
        # StaticText "Board Advisor" or StaticText "Angel Investor at Acme Corp"
        static_match = re.match(r'(?:StaticText\s+)?["\u201c](.+?)["\u201d]', stripped)
        if not static_match:
            # Also handle bare text lines in generic ARIA nodes
            # - generic [ref=N]: Advisor at Acme Corp
            static_match = re.match(r'-\s+generic\s+\[ref=[^\]]*\]:\s*(.+)', stripped)

        if not static_match:
            # Plain text line that could be a role title
            if _ADVISORY_PATTERN.search(stripped) and len(stripped) < 120:
                content = stripped
            else:
                continue
        else:
            content = static_match.group(1).strip()

        if not _ADVISORY_PATTERN.search(content):
            continue

        # Extract title and company from various formats
        title, company = _parse_title_company(content, lines, i)

        if not title:
            continue

        dedup_key = (title.lower(), (company or '').lower())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        roles.append({
            'title': title,
            'company': company,
            'is_advisory': True,
        })

    return roles


def _parse_title_company(content, lines, line_idx):
    """Extract title and company from a line and its surrounding context.

    Handles:
        - "Board Advisor at Acme Corp"
        - "Board Advisor" followed by "Acme Corp" on next line
        - "Advisor, Acme Corp"
        - "Advisor - Acme Corp"
    """
    title = None
    company = None

    # Try "Title at Company" pattern
    at_match = re.match(r'(.+?)\s+at\s+(.+)', content, re.IGNORECASE)
    if at_match and _ADVISORY_PATTERN.search(at_match.group(1)):
        title = at_match.group(1).strip().strip('"\'')
        company = at_match.group(2).strip().strip('"\'')
        return title, company

    # Try "Title, Company" or "Title - Company"
    sep_match = re.match(r'(.+?)\s*[,\-\u2013\u2014]\s+(.+)', content)
    if sep_match and _ADVISORY_PATTERN.search(sep_match.group(1)):
        candidate_title = sep_match.group(1).strip().strip('"\'')
        candidate_company = sep_match.group(2).strip().strip('"\'')
        # Only use this if company part doesn't look like a date or duration
        if not re.match(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4})', candidate_company):
            title = candidate_title
            company = candidate_company
            return title, company

    # The whole content is the title; look for company in nearby lines
    if _ADVISORY_PATTERN.search(content):
        title = content.strip().strip('"\'')

        # Look ahead for company name in the next few lines
        for j in range(line_idx + 1, min(line_idx + 5, len(lines))):
            next_line = lines[j].strip()

            # Skip empty lines
            if not next_line:
                continue

            # Stop if we hit another advisory keyword (next role)
            if _ADVISORY_PATTERN.search(next_line) and j > line_idx + 1:
                break

            # Stop if we hit a section header
            if next_line.startswith('##') or next_line.startswith('heading'):
                break

            # Stop if we hit a date pattern (means we missed the company)
            if re.match(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}', next_line):
                break

            # Extract company from StaticText, generic ref, or link patterns
            company_match = (
                re.match(r'(?:StaticText\s+)?["\u201c](.+?)["\u201d]', next_line) or
                re.match(r'-\s+generic\s+\[ref=[^\]]*\]:\s*(.+)', next_line) or
                re.match(r'-?\s*link\s+["\u201c](.+?)["\u201d]', next_line)
            )
            if company_match:
                candidate = company_match.group(1).strip()
                # Skip if it looks like a date, duration, or location
                if (not re.match(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4})', candidate)
                        and not re.match(r'\d+\s+(?:yr|mo|year|month)', candidate)
                        and len(candidate) > 1
                        and not _ADVISORY_PATTERN.search(candidate)):
                    company = candidate
                    break

        return title, company

    return None, None


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def detect_advisory_accumulation(current_roles, previous_count, employment_status=None):
    """Check if advisory role count increased significantly.

    Args:
        current_roles: List of role dicts from extract_advisory_roles().
        previous_count: Number of advisory roles at last check (int).
        employment_status: Optional — 'employed', 'left_role', 'between_roles'.

    Returns:
        None if no signal, or dict:
        {
            signal_type: 'advisory_accumulation',
            tier: 'high' | 'medium' | 'low',
            description: str,
            advisory_count: int,
            verticals: list[str],
        }
    """
    if not current_roles:
        return None

    current_count = len(current_roles)

    # Handle case where previous_count is None (first check)
    if previous_count is None:
        previous_count = 0

    new_roles = current_count - previous_count

    if new_roles <= 0:
        return None

    verticals = extract_verticals(current_roles)

    # Determine tier
    if new_roles >= 3 and employment_status in ('left_role', 'between_roles'):
        tier = 'high'
    elif new_roles >= 2 and employment_status in ('left_role', 'between_roles'):
        tier = 'high'
    elif new_roles >= 2 and employment_status == 'employed':
        tier = 'medium'
    elif new_roles >= 2:
        # Unknown employment status
        tier = 'medium'
    elif new_roles == 1:
        tier = 'low'
    else:
        return None

    # Build description
    parts = [f"Added {new_roles} advisory role{'s' if new_roles != 1 else ''} (now {current_count} total)"]

    role_titles = [r['title'] for r in current_roles if r.get('title')]
    companies = [r['company'] for r in current_roles if r.get('company')]

    if companies:
        # Show up to 3 company names
        shown = companies[:3]
        suffix = f" +{len(companies) - 3} more" if len(companies) > 3 else ""
        parts.append(f"at {', '.join(shown)}{suffix}")

    if employment_status == 'left_role':
        parts.append("after leaving full-time role")
    elif employment_status == 'between_roles':
        parts.append("while between roles")
    elif employment_status == 'employed':
        parts.append("while still employed full-time")

    if verticals:
        parts.append(f"vertical focus: {', '.join(verticals)}")

    description = '; '.join(parts)

    return {
        'signal_type': 'advisory_accumulation',
        'tier': tier,
        'description': description,
        'advisory_count': current_count,
        'verticals': verticals,
    }


# ---------------------------------------------------------------------------
# Vertical extraction
# ---------------------------------------------------------------------------

def extract_verticals(roles):
    """Identify common verticals across advisory roles.

    Examines company names and titles for vertical keywords, then returns
    verticals that appear in 2+ roles (or all verticals if each role maps to
    a different one).

    Returns:
        List of vertical strings, e.g. ['cybersecurity', 'AI/ML'].
    """
    if not roles:
        return []

    vertical_counts = {}

    for role in roles:
        # Combine title and company text for keyword matching
        text_parts = []
        if role.get('title'):
            text_parts.append(role['title'])
        if role.get('company'):
            text_parts.append(role['company'])
        combined = ' '.join(text_parts).lower()

        matched_verticals_for_role = set()
        for vertical, keywords in _VERTICAL_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in combined:
                    matched_verticals_for_role.add(vertical)
                    break

        for v in matched_verticals_for_role:
            vertical_counts[v] = vertical_counts.get(v, 0) + 1

    if not vertical_counts:
        return []

    # Return verticals that appear in 2+ roles, or all found verticals if
    # total roles is small (< 3)
    total_roles = len(roles)
    if total_roles < 3:
        # With few roles, any vertical match is meaningful
        return sorted(vertical_counts.keys())

    # With many roles, only return verticals appearing in multiple roles
    significant = [v for v, count in vertical_counts.items() if count >= 2]
    if significant:
        return sorted(significant)

    # Fallback: return all found verticals
    return sorted(vertical_counts.keys())
