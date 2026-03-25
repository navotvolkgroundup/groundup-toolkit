"""LinkedIn browser automation for US Founder Scout — search, profile lookup, and profile parsing."""

import re
import time
import logging
import subprocess
import sys
import os

# Add parent paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

try:
    from lib.claude import call_claude
except ImportError:
    call_claude = None

log = logging.getLogger("us-founder-scout")

# --- Configuration ---
LINKEDIN_BROWSER_PROFILE = "linkedin"
LINKEDIN_NAV_DELAY = 4  # seconds between LinkedIn page navigations


def linkedin_browser_available():
    """Check if the LinkedIn browser session is available."""
    try:
        result = subprocess.run(
            ['openclaw', 'browser', 'status', '--browser-profile', LINKEDIN_BROWSER_PROFILE, '--json'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        log.warning(f"LinkedIn browser status check failed: {e}")
        return False


def linkedin_search(query):
    """Search LinkedIn for people using the browser skill. Returns HTML snapshot text."""
    try:
        log.info(f"LinkedIn search: {query}")

        # URL encode the query
        encoded = subprocess.run(
            ['python3', '-c', f"import urllib.parse; print(urllib.parse.quote({query!r}))"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()

        url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"

        # Navigate to search results
        subprocess.run(
            ['openclaw', 'browser', 'navigate', '--browser-profile', LINKEDIN_BROWSER_PROFILE, url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(LINKEDIN_NAV_DELAY)

        # Get HTML snapshot with profile URLs
        result = subprocess.run(
            ['openclaw', 'browser', 'snapshot', '--browser-profile', LINKEDIN_BROWSER_PROFILE, '--format', 'html'],
            capture_output=True, text=True, timeout=15
        )

        if result.returncode == 0 and result.stdout:
            log.info(f"LinkedIn search returned {len(result.stdout)} bytes")
            return result.stdout
        else:
            log.error(f"LinkedIn search failed: {result.stderr}")
            return None
    except Exception as e:
        log.error(f"LinkedIn search error: {e}")
        return None


def linkedin_profile_lookup(url):
    """Look up a LinkedIn profile using the browser skill. Returns cleaned profile text."""
    try:
        log.info(f"LinkedIn profile lookup: {url}")

        # Navigate to profile
        subprocess.run(
            ['openclaw', 'browser', 'navigate', '--browser-profile', LINKEDIN_BROWSER_PROFILE, url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(5)

        # Get ARIA snapshot of profile
        result = subprocess.run(
            ['openclaw', 'browser', 'snapshot', '--browser-profile', LINKEDIN_BROWSER_PROFILE,
             '--format', 'aria', '--limit', '1000'],
            capture_output=True, text=True, timeout=15
        )

        if result.returncode != 0 or not result.stdout:
            log.warning(f"Failed to get profile snapshot: {result.stderr}")
            return None

        cleaned = _strip_aria_chrome(result.stdout)
        log.info(f"Profile lookup returned {len(cleaned)} bytes of cleaned content")
        return cleaned
    except Exception as e:
        log.error(f"LinkedIn profile lookup error: {e}")
        return None


def _strip_aria_chrome(aria_text):
    """Strip LinkedIn navigation chrome from ARIA snapshot, keeping profile content."""
    useful_lines = []
    in_profile = False

    for line in aria_text.split('\n'):
        stripped = line.strip()

        # Skip empty lines and pure structure lines
        if not stripped or stripped.startswith('- none') or stripped.startswith('- generic'):
            continue

        # Detect start of profile content
        if 'heading "' in stripped and not in_profile:
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


def extract_profiles_from_search(search_snapshot):
    """Parse profile URLs, names, and headlines from a LinkedIn search HTML snapshot.

    Returns list of dicts: [{"name": "...", "linkedin_url": "...", "headline": "..."}, ...]
    """
    if not search_snapshot:
        return []

    profiles = []
    seen_urls = set()

    lines = search_snapshot.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for: - link "Person Name" [ref=...]:
        name_match = re.match(r'- link "([^"]+)" \[ref=', line)
        if name_match:
            name = name_match.group(1)

            # Skip navigation links and junk entries
            if (name.startswith('View ') or name.startswith('Provides ')
                    or len(name) > 50
                    or name in ('LinkedIn', 'Home', 'My Network', 'Jobs', 'Messaging', 'Notifications')):
                i += 1
                continue

            # Look for URL on the next few lines
            linkedin_url = None
            headline = None

            for j in range(i + 1, min(i + 10, len(lines))):
                url_match = re.search(r'/url: (https://www\.linkedin\.com/in/[^\s]+)', lines[j])
                if url_match:
                    linkedin_url = url_match.group(1).rstrip(')')
                    break

            # Try to extract headline from surrounding context
            for j in range(i + 1, min(i + 15, len(lines))):
                if 'StaticText "' in lines[j]:
                    text = re.search(r'StaticText "([^"]*)"', lines[j])
                    if text and len(text.group(1)) > 5 and not text.group(1).startswith('View'):
                        headline = text.group(1)
                        break

            if linkedin_url and linkedin_url not in seen_urls:
                profiles.append({
                    'name': name,
                    'linkedin_url': linkedin_url,
                    'headline': headline or 'Unknown'
                })
                seen_urls.add(linkedin_url)

        i += 1

    return profiles


def filter_relevant_profiles(profiles, target_keywords=None):
    """Filter profiles for founding signals based on keywords."""
    if not target_keywords:
        target_keywords = [
            'founder', 'co-founder', 'CEO', 'CTO', 'CPO', 'VP Engineering',
            'VP Product', 'stealth', 'building', 'startup', 'entrepreneur'
        ]

    filtered = []
    for profile in profiles:
        headline = profile.get('headline', '').lower()
        name = profile.get('name', '').lower()

        # Check if headline or name contains founding keywords
        if any(kw.lower() in headline or kw.lower() in name for kw in target_keywords):
            filtered.append(profile)

    return filtered


def analyze_linkedin_profile(name, profile_text):
    """Use Claude to analyze a LinkedIn profile for founding signals."""
    if not call_claude:
        return {
            'is_founder_signal': False,
            'signal_tier': 'LOW',
            'reasons': ['Claude API not available'],
            'confidence': 0.0
        }

    prompt = f"""
Analyze this LinkedIn profile for signals that the person is starting a new company or venture.

Name: {name}
Profile:
{profile_text}

Return JSON:
{{
  "is_founder_signal": true/false,
  "signal_tier": "HIGH" or "MEDIUM" or "LOW",
  "reasons": ["reason1", "reason2"],
  "confidence": 0.0-1.0,
  "recent_role_change": true/false,
  "stealth_hints": true/false,
  "fundraising_signals": true/false
}}

HIGH = Recently left company + stealth hints, co-founding announcement, "day 1" posts, active recruitment
MEDIUM = Open to work, recent exit, exploring opportunities, new role at unknown company
LOW = Still at previous company, older posts, unclear signals
"""

    try:
        response = call_claude(
            model="claude-haiku-4-5-20251001",
            system="You are an expert at identifying tech founders. Analyze for founding signals. Respond only with valid JSON.",
            messages=[{"role": "user", "content": prompt}]
        )

        if response.content:
            text = response.content[0].text
            # Try to parse JSON
            import json
            try:
                data = json.loads(text)
                log.info(f"Profile analysis for {name}: {data['signal_tier']}")
                return data
            except json.JSONDecodeError:
                log.error(f"Failed to parse Claude response as JSON: {text}")
                return {
                    'is_founder_signal': False,
                    'signal_tier': 'LOW',
                    'reasons': ['JSON parse error'],
                    'confidence': 0.0
                }
    except Exception as e:
        log.error(f"Error analyzing profile for {name}: {e}")
        return {
            'is_founder_signal': False,
            'signal_tier': 'LOW',
            'reasons': [f'Analysis failed: {e}'],
            'confidence': 0.0
        }


def extract_github_from_linkedin(profile_text):
    """Extract GitHub URL from LinkedIn profile text."""
    # Look for github.com URLs
    match = re.search(r'https://github\.com/[\w\-]+', profile_text)
    if match:
        return match.group(0)
    return None
