#!/usr/bin/env python3
"""
Handle opt-in/opt-out requests via WhatsApp and Email
Team members can send "opt in" or "opt out" to control meeting briefs
"""
import os
import sys
import json
import shlex
import subprocess
import tempfile
import re
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import config

GOG_ACCOUNT = config.assistant_email
WHATSAPP_ACCOUNT = os.environ.get("WHATSAPP_ACCOUNT", "main")
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meeting-brief-automation.py")
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

def _gog_env():
    env = os.environ.copy()
    env['GOG_KEYRING_PASSWORD'] = config.gog_keyring_password
    return env

def _run_gog(args, json_output=True):
    """Run a gog command safely without shell."""
    cmd = ['gog'] + args + ['--account', GOG_ACCOUNT]
    if json_output:
        cmd.append('--json')
    result = subprocess.run(cmd, capture_output=True, text=True, env=_gog_env())
    if result.returncode != 0:
        print(f"Error running gog: {result.stderr[:200]}", file=sys.stderr)
        return None
    if json_output:
        try:
            return json.loads(result.stdout)
        except Exception:
            return result.stdout
    return result

def run_gog_command(cmd):
    args = shlex.split(cmd)
    return _run_gog(args)

def get_current_status(email):
    """Read current opt-in status from script"""
    with open(SCRIPT_PATH, 'r') as f:
        content = f.read()

    pattern = rf"'{re.escape(email)}':\s*{{[^}}]*'opted_in':\s*(True|False)"
    match = re.search(pattern, content)
    if match:
        return match.group(1) == 'True'
    return False

def set_opt_in(email, opted_in):
    """Update opt-in status for a team member"""
    with open(SCRIPT_PATH, 'r') as f:
        content = f.read()

    pattern = rf"('{re.escape(email)}':\s*{{[^}}]*'opted_in':\s*)(True|False)"
    replacement = rf"\g<1>{opted_in}"
    new_content = re.sub(pattern, replacement, content)

    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(SCRIPT_PATH))
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(new_content)
        os.replace(tmp_path, SCRIPT_PATH)
    except:
        os.unlink(tmp_path)
        raise

    return True

def send_whatsapp(phone, message):
    """Send WhatsApp message"""
    cmd = [
        'openclaw', 'message', 'send',
        '--channel', 'whatsapp',
        '--account', WHATSAPP_ACCOUNT,
        '--target', phone,
        '--message', message
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return result.returncode == 0

def send_email(to_email, subject, body):
    """Send email via gog"""
    fd, body_path = tempfile.mkstemp(suffix='.txt', prefix='optin-email-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(body)
        result = _run_gog([
            'gmail', 'send',
            '--to', to_email,
            '--subject', subject,
            '--body-file', body_path,
        ], json_output=False)
        return result is not None and result.returncode == 0
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass

def mark_email_processed(thread_id):
    """Mark email as processed"""
    result = _run_gog([
        'gmail', 'thread', 'modify', thread_id,
        '--add', PROCESSED_LABEL, '--remove', 'UNREAD,INBOX', '--force',
    ], json_output=False)
    return result is not None and result.returncode == 0

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

    result = run_gog_command(f'gmail search "{query}" --limit 10')

    if not result or 'threads' not in result:
        print("  No requests found")
        return []

    threads = result.get('threads', [])
    if not threads:
        print("  No requests found")
        return []

    print(f"  Found {len(threads)} potential requests")

    processed = []

    for thread in threads:
        from_email = thread.get('from', '')
        subject = thread.get('subject', '')
        thread_id = thread.get('id', '')

        # Extract sender email
        sender_match = re.search(r'<(.+?)>', from_email)
        sender_email = sender_match.group(1) if sender_match else from_email

        if sender_email not in TEAM_MEMBERS:
            continue

        # Get thread details to check body
        thread_details = run_gog_command(f'gmail thread get {thread_id}')
        if not thread_details or 'messages' not in thread_details:
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
            print(f"  ✅ Opted in: {member['name']} ({sender_email})")

            confirmation = f"""Hi {member['name']},

You've been successfully opted in to Smart Meeting Briefs! 🎉

You'll now receive intelligent meeting prep via WhatsApp 10 minutes before each meeting, including:
- HubSpot deal context
- Smart questions based on deal stage
- Attendee information
- Recent notes

Make sure your calendar is shared with {GOG_ACCOUNT} to receive briefs.

To opt out anytime, just email: "opt out of meeting briefs"

- Meeting Brief Bot"""

            send_email(sender_email, "✅ Meeting Briefs - Opted In", confirmation)
            processed.append(f"{member['name']} opted in")

        elif opt_out and current_status:
            # Opt out
            set_opt_in(sender_email, False)
            print(f"  ❌ Opted out: {member['name']} ({sender_email})")

            confirmation = f"""Hi {member['name']},

You've been opted out of Smart Meeting Briefs.

You won't receive any more meeting prep messages. You can opt back in anytime by emailing: "opt in to meeting briefs"

- Meeting Brief Bot"""

            send_email(sender_email, "Meeting Briefs - Opted Out", confirmation)
            processed.append(f"{member['name']} opted out")

        else:
            # Already in desired state
            action = "opted in" if current_status else "opted out"
            print(f"  ℹ️  {member['name']} already {action}")

            confirmation = f"""Hi {member['name']},

You're already {"opted in to" if current_status else "opted out of"} Smart Meeting Briefs.

Current status: {"✅ Receiving briefs" if current_status else "❌ Not receiving briefs"}

- Meeting Brief Bot"""

            send_email(sender_email, "Meeting Briefs - Status Confirmed", confirmation)

        # Mark as processed
        mark_email_processed(thread_id)

    return processed

def create_opt_in_instructions():
    """Create instructions for team members"""
    instructions = f"""
# How to Opt In/Out of Meeting Briefs

## Via Email (Easiest)

Send an email to **{GOG_ACCOUNT}**:

**To opt in:**
- Subject: "Opt in to meeting briefs"
- Body: (anything)

**To opt out:**
- Subject: "Opt out of meeting briefs"
- Body: (anything)

You'll receive a confirmation email within a few minutes.

## Via WhatsApp (Coming Soon)

Send a message to the OpenClaw WhatsApp number:
- "opt in to meeting briefs"
- "opt out of meeting briefs"

## What You Get When Opted In

Smart meeting prep sent 10 minutes before each meeting:
- Meeting attendees and contact info
- HubSpot deal context and stage
- Smart questions based on deal stage
- Recent CRM notes
- Meeting links and location

## Requirements

Make sure your Google Calendar is shared with **{GOG_ACCOUNT}**:
1. Go to calendar.google.com
2. Settings → Your calendar
3. Share with specific people → Add {GOG_ACCOUNT}
4. Permission: "See all event details"

## Privacy

- Your calendar data is only used for meeting prep
- Phone numbers are stored securely
- You can opt out anytime
- No data is shared with third parties
"""

    return instructions

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
