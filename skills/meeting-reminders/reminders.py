#!/usr/bin/env python3
"""
Meeting Reminder Automation - GroundUp Toolkit
Sends WhatsApp notifications before each calendar meeting
Enhanced with HubSpot context
"""

import os
import sys
import json
import subprocess
import sqlite3
import fcntl
import time
import requests
from datetime import datetime, timedelta
import pytz

# Shared config loader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config

# Enrichment library integration
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))

try:
    from enrichment import EnrichmentService
    ENRICHMENT_AVAILABLE = True
except ImportError:
    print("Warning: Enrichment library not available")
    ENRICHMENT_AVAILABLE = False

GOG_ACCOUNT = config.assistant_email
WHATSAPP_ACCOUNT = config.whatsapp_account
MATON_API_KEY = config.maton_api_key
MATON_BASE_URL = "https://gateway.maton.ai/hubspot"

# Persistent database path (survives reboots, unlike /tmp)
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "meeting-reminders.db")
LOCK_PATH = os.path.join(_DATA_DIR, "meeting-reminders.lock")

# Team members with calendars and phone numbers (loaded from config)
TEAM_MEMBERS = {}
for m in config.team_members:
    TEAM_MEMBERS[m['email']] = {
        'name': m['name'].split()[0],  # First name only
        'phone': m['phone'],
        'timezone': m['timezone'],
        'enabled': m.get('reminders_enabled', True)
    }

# Notification window: 5-20 minutes before meeting
# Wide window (15 min) with 5-min cron ensures no meeting falls through the gap
NOTIFICATION_WINDOW_START = 20  # minutes before meeting (far edge)
NOTIFICATION_WINDOW_END = 5     # minutes before meeting (near edge)


