"""LinkedIn browser automation — search, profile lookup, and profile parsing."""

import re
import time
import logging
import subprocess

from lib.claude import call_claude

log = logging.getLogger("founder-scout")

# --- Configuration ---
LINKEDIN_BROWSER_PROFILE = "linkedin"
LINKEDIN_NAV_DELAY = 4  # seconds between LinkedIn page navigations


def linkedin_browser_available():
    """Check if the LinkedIn browser session is available."""
    try:
        result = subprocess.run(
            ['openclaw', 'browser', '--browser-profile', LINKEDIN_BROWSER_PROFILE, 'status', '--json'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def linkedin_search(query):
    """Search LinkedIn for people using the browser skill. Returns HTML snapshot text."""
    try:
        encoded = subprocess.run(
            ['python3', '-c', f"import urllib.parse; print(urllib.parse.quote({query!r}))"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()

        url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
        subprocess.run(
            ['openclaw', 'browser', '--browser-profile', LINKEDIN_BROWSER_PROFILE, 'navigate', url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(3)

        # Use --format html to get profile URLs and headlines
        result = subprocess.run(
            ['openclaw', 'browser', '--browser-profile', LINKEDIN_BROWSER_PROFILE, 'snapshot', '--format', 'html'],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout if result.returncode == 0 else None
    except Exception as e:
        log.error("LinkedIn search error: %s", e)
        return None


def _strip_aria_chrome(aria_text):
    """Strip LinkedIn navigation chrome from ARIA snapshot, keeping profile content.

    Extracts only lines containing useful profile info (name, headline, experience,
    about, education, etc.) and removes verbose ARIA tree structure.
    """
    useful_lines = []
    in_profile = False
    for line in aria_text.split('\n'):
        stripped = line.strip()
        # Skip empty lines and pure structure lines
        if not stripped or stripped.startswith('- none') or stripped.startswith('- generic'):
            continue
        # Detect start of profile content (past the nav bar)
        if 'heading "' in stripped and not in_profile:
            # Check if this is the person's name heading (first real heading after nav)
            if any(kw in stripped.lower() for kw in ['experience', 'about', 'education']):
                in_profile = True
            elif 'LinkedIn' not in stripped and 'Navigation' not in stripped:
                in_profile = True
        if not in_profile:
            continue
        # Extract text content from ARIA lines
        if 'StaticText "' in stripped:
            text = re.search(r'StaticText "([^"]*)"', stripped)
            if text:
                useful_lines.append(text.group(1))
        elif 'heading "' in stripped:
            text = re.search(r'heading "([^"]*)"', stripped)
            if text:
                useful_lines.append(f"\n## {text.group(1)}")
        elif 'link "' in stripped:
            text = re.search(r'link "([^"]*)"', stripped)
            if text and len(text.group(1)) > 3:
                useful_lines.append(text.group(1))
    return '\n'.join(useful_lines)


def linkedin_profile_lookup(url):
    """Look up a LinkedIn profile using the browser skill. Returns cleaned profile text."""
    try:
        subprocess.run(
            ['openclaw', 'browser', '--browser-profile', LINKEDIN_BROWSER_PROFILE, 'navigate', url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(5)

        result = subprocess.run(
            ['openclaw', 'browser', '--browser-profile', LINKEDIN_BROWSER_PROFILE, 'snapshot',
             '--format', 'aria', '--limit', '1000'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0 or not result.stdout:
            return None
        return _strip_aria_chrome(result.stdout)
    except Exception as e:
        log.error("LinkedIn profile lookup error: %s", e)
        return None


def extract_profiles_from_search(search_snapshot):
    """Parse profile URLs, names, and headlines from a LinkedIn search HTML snapshot.

    The HTML snapshot format has entries like:
        - link "Name" [ref=...]:
            - /url: https://www.linkedin.com/in/username?...
        ...
        - generic [ref=...]: Headline text
        - generic [ref=...]: Location

    Returns list of dicts: [{"name": "...", "linkedin_url": "...", "headline": "..."}, ...]
    """
    if not search_snapshot:
        return []

    profiles = []
    seen_urls = set()

    # Split into lines for sequential parsing
    lines = search_snapshot.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for: - link "Person Name" [ref=...]:
        # Followed by: - /url: https://www.linkedin.com/in/...
        name_match = re.match(r'- link "([^"]+)" \[ref=', line)
        if name_match:
            name = name_match.group(1)
            # Skip navigation links, "View X's profile" links, and junk entries
            if (name.startswith('View ') or name.startswith('Provides ')
                    or len(name) > 50
                    or name in ('LinkedIn', 'Home', 'My Network', 'Jobs', 'Messaging', 'Notifications')):
                i += 1
                continue

            # Look for /url on the next few lines
            url = None
            for j in range(i + 1, min(i + 5, len(lines))):
                url_match = re.search(r'/url: (https://www\.linkedin\.com/in/[^\s?]+)', lines[j])
                if url_match:
                    url = url_match.group(1)
                    break

            if url and url not in seen_urls:
                seen_urls.add(url)

                # Look for headline in the nearby lines (typically within ~20 lines after the name link)
                headline = None
                for j in range(i + 5, min(i + 25, len(lines))):
                    hl_line = lines[j].strip()
                    # Headlines appear as: - generic [ref=...]: Headline text
                    hl_match = re.match(r'- generic \[ref=[^\]]+\]: (.+)', hl_line)
                    if hl_match:
                        text = hl_match.group(1).strip()
                        # Skip short texts (connection degree, follower counts, location names)
                        if len(text) > 10 and not text.startswith('View ') and 'degree connection' not in text and 'follower' not in text:
                            headline = text
                            break

                profiles.append({
                    'name': name,
                    'linkedin_url': f"https://www.linkedin.com/in/{url.split('/in/')[-1]}",
                    'headline': headline,
                })

        i += 1

    return profiles


def filter_relevant_profiles(profiles):
    """Filter profiles by headline keywords — only keep people clearly starting something new.

    Uses deterministic keyword matching instead of Claude (which can't distinguish
    established founders from new ones based on short headlines alone).
    """
    if not profiles:
        return []

    # Positive signals — headline must contain at least one of these
    POSITIVE_SIGNALS = [
        'stealth', 'stealth mode',
        'building something', 'building the future', 'building a ', 'building in ',
        'new venture', 'new startup', 'new company',
        'next chapter', "what's next", 'whats next', 'exploring next',
        'launching', 'just launched',
        'pre-seed', 'pre seed', 'preseed',
        'in formation', 'day one', 'day 1',
        'working on something new', 'starting something',
        'left to start', 'left to build', 'left to found',
        'formerly at', 'formerly @',  # "formerly at X" + no current title = signal
    ]

    # Negative signals — remove even if positive signal matches
    NEGATIVE_TITLES = [
        'investor', 'venture capital', 'vc ', ' vc', 'partner at',
        'managing partner', 'general partner', 'limited partner',
        'angel investor', 'board member', 'board of directors',
        'advisor', 'adviser', 'consultant', 'consulting',
        'mentor', 'coach', 'speaker', 'author',
        'professor', 'lecturer', 'academic', 'researcher',
        'journalist', 'reporter', 'editor',
        'recruiter', 'talent', 'hiring',
    ]

    # Known established companies — founders/CEOs at these are NOT new founders
    ESTABLISHED_COMPANIES = [
        'wix', 'monday', 'check point', 'checkpoint', 'nice', 'amdocs',
        'fiverr', 'similarweb', 'taboola', 'outbrain', 'playtika',
        'ironource', 'ironsource', 'jvp', 'jerusalem venture',
        'viola', 'pitango', 'magma', 'vertex', 'aleph', 'grove ventures',
        'insight partners', 'sequoia', 'a16z', 'ycombinator', 'y combinator',
        'qumra', 'glilot', 'entree capital', 'ourcrowd', 'leumitech',
        'microsoft', 'google', 'meta', 'facebook', 'amazon', 'apple',
        'intel', 'nvidia', 'salesforce', 'oracle', 'ibm', 'cisco',
        'paypal', 'stripe', 'tiktok', 'bytedance', 'uber', 'airbnb',
        'mobileye', 'mellanox', 'cyberark', 'varonis', 'sapiens',
        'elbit', 'rafael', 'iai ', 'israel aerospace',
    ]

    filtered = []
    for p in profiles:
        headline = (p.get('headline') or '').lower().strip()
        if not headline or headline == 'no headline':
            continue

        # Check for negative signals first
        has_negative = any(neg in headline for neg in NEGATIVE_TITLES)
        if has_negative:
            log.debug("Filtered out (negative): %s — %s", p['name'], headline)
            continue

        # Check for established companies — but skip this check if headline
        # indicates they LEFT that company (ex-, former, formerly, left)
        has_left_prefix = any(prefix in headline for prefix in ['ex-', 'former ', 'formerly ', 'left '])
        if not has_left_prefix:
            at_established = any(co in headline for co in ESTABLISHED_COMPANIES)
            if at_established:
                log.debug("Filtered out (established co): %s — %s", p['name'], headline)
                continue

        # Check for positive signals
        has_positive = any(sig in headline for sig in POSITIVE_SIGNALS)
        if has_positive:
            log.debug("Kept (positive signal): %s — %s", p['name'], headline)
            filtered.append(p)
        else:
            log.debug("Filtered out (no signal): %s — %s", p['name'], headline)

    return filtered


def analyze_linkedin_profile(name, profile_text, linkedin_url, claude_calls_remaining):
    """Analyze a LinkedIn profile snapshot — is this person starting something new?

    Returns dict with: name, relevant (bool), summary, current_title, linkedin_url.
    Uses full profile data (experience, about, headline) for accurate assessment.
    """
    if claude_calls_remaining <= 0:
        return None

    import json
    system_prompt = (
        "You are a VC scout for a first-check fund. Your job is to determine whether "
        "a person is CURRENTLY starting a new company (founded in the last 6 months) or "
        "is clearly about to. You have access to their full LinkedIn profile."
    )
    prompt = f"""Analyze this LinkedIn profile. Is this person starting a NEW company?

NAME: {name}
LINKEDIN URL: {linkedin_url}

PROFILE DATA:
{profile_text[:4000]}

Answer with ONLY valid JSON (no markdown):
{{"name": "{name}", "relevant": true/false, "summary": "1-2 sentence explanation", "current_title": "their current role", "linkedin_url": "{linkedin_url}"}}

RELEVANT (true) means:
- They recently founded or co-founded a new company (last ~6 months)
- They are at a stealth startup or building something unnamed
- Their profile explicitly says they are starting something new

NOT RELEVANT (false) means:
- They are a founder/CEO at an ESTABLISHED company (founded years ago)
- They are an investor, VC partner, advisor, or consultant
- They left a job but are not clearly starting something new
- They are at a known company in a senior role
- They are a serial entrepreneur promoting past exits, not a current new venture
- Any ambiguity — when in doubt, return false"""

    response = call_claude(prompt, system_prompt, max_tokens=300)
    if not response:
        return None

    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        log.warning("Could not parse Claude response for %s: %s", name, response[:200])
    return None


def extract_github_from_linkedin(profile_text):
    """Try to extract a GitHub URL from LinkedIn profile text."""
    if not profile_text:
        return None
    m = re.search(r'(https?://github\.com/[A-Za-z0-9_-]+)(?:\s|$|[)\]<])', profile_text)
    return m.group(1) if m else None
