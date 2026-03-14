"""
Shared Brave Search API client.

Usage:
    from lib.brave import brave_search

    results = brave_search("startup funding 2026")
    # Returns: [{"title": "...", "url": "...", "description": "..."}, ...]
"""

import sys
import time
import requests

from lib.config import config

BRAVE_SEARCH_API_KEY = config.brave_search_api_key

_MAX_RETRIES = 3
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def brave_search(query, count=5):
    """Search using Brave Search API.

    Args:
        query: Search query string.
        count: Number of results (default: 5).

    Returns:
        List of dicts with title, url, description. Empty list on failure.
    """
    if not BRAVE_SEARCH_API_KEY:
        return []

    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_SEARCH_API_KEY},
                params={"q": query, "count": count},
                timeout=10
            )
            if response.status_code == 200:
                return [
                    {"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
                    for r in response.json().get("web", {}).get("results", [])
                ]
            if response.status_code in _RETRYABLE_STATUSES:
                wait = 2 ** attempt  # 1s, 2s, 4s
                print(f"  Brave search HTTP {response.status_code}, retrying in {wait}s "
                      f"(attempt {attempt + 1}/{_MAX_RETRIES})...", file=sys.stderr)
                time.sleep(wait)
                continue
            # Non-retryable HTTP error
            return []
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            wait = 2 ** attempt
            print(f"  Brave search error: {e}, retrying in {wait}s "
                  f"(attempt {attempt + 1}/{_MAX_RETRIES})...", file=sys.stderr)
            time.sleep(wait)
            continue
        except Exception as e:
            print(f"  Search error: {e}", file=sys.stderr)
            return []

    print(f"  Brave search: exhausted {_MAX_RETRIES} retries", file=sys.stderr)
    return []
