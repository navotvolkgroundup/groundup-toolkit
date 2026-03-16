#!/usr/bin/env python3
"""
Meeting Reminder Automation - GroundUp Toolkit
Enhanced with: AI briefs, email context, stage-aware tips, previous meeting context,
and post-meeting nudge (for deals only).
"""

import os
import sys
import sqlite3
import fcntl
from datetime import datetime, timedelta
import pytz

# Shared config loader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.structured_log import get_logger
log = get_logger("meeting-reminders")

from lib.config import config
from lib.whatsapp import send_whatsapp
from lib.gws import gws_gmail_send

# Module imports (same directory, not a package)
from calendar_checker import (
    get_upcoming_events, format_meeting_time,
    get_previous_meeting_context, get_next_meeting,
)
from attendee_enricher import (
    TEAM_MEMBERS, STAGE_MAP, ENRICHMENT_AVAILABLE,
    format_attendees, get_external_attendees, is_internal_meeting,
    search_hubspot_company, get_company_deals,
    get_hubspot_context, get_deal_stage_info,
    get_recent_email_context, enrich_external_attendees,
    generate_ai_brief,
)

WHATSAPP_ACCOUNT = config.whatsapp_account

# Persistent database path (survives reboots, unlike /tmp)
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, mode=0o700, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "meeting-reminders.db")
LOCK_PATH = os.path.join(_DATA_DIR, "meeting-reminders.lock")

# Notification window: 5-20 minutes before meeting
NOTIFICATION_WINDOW_START = 20  # minutes before meeting (far edge)
NOTIFICATION_WINDOW_END = 5     # minutes before meeting (near edge)

# Post-meeting nudge: 30-40 minutes after meeting ended
NUDGE_WINDOW_START = 30
NUDGE_WINDOW_END = 40