class ReminderDatabase:
    """Track which meetings have been notified"""

    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notified_meetings (
                event_id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                meeting_start TEXT NOT NULL
            )
        ''')
        # Clean up old notifications (older than 24 hours)
        cutoff = (datetime.now(pytz.UTC).replace(tzinfo=None) - timedelta(hours=24)).isoformat()
        cursor.execute('DELETE FROM notified_meetings WHERE notified_at < ?', (cutoff,))
        conn.commit()
        conn.close()

    def is_notified(self, event_id, email):
        """Check if meeting has been notified"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM notified_meetings WHERE event_id = ? AND email = ?',
            (event_id, email)
        )
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def mark_notified(self, event_id, email, meeting_start):
        """Mark meeting as notified"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO notified_meetings (event_id, email, notified_at, meeting_start) VALUES (?, ?, ?, ?)',
            (event_id, email, datetime.now(pytz.UTC).replace(tzinfo=None).isoformat(), meeting_start)
        )
        conn.commit()
        conn.close()


def run_gog_command(cmd):
    """Run gog command with keyring password"""
    keyring_password = os.environ.get("GOG_KEYRING_PASSWORD", "")
    full_cmd = f'export GOG_KEYRING_PASSWORD="{keyring_password}" && gog {cmd} --account {GOG_ACCOUNT} --json'

    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            print(f"Error running gog command: {result.stderr}", file=sys.stderr)
            return None

        if result.stdout:
            return json.loads(result.stdout)
        return {}
    except Exception as e:
        print(f"Exception running gog command: {e}", file=sys.stderr)
        return None


def get_upcoming_events(email, start_time, end_time):
    """Get calendar events in time range"""
    # Format times for gog (RFC3339 format)
    start_str = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str = end_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    cmd = f'calendar events {email} --from "{start_str}" --to "{end_str}" --max 50'
    result = run_gog_command(cmd)

    if not result or 'events' not in result:
        return []

    return result['events']


def format_meeting_time(start_time_str, timezone_str):
    """Format meeting time in user's timezone"""
    # Parse ISO format time
    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))

    # Convert to user's timezone
    user_tz = pytz.timezone(timezone_str)
    local_time = start_time.astimezone(user_tz)

    # Format as "2:30 PM"
    return local_time.strftime('%I:%M %p').lstrip('0')


def send_whatsapp_message(phone, message, max_retries=3, retry_delay=3):
    """Send WhatsApp message via OpenClaw with retry logic.

    Fail fast (3 retries, 3s delay) to avoid blocking reminders for other
    team members. Falls back to email if all retries fail.
    """
    for attempt in range(1, max_retries + 1):
        try:
            cmd = [
                'openclaw', 'message', 'send',
                '--channel', 'whatsapp',
                '--account', WHATSAPP_ACCOUNT,
                '--target', phone,
                '--message', message
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                print(f"  ✓ Sent to {phone}" + (f" (attempt {attempt})" if attempt > 1 else ""))
                return True
            else:
                error_msg = result.stderr.strip()
                print(f"  ✗ Attempt {attempt}/{max_retries} failed for {phone}: {error_msg}", file=sys.stderr)
                if attempt < max_retries:
                    print(f"    Retrying in {retry_delay}s...", file=sys.stderr)
                    time.sleep(retry_delay)
                else:
                    print(f"  ✗ All {max_retries} attempts failed for {phone}", file=sys.stderr)
                    return False
        except Exception as e:
            print(f"  ✗ Attempt {attempt}/{max_retries} exception for {phone}: {e}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                return False
    return False



def send_email_fallback(to_email, name, message):
    """Fallback: send meeting reminder via email when WhatsApp is down"""
    try:
        import tempfile
        subject = f"Meeting Reminder"
        # Extract meeting name from first line if possible
        first_line = message.split('\n')[0] if message else ''
        if first_line:
            subject = f"Meeting Reminder: {first_line.strip()}"
            if len(subject) > 120:
                subject = subject[:117] + '...'

        body = f"Hi {name},\n\n{message}\n\n-- {config.assistant_name} (sent via email because WhatsApp was unavailable)"

        # Write body to temp file to avoid shell escaping issues
        body_file = tempfile.mktemp(suffix='.txt')
        with open(body_file, 'w') as f:
            f.write(body)

        cmd = [
            'gog', 'gmail', 'send',
            '--to', to_email,
            '--subject', subject,
            '--body-file', body_file,
            '--account', GOG_ACCOUNT,
            '--force', '--no-input'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        try:
            os.unlink(body_file)
        except:
            pass

        if result.returncode == 0:
            print(f"  ✓ Email fallback sent to {to_email}")
            return True
        else:
            print(f"  ✗ Email fallback failed for {to_email}: {result.stderr.strip()[:200]}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  ✗ Email fallback exception for {to_email}: {e}", file=sys.stderr)
        return False


def format_attendees(attendees, owner_email):
    """Format attendee list (excluding owner)"""
    if not attendees:
        return "No other attendees"

    # Filter out owner and self-email addresses
    filtered = [a for a in attendees if a != owner_email and '@' in a]

    if not filtered:
        return "No other attendees"

    # Format names (extract before @)
    names = [a.split('@')[0].replace('.', ' ').title() for a in filtered[:3]]

    if len(filtered) > 3:
        return f"{', '.join(names)} and {len(filtered) - 3} others"
    else:
        return ', '.join(names)


def get_external_attendees(attendees, owner_email):
    """Get list of external (non-team-domain) attendee emails"""
    if not attendees:
        return []

    external = []
    for attendee in attendees:
        email = attendee.get('email', '')
        if email and '@' in email and email != owner_email:
            if not email.endswith('@' + config.team_domain):
                external.append(email)

    return external


def search_hubspot_company(email_domain):
    """Search HubSpot for company by domain"""
    if not MATON_API_KEY:
        return None

    try:
        headers = {
            'Authorization': f'Bearer {MATON_API_KEY}',
            'Content-Type': 'application/json'
        }

        # Search for company by domain
        url = f"{MATON_BASE_URL}/companies/search"
        payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "domain",
                    "operator": "EQ",
                    "value": email_domain
                }]
            }],
            "properties": ["name", "domain", "industry", "description"],
            "limit": 1
        }

        response = requests.post(url, headers=headers, json=payload, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data.get('results') and len(data['results']) > 0:
                return data['results'][0]

        return None
    except Exception as e:
        print(f"  Error searching HubSpot: {e}", file=sys.stderr)
        return None


def get_company_deals(company_id):
    """Get active deals for a company"""
    if not MATON_API_KEY or not company_id:
        return []

    try:
        headers = {
            'Authorization': f'Bearer {MATON_API_KEY}',
            'Content-Type': 'application/json'
        }

        # Get deals associated with company
        url = f"{MATON_BASE_URL}/companies/{company_id}/associations/deals"

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            deal_ids = [assoc['id'] for assoc in data.get('results', [])]

            if not deal_ids:
                return []

            # Get deal details
            deals = []
            for deal_id in deal_ids[:3]:  # Limit to 3 most recent deals
                deal_url = f"{MATON_BASE_URL}/deals/{deal_id}"
                deal_response = requests.get(
                    deal_url,
                    headers=headers,
                    params={'properties': 'dealname,dealstage,amount,closedate'},
                    timeout=10
                )

                if deal_response.status_code == 200:
                    deals.append(deal_response.json())

            return deals

        return []
    except Exception as e:
        print(f"  Error fetching deals: {e}", file=sys.stderr)
        return []


def get_latest_note(company_id):
    """Get the latest note/engagement for a company"""
    if not MATON_API_KEY or not company_id:
        return None

    try:
        headers = {
            'Authorization': f'Bearer {MATON_API_KEY}',
            'Content-Type': 'application/json'
        }

        # Get engagements (notes) associated with company
        url = f"{MATON_BASE_URL}/companies/{company_id}/associations/notes"

        response = requests.get(url, headers=headers, params={'limit': 1}, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data.get('results') and len(data['results']) > 0:
                note_id = data['results'][0]['id']

                # Get note details
                note_url = f"{MATON_BASE_URL}/notes/{note_id}"
                note_response = requests.get(note_url, headers=headers, timeout=10)

                if note_response.status_code == 200:
                    note_data = note_response.json()
                    body = note_data.get('properties', {}).get('hs_note_body', '')
                    # Truncate to 200 chars
                    if len(body) > 200:
                        body = body[:200] + '...'
                    return body

        return None
    except Exception as e:
        print(f"  Error fetching notes: {e}", file=sys.stderr)
        return None


def get_hubspot_context(attendees, owner_email):
    """Get HubSpot context for external attendees"""
    external_emails = get_external_attendees(attendees, owner_email)

    if not external_emails:
        return None

    # Try to find company for first external attendee
    first_email = external_emails[0]
    domain = first_email.split('@')[-1]

    print(f"    Looking up HubSpot data for {domain}...")

    company = search_hubspot_company(domain)

    if not company:
        print(f"    No HubSpot company found")
        return None

    company_id = company.get('id')
    company_name = company.get('properties', {}).get('name', domain)
    company_industry = company.get('properties', {}).get('industry', '')

    print(f"    Found company: {company_name}")

    # Get associated deals
    deals = get_company_deals(company_id)

    # Get latest note
    latest_note = get_latest_note(company_id)

    return {
        'company_name': company_name,
        'industry': company_industry,
        'deals': deals,
        'latest_note': latest_note
    }


def format_hubspot_context(context):
    """Format HubSpot context for WhatsApp message"""
    if not context:
        return []

    lines = []

    # Company info
    lines.append("")
    lines.append(f"🏢 {context['company_name']}")

    if context.get('industry'):
        lines.append(f"🏭 {context['industry']}")

    # Deal info
    if context.get('deals'):
        deal = context['deals'][0]  # Show first deal
        deal_name = deal.get('properties', {}).get('dealname', 'Unnamed Deal')
        deal_stage = deal.get('properties', {}).get('dealstage', '')

        # Map stage IDs to readable names
        stage_map = {
            'appointmentscheduled': 'Screening',
            'presentationscheduled': 'First Meeting',
            'qualifiedtobuy': 'Qualified',
            'decisionmakerboughtin': 'Due Diligence',
            'contractsent': 'Term Sheet',
            'closedwon': 'Closed Won',
            'closedlost': 'Passed'
        }

        stage_name = stage_map.get(deal_stage, deal_stage)

        lines.append(f"💼 Deal: {deal_name}")
        if stage_name:
            lines.append(f"📊 Stage: {stage_name}")

    # Latest note
    if context.get('latest_note'):
        lines.append("")
        lines.append("📝 Last Note:")
        lines.append(context['latest_note'])

    return lines


def process_meeting_reminders():
    """Main processing function"""
    # Acquire exclusive lock to prevent overlapping cron runs
    lock_file = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[{datetime.now(pytz.UTC).replace(tzinfo=None).isoformat()}] Another instance is running, skipping.")
        return

    try:
        _do_process_meeting_reminders()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _do_process_meeting_reminders():
    """Inner processing function (called under lock)"""
    print(f"[{datetime.now(pytz.UTC).replace(tzinfo=None).isoformat()}] Starting meeting reminder check...")

    db = ReminderDatabase(DB_PATH)
    now = datetime.now(pytz.UTC).replace(tzinfo=None)

    # Check window: 5-20 minutes from now
    window_start = now + timedelta(minutes=NOTIFICATION_WINDOW_END)
    window_end = now + timedelta(minutes=NOTIFICATION_WINDOW_START)

    print(f"  Checking for meetings between {window_start.strftime('%H:%M')} and {window_end.strftime('%H:%M')} UTC")

    total_notifications = 0

    # Check each team member's calendar
    for email, member in TEAM_MEMBERS.items():
        if not member['enabled']:
            continue

        print(f"\n  Checking {member['name']}'s calendar...")

        # Get upcoming events
        events = get_upcoming_events(email, window_start, window_end)

        if not events:
            print(f"    No upcoming meetings")
            continue

        print(f"    Found {len(events)} meeting(s) in notification window")

        # Process each event
        for event in events:
            event_id = event.get('id')
            summary = event.get('summary', 'Untitled Meeting')
            start_time = event.get('start', {}).get('dateTime')
            location = event.get('location', '')
            conference = event.get('conferenceData', {})
            attendees = event.get('attendees', [])

            if not event_id or not start_time:
                continue

            # Validate meeting time - skip if already started or beyond window
            try:
                from datetime import datetime as dt_parse
                meeting_start = dt_parse.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(pytz.UTC).replace(tzinfo=None)
                
                # Skip if meeting already started
                if meeting_start < now:
                    print(f"    ⏭  Already started: {summary}")
                    continue
                
                # Skip if meeting is beyond notification window
                if meeting_start > window_end:
                    minutes_away = (meeting_start - now).total_seconds() / 60
                    print(f"    ⏭  Too far in future: {summary} ({minutes_away:.1f} min away)")
                    continue

                # Debug: Show meeting is in window
                minutes_away = (meeting_start - now).total_seconds() / 60
                print(f"    ✓ In window: {summary} ({minutes_away:.1f} min away)")
            except Exception as e:
                print(f"    ⚠  Could not parse time for {summary}: {e}")
                pass

            # Skip solo meetings (blocked time / focus time)
            other_attendees = [a for a in attendees if a.get('email', '') != email]
            if not other_attendees:
                print(f"    ⏭  Solo meeting (blocked time): {summary}")
                continue

            # Check if already notified
            if db.is_notified(event_id, email):
                print(f"    ⏭  Already notified: {summary}")
                continue

            # Format meeting details
            meeting_time = format_meeting_time(start_time, member['timezone'])
            attendee_list = format_attendees([a.get('email') for a in attendees], email)

            # Build basic message with actual minutes remaining
            mins_away = int(round(minutes_away))
            message_lines = [
                f"🔔 Meeting in ~{mins_away} minutes:",
                f"",
                f"📅 {summary}",
                f"⏰ {meeting_time}",
                f"👥 {attendee_list}"
            ]

            # Add location/link
            meet_link = None
            if conference and 'entryPoints' in conference:
                for entry in conference['entryPoints']:
                    if entry.get('entryPointType') == 'video':
                        meet_link = entry.get('uri')
                        break

            if meet_link:
                message_lines.append(f"🔗 {meet_link}")
            elif location:
                message_lines.append(f"📍 {location}")

            # Get HubSpot context
            hubspot_context = get_hubspot_context(attendees, email)
            if hubspot_context:
                context_lines = format_hubspot_context(hubspot_context)
                message_lines.extend(context_lines)

            # Enrich external attendees with LinkedIn, Crunchbase, GitHub, News
            if ENRICHMENT_AVAILABLE and attendees:
                enriched_attendees = enrich_external_attendees(attendees, email)
                if enriched_attendees:
                    message_lines.append("")
                    message_lines.append("👥 ATTENDEE CONTEXT:")
                    for enriched in enriched_attendees:
                        message_lines.append(enriched)

            message = '\n'.join(message_lines)

            # Send WhatsApp notification (with SMS fallback)
            print(f"    📤 Sending reminder: {summary}")
            sent = send_whatsapp_message(member['phone'], message)
            if not sent:
                print(f"    📧 WhatsApp failed, falling back to email...")
                sent = send_email_fallback(email, member['name'], message)
            if sent:
                db.mark_notified(event_id, email, start_time)
                total_notifications += 1

    print(f"\n✅ Sent {total_notifications} notification(s)")



def get_next_meeting(email):
    """Get the next upcoming meeting for a user"""
    now = datetime.now(pytz.UTC).replace(tzinfo=None)
    # Look ahead 7 days
    end_time = now + timedelta(days=7)

    # Get all upcoming events
    events = get_upcoming_events(email, now, end_time)

    if not events:
        return None

    # Filter to future events and sort by start time
    future_events = []
    for event in events:
        start_time = event.get('start', {}).get('dateTime')
        if not start_time:
            continue

        try:
            meeting_start = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(pytz.UTC).replace(tzinfo=None)
            if meeting_start > now:
                event['_parsed_start'] = meeting_start
                future_events.append(event)
        except:
            continue

    if not future_events:
        return None

    # Sort by start time and return first
    future_events.sort(key=lambda e: e['_parsed_start'])
    return future_events[0]


def enrich_external_attendees(attendees, owner_email):
    """
    Enrich external attendees with data from LinkedIn, Crunchbase, GitHub, and News

    Returns list of formatted enrichment strings
    """
    if not ENRICHMENT_AVAILABLE:
        return []

    # Get team member emails to filter them out
    team_emails = set(TEAM_MEMBERS.keys())

    enriched_results = []
    service = EnrichmentService()

    for attendee in attendees:
        email = attendee.get('email', '').lower()
        name = attendee.get('displayName', email)

        # Skip team members
        if email in team_emails or email == owner_email.lower():
            continue

        # Skip if email is missing or invalid
        if not email or '@' not in email:
            continue

        # Skip common non-person emails
        if any(x in email for x in ['noreply', 'no-reply', 'calendar', 'bot', 'notification']):
            continue

        try:
            # Enrich this attendee
            enrichment = service.enrich_attendee(email, name, use_cache=True)

            # Only include if we got meaningful data
            has_data = (
                enrichment.get('linkedin') or
                enrichment.get('crunchbase') or
                enrichment.get('github') or
                enrichment.get('recent_news')
            )

            if has_data:
                formatted = service.format_enrichment(enrichment)
                enriched_results.append(formatted)

        except Exception as e:
            print(f"⚠️  Warning: Could not enrich {name} ({email}): {e}")
            continue

    return enriched_results


def format_next_meeting_message(event, member_info):
    """Format a rich message about the next meeting with attendee enrichment"""
    if not event:
        return f"📅 No upcoming meetings found for {member_info['name']}"

    summary = event.get('summary', 'Untitled Meeting')
    start_time = event.get('start', {}).get('dateTime')
    location = event.get('location', '')
    conference = event.get('conferenceData', {})
    attendees = event.get('attendees', [])

    # Calculate time until meeting
    meeting_start = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(pytz.UTC).replace(tzinfo=None)
    now = datetime.now(pytz.UTC).replace(tzinfo=None)
    time_until = meeting_start - now

    # Format time until
    if time_until.days > 0:
        time_until_str = f"in {time_until.days} day(s)"
    elif time_until.seconds >= 3600:
        hours = time_until.seconds // 3600
        time_until_str = f"in {hours} hour(s)"
    else:
        minutes = time_until.seconds // 60
        time_until_str = f"in {minutes} minute(s)"

    # Format meeting time
    meeting_time = format_meeting_time(start_time, member_info['timezone'])
    attendee_list = format_attendees([a.get('email') for a in attendees], member_info.get('email', ''))

    # Build message
    message_lines = [
        f"📅 Your next meeting {time_until_str}:",
        f"",
        f"📝 {summary}",
        f"⏰ {meeting_time}",
        f"👥 {attendee_list}"
    ]

    # Add location/link
    meet_link = None
    if conference and 'entryPoints' in conference:
        for entry in conference['entryPoints']:
            if entry.get('entryPointType') == 'video':
                meet_link = entry.get('uri')
                break

    if meet_link:
        message_lines.append(f"🔗 {meet_link}")
    elif location:
        message_lines.append(f"📍 {location}")

    # Enrich external attendees with LinkedIn, Crunchbase, GitHub, News
    if ENRICHMENT_AVAILABLE and attendees:
        enriched_attendees = enrich_external_attendees(attendees, member_info.get('email', ''))
        if enriched_attendees:
            message_lines.append("")
            message_lines.append("👥 ATTENDEE CONTEXT:")
            for enriched in enriched_attendees:
                message_lines.append(enriched)

    # Get HubSpot context
    hubspot_context = get_hubspot_context(attendees, member_info.get('email', ''))
    if hubspot_context:
        context_lines = format_hubspot_context(hubspot_context)
        message_lines.extend(context_lines)

    return '\n'.join(message_lines)


def query_next_meeting(identifier):
    """Query next meeting by email or phone number"""
    # Find team member by email or phone
    member = None
    member_email = None

    for email, info in TEAM_MEMBERS.items():
        if identifier.lower() == email.lower() or identifier == info['phone']:
            member = info
            member_email = email
            member['email'] = email  # Add email to member dict
            break

    if not member:
        return f"❌ User not found: {identifier}"

    print(f"🔍 Looking up next meeting for {member['name']} ({member_email})...")

    # Get next meeting
    next_meeting = get_next_meeting(member_email)

    # Format message
    message = format_next_meeting_message(next_meeting, member)

    return message


def main():
    """Main entry point"""
    # Check if running in query mode
    if len(sys.argv) > 1 and sys.argv[1] == 'query':
        identifier = sys.argv[2] if len(sys.argv) > 2 else None
        if identifier:
            message = query_next_meeting(identifier)
            print(message)
        else:
            print("Usage: reminders.py query <email|phone>")
            sys.exit(1)
    else:
        # Normal reminder processing mode
        try:
            process_meeting_reminders()
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Fatal error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
