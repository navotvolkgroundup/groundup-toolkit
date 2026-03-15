"""
Shared Claude API client with configurable retry logic.

Usage:
    from lib.claude import call_claude

    response = call_claude("Summarize this text", system_prompt="You are helpful.")
    response = call_claude("Analyze this", model="claude-haiku-4-5", max_tokens=2000)
"""

import sys
import time
import requests

from lib.config import config
from lib.models import MODEL_SONNET, DEFAULT_MAX_TOKENS, ANTHROPIC_API_VERSION, ANTHROPIC_API_URL

ANTHROPIC_API_KEY = config.anthropic_api_key


def call_claude(prompt, system_prompt="", model=MODEL_SONNET,
                max_tokens=DEFAULT_MAX_TOKENS, timeout=120, max_retries=5):
    """Call Claude API with retry logic for rate limits and overload.

    Args:
        prompt: User message to send.
        system_prompt: Optional system prompt.
        model: Model ID (default: claude-sonnet-4-20250514).
        max_tokens: Max tokens in response (default: 4096).
        timeout: HTTP timeout in seconds (default: 120).
        max_retries: Max retry attempts for 429/529 errors (default: 5).

    Returns:
        Response text on success, None on failure.
    """
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    if system_prompt:
        payload["system"] = system_prompt

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json"
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload,
                timeout=timeout
            )
        except requests.exceptions.RequestException as e:
            print(f"  Claude API request error: {e}", file=sys.stderr)
            return None

        if response.status_code == 200:
            return response.json()["content"][0]["text"]

        if response.status_code == 429:
            wait = min(15 * (attempt + 1), 60)
            print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})...", file=sys.stderr)
            time.sleep(wait)
            continue

        if response.status_code == 529:
            wait = 30
            print(f"  API overloaded, waiting {wait}s (attempt {attempt + 1}/{max_retries})...", file=sys.stderr)
            time.sleep(wait)
            continue

        print(f"  Claude API error: HTTP {response.status_code}", file=sys.stderr)
        return None

    print(f"  Claude API: exhausted {max_retries} retries", file=sys.stderr)
    return None
