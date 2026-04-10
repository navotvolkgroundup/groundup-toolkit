"""
Shared WhatsApp message sender via OpenClaw CLI.

Usage:
    from lib.whatsapp import send_whatsapp, whatsapp_available

    send_whatsapp("+1234567890", "Hello!")
    send_whatsapp("+1234567890", "Hello!", account="main")

    # Check if WhatsApp is available before sending (circuit breaker)
    if whatsapp_available():
        send_whatsapp(...)
"""

import sys
import time
import shutil
import subprocess


# Circuit breaker: tracks consecutive failures to avoid hammering a dead gateway.
_consecutive_failures = 0
_CIRCUIT_BREAKER_THRESHOLD = 2  # skip after this many consecutive failures in one process


def whatsapp_available():
    """Check if WhatsApp sending is currently available (circuit breaker not tripped)."""
    return _consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD


def reset_circuit_breaker():
    """Reset the circuit breaker (e.g. at the start of a new check cycle)."""
    global _consecutive_failures
    _consecutive_failures = 0


def send_whatsapp(phone, message, account=None, max_retries=3, retry_delay=5):
    """Send WhatsApp message via OpenClaw with retry.

    Args:
        phone: Recipient phone number.
        message: Message text.
        account: OpenClaw WhatsApp account name (default: None, uses default account).
        max_retries: Max retry attempts (default: 3).
        retry_delay: Seconds between retries (default: 5).

    Returns:
        True on success, False on failure.
    """
    global _consecutive_failures

    if not phone or not phone.strip():
        print(f"  WhatsApp skipped: no phone number provided", file=sys.stderr)
        return False

    # Circuit breaker: skip if gateway is confirmed down
    if not whatsapp_available():
        print(f"  WhatsApp skipped: gateway unavailable (circuit breaker open after {_consecutive_failures} failures)", file=sys.stderr)
        return False

    # Check that openclaw CLI exists before trying
    if not shutil.which('openclaw'):
        print(f"  WhatsApp failed: 'openclaw' not found in PATH", file=sys.stderr)
        _consecutive_failures = _CIRCUIT_BREAKER_THRESHOLD  # trip immediately
        return False

    for attempt in range(1, max_retries + 1):
        try:
            cmd = [
                'openclaw', 'message', 'send',
                '--channel', 'whatsapp',
                '--target', phone,
                '--message', message
            ]
            if account and account not in ('default', 'main'):
                cmd.extend(['--account', account])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"  WhatsApp sent to {phone}" + (f" (attempt {attempt})" if attempt > 1 else ""))
                _consecutive_failures = 0  # reset on success
                return True
            else:
                print(f"  WhatsApp attempt {attempt}/{max_retries} failed: {result.stderr.strip()[:200]}", file=sys.stderr)
                if attempt < max_retries:
                    time.sleep(retry_delay)
        except subprocess.TimeoutExpired:
            print(f"  WhatsApp attempt {attempt}/{max_retries} timed out (30s) sending to {phone}", file=sys.stderr)
            # Don't retry timeouts — gateway is likely down
            _consecutive_failures += 1
            return False
        except FileNotFoundError:
            print(f"  WhatsApp failed: 'openclaw' not found in PATH", file=sys.stderr)
            _consecutive_failures = _CIRCUIT_BREAKER_THRESHOLD
            return False
        except Exception as e:
            print(f"  WhatsApp attempt {attempt}/{max_retries} error: {type(e).__name__}: {e}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(retry_delay)

    _consecutive_failures += 1
    return False