class ReminderDatabase:
    """Track which meetings have been notified and nudged"""

    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if table exists with old schema (event_id-only PK).
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='notified_meetings'")
        row = cursor.fetchone()
        if row and 'PRIMARY KEY (event_id, email)' not in row[0]:
            cursor.execute('DROP TABLE notified_meetings')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notified_meetings (
                event_id TEXT NOT NULL,
                email TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                meeting_start TEXT NOT NULL,
                PRIMARY KEY (event_id, email)
            )
        ''')

        # Post-meeting nudge tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nudged_meetings (
                event_id TEXT NOT NULL,
                email TEXT NOT NULL,
                nudged_at TEXT NOT NULL,
                PRIMARY KEY (event_id, email)
            )
        ''')

        # Clean up old records (older than 48 hours)
        cutoff = (datetime.now(pytz.UTC).replace(tzinfo=None) - timedelta(hours=48)).isoformat()
        cursor.execute('DELETE FROM notified_meetings WHERE notified_at < ?', (cutoff,))
        cursor.execute('DELETE FROM nudged_meetings WHERE nudged_at < ?', (cutoff,))
        conn.commit()
        conn.close()

    def is_notified(self, event_id, email):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM notified_meetings WHERE event_id = ? AND email = ?', (event_id, email))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def mark_notified(self, event_id, email, meeting_start):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO notified_meetings (event_id, email, notified_at, meeting_start) VALUES (?, ?, ?, ?)',
            (event_id, email, datetime.now(pytz.UTC).replace(tzinfo=None).isoformat(), meeting_start)
        )
        conn.commit()
        conn.close()

    def is_nudged(self, event_id, email):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM nudged_meetings WHERE event_id = ? AND email = ?', (event_id, email))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def mark_nudged(self, event_id, email):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO nudged_meetings (event_id, email, nudged_at) VALUES (?, ?, ?)',
            (event_id, email, datetime.now(pytz.UTC).replace(tzinfo=None).isoformat())
        )
        conn.commit()
        conn.close()

    def get_notified_meetings_ending_between(self, start, end):
        """Get meetings that were notified and ended in the given window."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT event_id, email, meeting_start FROM notified_meetings WHERE meeting_start BETWEEN ? AND ?',
            (start.isoformat(), end.isoformat())
        )
        results = cursor.fetchall()
        conn.close()
        return results


def send_whatsapp_message(phone, message, max_retries=3, retry_delay=3):
    """Send WhatsApp message via OpenClaw with retry logic."""
    return send_whatsapp(phone, message, account=WHATSAPP_ACCOUNT,
                         max_retries=max_retries, retry_delay=retry_delay)


def send_email_fallback(to_email, name, message):
    """Fallback: send meeting reminder via email when WhatsApp is down"""
    try:
        subject = "Meeting Reminder"
        first_line = message.split('\n')[0] if message else ''
        if first_line:
            subject = f"Meeting Reminder: {first_line.strip()}"
            if len(subject) > 120:
                subject = subject[:117] + '...'
        body = f"Hi {name},\n\n{message}\n\n-- {config.assistant_name} (sent via email because WhatsApp was unavailable)"
        if gws_gmail_send(to_email, subject, body):
            print(f"  ✓ Email fallback sent to {to_email}")
            return True
        else:
            print(f"  ✗ Email fallback failed for {to_email}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  ✗ Email fallback exception for {to_email}: {e}", file=sys.stderr)
        return False


def process_post_meeting_nudges(db):
    """Send follow-up nudges after meetings that have a HubSpot deal."""
    now = datetime.now(pytz.UTC).replace(tzinfo=None)

    # Look for meetings that ended 30-40 minutes ago
    nudge_start = now - timedelta(minutes=NUDGE_WINDOW_END)
    nudge_end = now - timedelta(minutes=NUDGE_WINDOW_START)

    print(f"\n  Checking for post-meeting nudges (meetings ended {NUDGE_WINDOW_START}-{NUDGE_WINDOW_END}m ago)...")

    nudge_count = 0

    for email, member in TEAM_MEMBERS.items():
        if not member['enabled']:
            continue

        # Get events that ended in the nudge window
        # We fetch events that started up to 2 hours before the nudge window end
        fetch_start = nudge_start - timedelta(hours=2)
        events = get_upcoming_events(email, fetch_start, nudge_end)

        if not events:
            continue

        for event in events:
            event_id = event.get('id')
            if not event_id:
                continue

            # Calculate event end time
            end_time_str = event.get('end', {}).get('dateTime')
            if not end_time_str:
                continue

            try:
                event_end = datetime.fromisoformat(end_time_str.replace('Z', '+00:00')).astimezone(pytz.UTC).replace(tzinfo=None)
            except Exception:
                continue

            # Check if the meeting ended in our nudge window
            if not (nudge_start <= event_end <= nudge_end):
                continue

            # Skip if already nudged
            if db.is_nudged(event_id, email):
                continue

            # Skip solo meetings
            attendees = event.get('attendees', [])
            other_attendees = [a for a in attendees if a.get('email', '') != email]
            if not other_attendees:
                continue

            # Skip internal meetings
            if is_internal_meeting(attendees, email):
                continue

            # Only nudge if there's a HubSpot deal
            external_emails = get_external_attendees(attendees, email)
            if not external_emails:
                continue

            first_email = external_emails[0]
            domain = first_email.split('@')[-1]
            company = search_hubspot_company(domain)

            if not company:
                print(f"    ⏭  No HubSpot company for {domain}, skipping nudge")
                continue

            company_id = company.get('id')
            company_name = company.get("properties", {}).get("name") or domain
            deals = get_company_deals(company_id)

            if not deals:
                print(f"    ⏭  No deals for {company_name}, skipping nudge")
                continue

            # We have a deal — send the nudge
            summary = event.get('summary', 'your meeting')
            deal_name = deals[0].get('properties', {}).get('dealname', company_name)
            stage_id = deals[0].get('properties', {}).get('dealstage', '')
            stage_label = STAGE_MAP.get(stage_id, {}).get('label', stage_id)

            nudge_msg = (
                f"👋 How did \"{summary}\" go?\n"
                f"\n"
                f"📋 Deal: {deal_name} ({stage_label})\n"
                f"\n"
                f"Quick options:\n"
                f"• Reply with a note and I'll log it to HubSpot\n"
                f"• \"move to [stage]\" to update the deal stage\n"
                f"• \"pass\" if we're not moving forward"
            )

            print(f"    📤 Sending post-meeting nudge: {summary} → {member['name']}")
            sent = send_whatsapp_message(member['phone'], nudge_msg)
            if sent:
                db.mark_nudged(event_id, email)
                nudge_count += 1

    print(f"  📬 Sent {nudge_count} post-meeting nudge(s)")


# ============================================================
# Main reminder processing
# ============================================================

def process_meeting_reminders():
    """Main processing function"""
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

    for email, member in TEAM_MEMBERS.items():
        if not member['enabled']:
            continue

        print(f"\n  Checking {member['name']}'s calendar...")

        events = get_upcoming_events(email, window_start, window_end)

        if not events:
            print(f"    No upcoming meetings")
            continue

        print(f"    Found {len(events)} meeting(s) in notification window")

        for event in events:
            event_id = event.get('id')
            summary = event.get('summary', 'Untitled Meeting')
            start_time = event.get('start', {}).get('dateTime')
            location = event.get('location', '')
            conference = event.get('conferenceData', {})
            attendees = event.get('attendees', [])

            if not event_id or not start_time:
                continue

            # Validate meeting time
            try:
                meeting_start = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(pytz.UTC).replace(tzinfo=None)
                if meeting_start < now:
                    print(f"    ⏭  Already started: {summary}")
                    continue
                if meeting_start > window_end:
                    minutes_away = (meeting_start - now).total_seconds() / 60
                    print(f"    ⏭  Too far in future: {summary} ({minutes_away:.1f} min away)")
                    continue
                minutes_away = (meeting_start - now).total_seconds() / 60
                print(f"    ✓ In window: {summary} ({minutes_away:.1f} min away)")
            except Exception as e:
                print(f"    Warning: Could not parse time for {summary}: {e}")
                continue

            # Skip solo meetings (blocked time)
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
            internal = is_internal_meeting(attendees, email)

            mins_away = int(round(minutes_away))
            message_lines = [
                f"🔔 Meeting in ~{mins_away} minutes:",
                f"",
                f"📅 {summary}",
                f"⏰ {meeting_time}",
            ]

            # Attendees for external meetings
            if not internal:
                attendee_list = format_attendees([a.get('email') for a in attendees], email)
                message_lines.append(f"👥 {attendee_list}")

            # Meeting link / location
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

            # --- Enhanced context for external meetings ---
            hubspot_context = None
            email_context = None
            previous_meetings = None
            stage_info = None
            ai_brief = None

            if not internal:
                external_emails = get_external_attendees(attendees, email)
                external_domains = set()
                for ext_email in external_emails:
                    if '@' in ext_email:
                        external_domains.add(ext_email.split('@')[-1])

                # HubSpot context
                hubspot_context = get_hubspot_context(attendees, email)

                # Stage-aware suggestions
                if hubspot_context and hubspot_context.get('deals'):
                    _, stage_info = get_deal_stage_info(hubspot_context['deals'])

                # Extract external attendee names for name-based search
                ext_attendee_names = []
                for a in (attendees or []):
                    if isinstance(a, dict):
                        ae = a.get('email', '')
                        if ae in external_emails and a.get('displayName'):
                            ext_attendee_names.append(a['displayName'])

                # Recent email threads
                print(f"    📧 Searching recent emails...")
                email_context = get_recent_email_context(external_emails, attendee_names=ext_attendee_names)

                # Previous meetings with this contact
                print(f"    📅 Checking previous meetings...")
                previous_meetings = get_previous_meeting_context(email, external_domains, event_id, external_emails=external_emails)

                # Enrichment
                if ENRICHMENT_AVAILABLE and attendees:
                    enriched_attendees = enrich_external_attendees(attendees, email)
                    if enriched_attendees:
                        message_lines.append("")
                        message_lines.append("👥 ATTENDEE CONTEXT:")
                        for enriched in enriched_attendees:
                            message_lines.append(enriched)

                # HubSpot details (company, deal, note)
                if hubspot_context:
                    message_lines.append("")
                    message_lines.append(f"🏢 {hubspot_context['company_name']}")
                    if hubspot_context.get('industry'):
                        message_lines.append(f"🏭 {hubspot_context['industry']}")
                    if hubspot_context.get('deals'):
                        deal = hubspot_context['deals'][0]
                        deal_name = deal.get('properties', {}).get('dealname', 'Unnamed Deal')
                        deal_stage = deal.get('properties', {}).get('dealstage', '')
                        stage_label = STAGE_MAP.get(deal_stage, {}).get('label', deal_stage)
                        message_lines.append(f"💼 Deal: {deal_name}")
                        if stage_label:
                            message_lines.append(f"📊 Stage: {stage_label}")
                    if hubspot_context.get('latest_note'):
                        message_lines.append("")
                        message_lines.append("📝 Last Note:")
                        message_lines.append(hubspot_context['latest_note'])

                # Previous meetings
                if previous_meetings:
                    message_lines.append("")
                    message_lines.append("🕐 Previous meetings:")
                    message_lines.append(previous_meetings)

                # Email thread context
                if email_context:
                    message_lines.append("")
                    message_lines.append("📧 Recent emails:")
                    message_lines.append(email_context)

                # AI Brief — the star of the show
                attendee_names = format_attendees([a.get('email') for a in attendees], email)
                print(f"    🤖 Generating AI brief...")
                ai_brief = generate_ai_brief(
                    summary, member['name'], attendee_names,
                    hubspot_context, email_context, previous_meetings, stage_info
                )

                if ai_brief:
                    message_lines.append("")
                    message_lines.append("💡 PREP BRIEF:")
                    message_lines.append(ai_brief)
                elif stage_info:
                    # Fallback: just show stage tips if AI brief failed
                    message_lines.append("")
                    message_lines.append(f"💡 {stage_info['tips']}")

            message = '\n'.join(message_lines)

            # Send
            print(f"    📤 Sending reminder: {summary}")
            sent = send_whatsapp_message(member['phone'], message)
            if not sent:
                print(f"    📧 WhatsApp failed, falling back to email...")
                sent = send_email_fallback(email, member['name'], message)
            if sent:
                db.mark_notified(event_id, email, start_time)
                total_notifications += 1

    print(f"\n✅ Sent {total_notifications} reminder(s)")

    # Post-meeting nudges
    process_post_meeting_nudges(db)


# ============================================================
# Query mode
# ============================================================

def format_next_meeting_message(event, member_info):
    """Format a rich message about the next meeting with attendee enrichment"""
    if not event:
        return f"📅 No upcoming meetings found for {member_info['name']}"

    summary = event.get('summary', 'Untitled Meeting')
    start_time = event.get('start', {}).get('dateTime')
    location = event.get('location', '')
    conference = event.get('conferenceData', {})
    attendees = event.get('attendees', [])

    meeting_start = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(pytz.UTC).replace(tzinfo=None)
    now = datetime.now(pytz.UTC).replace(tzinfo=None)
    time_until = meeting_start - now

    if time_until.days > 0:
        time_until_str = f"in {time_until.days} day(s)"
    elif time_until.seconds >= 3600:
        hours = time_until.seconds // 3600
        time_until_str = f"in {hours} hour(s)"
    else:
        minutes = time_until.seconds // 60
        time_until_str = f"in {minutes} minute(s)"

    meeting_time = format_meeting_time(start_time, member_info['timezone'])
    internal = is_internal_meeting(attendees, member_info.get('email', ''))

    message_lines = [
        f"📅 Your next meeting {time_until_str}:",
        f"",
        f"📝 {summary}",
        f"⏰ {meeting_time}",
    ]

    if not internal:
        attendee_list = format_attendees([a.get('email') for a in attendees], member_info.get('email', ''))
        message_lines.append(f"👥 {attendee_list}")

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

    if not internal:
        if ENRICHMENT_AVAILABLE and attendees:
            enriched_attendees = enrich_external_attendees(attendees, member_info.get('email', ''))
            if enriched_attendees:
                message_lines.append("")
                message_lines.append("👥 ATTENDEE CONTEXT:")
                for enriched in enriched_attendees:
                    message_lines.append(enriched)

        hubspot_context = get_hubspot_context(attendees, member_info.get('email', ''))
        if hubspot_context:
            message_lines.append("")
            message_lines.append(f"🏢 {hubspot_context['company_name']}")
            if hubspot_context.get('industry'):
                message_lines.append(f"🏭 {hubspot_context['industry']}")
            if hubspot_context.get('deals'):
                deal = hubspot_context['deals'][0]
                deal_name = deal.get('properties', {}).get('dealname', 'Unnamed Deal')
                deal_stage = deal.get('properties', {}).get('dealstage', '')
                stage_label = STAGE_MAP.get(deal_stage, {}).get('label', deal_stage)
                message_lines.append(f"💼 Deal: {deal_name}")
                if stage_label:
                    message_lines.append(f"📊 Stage: {stage_label}")
            if hubspot_context.get('latest_note'):
                message_lines.append("")
                message_lines.append("📝 Last Note:")
                message_lines.append(hubspot_context['latest_note'])

    return '\n'.join(message_lines)


def query_next_meeting(identifier):
    """Query next meeting by email or phone number"""
    member = None
    member_email = None

    for email_addr, info in TEAM_MEMBERS.items():
        if identifier.lower() == email_addr.lower() or identifier == info['phone']:
            member = info
            member_email = email_addr
            member['email'] = email_addr
            break

    if not member:
        return f"❌ User not found: {identifier}"

    print(f"🔍 Looking up next meeting for {member['name']} ({member_email})...")

    next_meeting = get_next_meeting(member_email)
    message = format_next_meeting_message(next_meeting, member)
    return message


def main():
    """Main entry point"""
    if len(sys.argv) > 1 and sys.argv[1] == 'query':
        identifier = sys.argv[2] if len(sys.argv) > 2 else None
        if identifier:
            message = query_next_meeting(identifier)
            print(message)
        else:
            print("Usage: reminders.py query <email|phone>")
            sys.exit(1)
    else:
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
