#!/usr/bin/env python3
"""
Handle opt-in/opt-out requests via WhatsApp and Email
Team members can send "opt in" or "opt out" to control meeting briefs
"""
import os
import sys
import subprocess
import tempfile
import re
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.expanduser('~/.openclaw'))
from lib.config import config
from lib.gws import gws_gmail_search, gws_gmail_thread_get, gws_gmail_modify, gws_gmail_send

WHATSAPP_ACCOUNT = None  # use default account
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..'))
OPTIN_FILE = os.path.join(_TOOLKIT_ROOT, 'data', 'meeting-brief-optin.json')
PROCESSED_LABEL = "MeetingBrief-Processed"

# Team members with phone and email (loaded from config)
TEAM_MEMBERS = {}
for m in config.team_members:
    TEAM_MEMBERS[m['email']] = {
        'name': m['name'].split()[0],
        'phone': m['phone']
    }

# Reverse lookup: phone -> email
PHONE_TO_EMAIL = {member['phone']: email for email, member in TEAM_MEMBERS.items()}

def _load_optin_data():
    """Load opt-in data from JSON file."""
    import json
    try:
        with open(OPTIN_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_optin_data(data):
    """Atomically save opt-in data to JSON file."""
    import json
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(OPTIN_FILE))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, OPTIN_FILE)
    except Exception:
        os.unlink(tmp_path)
        raise

def get_current_status(email):
    """Read current opt-in status from JSON file."""
    data = _load_optin_data()
    return data.get(email, {}).get('opted_in', False)

def set_opt_in(email, opted_in):
    """Update opt-in status for a team member."""
    data = _load_optin_data()
    if email not in data:
        data[email] = {}
    data[email]['opted_in'] = opted_in
    data[email]['updated_at'] = datetime.now().isoformat()
    _save_optin_data(data)
    return True

def send_whatsapp(phone, message):
    """Send WhatsApp message"""
    cmd = [
        'openclaw', 'message', 'send',
        '--channel', 'whatsapp',
        '--target', phone,
        '--message', message
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return result.returncode == 0

def send_email(to_email, subject, body):
    """Send email via gws"""
    return bool(gws_gmail_send(to_email, subject, body))

def mark_email_processed(thread_id):
    """Mark email as processed"""
    return bool(gws_gmail_modify(thread_id, add_labels=[PROCESSED_LABEL], remove_labels=['UNREAD', 'INBOX']))

def check_whatsapp_messages():
    """Check for WhatsApp opt-in/opt-out messages"""
    print(f"[{datetime.now()}] Checking WhatsApp messages...")

    # For now, we'll use a placeholder - OpenClaw WhatsApp integration would need
    # to be configured to log messages to a file or database
    # This is a simplified version

    print("  Note: WhatsApp message checking requires OpenClaw message logging")
    print("  Alternative: Team members can email instead")

    return []

def check_email_requests():
    """Check for email opt-in/opt-out requests"""
    print(f"[{datetime.now()}] Checking email requests...")

    team_emails = ' OR '.join([f'from:{email}' for email in TEAM_MEMBERS.keys()])
    query = f'in:inbox -{PROCESSED_LABEL} ({team_emails}) (subject:"meeting brief" OR body:"meeting brief") newer_than:1d'

    raw_threads = gws_gmail_search(query, max_results=10)

    if not raw_threads:
        print("  No requests found")
        return []

    print(f"  Found {len(raw_threads)} potential requests")

    processed = []

    for t in raw_threads:
        thread_id = t.get('id', '')

        # Get full thread details (gws search only returns id/snippet)
        thread_details = gws_gmail_thread_get(thread_id)
        if not thread_details or 'messages' not in thread_details:
            continue

        # Extract from/subject from first message headers
        first_msg = thread_details['messages'][0]
        headers = first_msg.get('payload', {}).get('headers', [])
        from_email = ''
        subject = ''
        for h in headers:
            name = h.get('name', '').lower()
            if name == 'from':
                from_email = h.get('value', '')
            elif name == 'subject':
                subject = h.get('value', '')

        # Extract sender email
        sender_match = re.search(r'<(.+?)>', from_email)
        sender_email = sender_match.group(1) if sender_match else from_email

        if sender_email not in TEAM_MEMBERS:
            continue

        # Check subject and body for opt-in/opt-out
        body = ""
        for msg in thread_details['messages']:
            body += msg.get('snippet', '') + " "

        text_to_check = f"{subject} {body}".lower()

        opt_in = False
        opt_out = False

        if re.search(r'\bopt\s*in\b', text_to_check):
            opt_in = True
        elif re.search(r'\bopt\s*out\b', text_to_check):
            opt_out = True

        if not opt_in and not opt_out:
            continue

        member = TEAM_MEMBERS[sender_email]
        current_status = get_current_status(sender_email)

        if opt_in and not current_status:
            # Opt in
            set_opt_in(sender_email, True)
            print(f"  Opted in: {member['name']} ({sender_email})")

            confirmation = f"""Hi {member['name']},

You've been successfully opted in to Smart Meeting Briefs!

You'll now receive intelligent meeting prep via WhatsApp 10 minutes before each meeting, including:
- HubSpot deal context
- Smart questions based on deal stage
- Attendee information
- Recent notes

Make sure your calendar is shared with {config.assistant_email} to receive briefs.

To opt out anytime, just email: "opt out of meeting briefs"

- Meeting Brief Bot"""

            send_email(sender_email, "Meeting Briefs - Opted In", confirmation)
            processed.append(f"{member['name']} opted in")

        elif opt_out and current_status:
            # Opt out
            set_opt_in(sender_email, False)
            print(f"  Opted out: {member['name']} ({sender_email})")

            confirmation = f"""Hi {member['name']},

You've been opted out of Smart Meeting Briefs.

You won't receive any more meeting prep messages. You can opt back in anytime by emailing: "opt in to meeting briefs"

- Meeting Brief Bot"""

            send_email(sender_email, "Meeting Briefs - Opted Out", confirmation)
            processed.append(f"{member['name']} opted out")

        else:
            # Already in desired state
            action = "opted in" if current_status else "opted out"
            print(f"  {member['name']} already {action}")

            confirmation = f"""Hi {member['name']},

You're already {"opted in to" if current_status else "opted out of"} Smart Meeting Briefs.

Current status: {"Receiving briefs" if current_status else "Not receiving briefs"}

- Meeting Brief Bot"""

            send_email(sender_email, "Meeting Briefs - Status Confirmed", confirmation)

        # Mark as processed
        mark_email_processed(thread_id)

    return processed

def main():
    print("="*70)
    print("MEETING BRIEF OPT-IN/OPT-OUT HANDLER")
    print("="*70)
    print()

    # Check WhatsApp messages (placeholder for now)
    whatsapp_processed = check_whatsapp_messages()

    # Check email requests
    email_processed = check_email_requests()

    print()
    print("="*70)
    print(f"Summary:")
    print(f"  WhatsApp: {len(whatsapp_processed)} processed")
    print(f"  Email: {len(email_processed)} processed")
    if email_processed:
        for action in email_processed:
            print(f"    - {action}")
    print("="*70)

if __name__ == "__main__":
    main()
