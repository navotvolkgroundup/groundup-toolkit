"""
Shared WhatsApp message sender via OpenClaw CLI.

Usage:
    from lib.whatsapp import send_whatsapp

    send_whatsapp("+1234567890", "Hello!")
    send_whatsapp("+1234567890", "Hello!", account="main")
"""

import sys
import time
import subprocess


def send_whatsapp(phone, message, account=None, max_retries=3, retry_delay=3):
    """Send WhatsApp message via OpenClaw with retry.

    Args:
        phone: Recipient phone number.
        message: Message text.
        account: OpenClaw WhatsApp account name (default: None, uses default account).
        max_retries: Max retry attempts (default: 3).
        retry_delay: Seconds between retries (default: 3).

    Returns:
        True on success, False on failure.
    """
    if not phone or not phone.strip():
        print(f"  WhatsApp skipped: no phone number provided", file=sys.stderr)
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

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                print(f"  WhatsApp sent to {phone}" + (f" (attempt {attempt})" if attempt > 1 else ""))
                return True
            else:
                print(f"  WhatsApp attempt {attempt}/{max_retries} failed: {result.stderr.strip()[:100]}", file=sys.stderr)
                if attempt < max_retries:
                    time.sleep(retry_delay)
        except Exception as e:
            print(f"  WhatsApp attempt {attempt}/{max_retries} exception: {e}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(retry_delay)
    return False
