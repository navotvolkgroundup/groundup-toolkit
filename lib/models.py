"""
Centralized model IDs and API constants.

Update these when upgrading to new Claude model versions.
All skills and scripts should import from here instead of hardcoding model IDs.

Usage:
    from lib.models import MODEL_SONNET, MODEL_HAIKU
"""

# --- Claude model IDs ---

MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-20250514"
MODEL_SONNET_LATEST = "claude-sonnet-4-5-20250929"

# --- Anthropic API ---

ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# --- Default token limits ---

DEFAULT_MAX_TOKENS = 4096
HAIKU_MAX_TOKENS = 2000
