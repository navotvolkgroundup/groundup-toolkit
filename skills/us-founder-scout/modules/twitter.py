"""Twitter/X browser automation for signal detection."""

import re
import time
import logging
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

try:
    from lib.claude import call_claude
except ImportError:
    call_claude = None

log = logging.getLogger("us-founder-scout")

# --- Configuration ---
TWITTER_BROWSER_PROFILE = "twitter"
TWITTER_NAV_DELAY = 3  # seconds between Twitter page navigations

# Keywords indicating founding signals
FOUNDING_KEYWORDS = [
    "stealth", "building something", "day 1", "we're hiring",
    "left company", "chapter 2", "new chapter", "grateful for the journey",
    "excited to announce", "happy to share", "launching", "go-live"
]

EXIT_KEYWORDS = [
    "acquired", "exit", "proud to announce", "joining", "thrilled to share",
    "chapter closed", "time for next chapter"
]


def twitter_browser_available():
    """Check if the Twitter browser session is available."""
    try:
        result = subprocess.run(
            ['openclaw', 'browser', '--browser-profile', TWITTER_BROWSER_PROFILE, 'status'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        log.warning(f"Twitter browser status check failed: {e}")
        return False


def twitter_search(query):
    """Search Twitter for posts using the browser skill. Returns text content."""
    try:
        log.info(f"Twitter search: {query}")

        # URL encode the query
        encoded = subprocess.run(
            ['python3', '-c', f"import urllib.parse; print(urllib.parse.quote({query!r}))"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()

        # Twitter search URL
        url = f"https://x.com/search?q={encoded}&f=live"

        # Navigate to search results
        subprocess.run(
            ['openclaw', 'browser', '--browser-profile', TWITTER_BROWSER_PROFILE, 'navigate', url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(TWITTER_NAV_DELAY)

        # Get ARIA snapshot of search results
        result = subprocess.run(
            ['openclaw', 'browser', '--browser-profile', TWITTER_BROWSER_PROFILE, 'snapshot', '--format', 'aria', '--limit', '500'],
            capture_output=True, text=True, timeout=15
        )

        if result.returncode == 0 and result.stdout:
            log.info(f"Twitter search returned {len(result.stdout)} bytes")
            return result.stdout
        else:
            log.error(f"Twitter search failed: {result.stderr}")
            return None
    except Exception as e:
        log.error(f"Twitter search error: {e}")
        return None


def twitter_profile_timeline(handle):
    """Get a Twitter profile's recent tweets using the browser skill."""
    try:
        log.info(f"Twitter timeline: @{handle}")

        url = f"https://x.com/{handle}"

        # Navigate to profile
        subprocess.run(
            ['openclaw', 'browser', '--browser-profile', TWITTER_BROWSER_PROFILE, 'navigate', url],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(TWITTER_NAV_DELAY)

        # Get ARIA snapshot
        result = subprocess.run(
            ['openclaw', 'browser', '--browser-profile', TWITTER_BROWSER_PROFILE, 'snapshot', '--format', 'aria', '--limit', '500'],
            capture_output=True, text=True, timeout=15
        )

        if result.returncode == 0 and result.stdout:
            log.info(f"Twitter timeline returned {len(result.stdout)} bytes")
            return result.stdout
        else:
            log.error(f"Twitter timeline failed: {result.stderr}")
            return None
    except Exception as e:
        log.error(f"Twitter timeline error: {e}")
        return None


def extract_signal_keywords(text):
    """Extract founding/exit signal keywords from text."""
    text_lower = text.lower()
    signals = {
        'founding': [],
        'exit': [],
        'hiring': []
    }

    for kw in FOUNDING_KEYWORDS:
        if kw.lower() in text_lower:
            signals['founding'].append(kw)

    for kw in EXIT_KEYWORDS:
        if kw.lower() in text_lower:
            signals['exit'].append(kw)

    if 'hiring' in text_lower or 'we are hiring' in text_lower or 'now hiring' in text_lower:
        signals['hiring'].append('hiring')

    return signals


def analyze_twitter_activity(handle, timeline_text):
    """Use Claude to analyze Twitter activity for founding signals."""
    if not call_claude:
        return {
            'signal_tier': 'LOW',
            'signals_detected': [],
            'confidence': 0.0,
            'recent_founding_hints': False
        }

    prompt = f"""
Analyze this Twitter profile's recent activity for founding signals.

Handle: @{handle}
Recent timeline:
{timeline_text}

Return JSON:
{{
  "signal_tier": "HIGH" or "MEDIUM" or "LOW",
  "signals_detected": ["signal1", "signal2"],
  "recent_founding_hints": true/false,
  "activity_spike": true/false,
  "engagement_with_founders": true/false,
  "confidence": 0.0-1.0,
  "summary": "brief description"
}}

HIGH = Recent posts about starting company, stealth mode, hiring, or significant activity spike
MEDIUM = Posts suggesting exploration, new venture hints, engagement with investor/founder network
LOW = No clear signals or older posts
"""

    try:
        import json
        text = call_claude(
            prompt,
            system_prompt="You are an expert at identifying founder signals. Analyze Twitter activity. Respond only with valid JSON.",
            model="claude-haiku-4-5-20251001",
        )

        data = json.loads(text)
        log.info(f"Twitter analysis for @{handle}: {data['signal_tier']}")
        return data
    except json.JSONDecodeError:
        log.error(f"Failed to parse Claude response as JSON")
        return {
            'signal_tier': 'LOW',
            'signals_detected': [],
            'confidence': 0.0,
            'recent_founding_hints': False
        }
    except Exception as e:
        log.error(f"Error analyzing Twitter for @{handle}: {e}")
        return {
            'signal_tier': 'LOW',
            'signals_detected': [],
            'confidence': 0.0,
            'recent_founding_hints': False
        }


def extract_twitter_handle(text):
    """Extract Twitter handle from text or profile."""
    match = re.search(r'@([\w]+)', text)
    if match:
        return match.group(1)
    return None
