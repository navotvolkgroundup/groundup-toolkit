"""
Shared email sender via gws-auth CLI.

Usage:
    from lib.email import send_email

    send_email("user@example.com", "Subject", "Body text")
"""

import sys

from lib.gws import gws_gmail_send


def send_email(to_email, subject, body, account=None):
    """Send email using gws-auth.

    Args:
        to_email: Recipient email address.
        subject: Email subject.
        body: Email body text.
        account: Ignored (kept for API compatibility). gws-auth uses the authenticated account.

    Returns:
        True on success, False on failure.
    """
    result = gws_gmail_send(to_email, subject, body)
    if result:
        print(f"  Email sent to {to_email}")
        return True
    else:
        print(f"  Email failed for {to_email}", file=sys.stderr)
        return False
