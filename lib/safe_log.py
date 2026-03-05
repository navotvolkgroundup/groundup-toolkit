"""
Security-aware error logging — strips credentials from exception messages.

Usage:
    from lib.safe_log import safe_error
    try:
        ...
    except Exception as e:
        safe_error("HubSpot search failed", e)
"""
import re
import sys


# Patterns to redact from error messages
_REDACT_PATTERNS = [
    # API keys / tokens in URLs
    (re.compile(r'([\?&](key|token|secret|api_key|apikey|access_token|auth)=)[^&\s]+', re.I), r'\1[REDACTED]'),
    # Authorization headers
    (re.compile(r'(Authorization:\s*(?:Bearer|Basic|Token)\s+)\S+', re.I), r'\1[REDACTED]'),
    # Common API key patterns (Anthropic, Google, generic sk- keys)
    (re.compile(r'sk-ant-[A-Za-z0-9_-]{10,}'), '[REDACTED]'),
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '[REDACTED]'),
    (re.compile(r'(GOCSPX-)[A-Za-z0-9_-]+', re.I), r'\1[REDACTED]'),
    # Generic long hex/base64 strings that look like keys (32+ chars)
    (re.compile(r'(?<=[=:\s])[A-Za-z0-9+/=_-]{40,}'), '[REDACTED]'),
]


def sanitize_error(msg):
    """Strip potential credentials from an error message string."""
    text = str(msg)
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def safe_error(context, exception, max_len=300):
    """Print a sanitized error message to stderr.

    Args:
        context: Human-readable context (e.g., "HubSpot search failed")
        exception: The caught exception
        max_len: Maximum length of error detail to print
    """
    sanitized = sanitize_error(str(exception))[:max_len]
    print(f"  {context}: {sanitized}", file=sys.stderr)
    return sanitized
