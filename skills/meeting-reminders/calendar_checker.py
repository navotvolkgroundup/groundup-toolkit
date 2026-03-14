"""
Calendar API calls, event fetching, and time window logic.
Extracted from reminders.py as part of modular refactoring.
"""

import os
import sys
from datetime import datetime, timedelta
import pytz

# Shared config loader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config
from lib.gws import gws_calendar_events


def get_upcoming_events(email, start_time, end_time):
    """Get calendar events in time range via gws-auth."""
    time_min = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    time_max = end_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    return gws_calendar_events(email, time_min, time_max, max_results=50)


def format_meeting_time(start_time_str, timezone_str):
    """Format meeting time in user's timezone"""
    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
    user_tz = pytz.timezone(timezone_str)
    local_time = start_time.astimezone(user_tz)
    return local_time.strftime('%I:%M %p').lstrip('0')


def get_previous_meeting_context(email, external_domains, current_event_id,
                                  external_emails=None):
    """Find previous calendar meetings with the same external attendees.

    Uses exact email matching when available. Falls back to domain matching
    only for company-specific domains (skips generic providers like gmail.com).
    """
    # Generic email providers — domain matching is useless for these
    GENERIC_DOMAINS = {
        'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'icloud.com',
        'live.com', 'aol.com', 'protonmail.com', 'me.com', 'mail.com',
        'googlemail.com', 'msn.com', 'ymail.com',
    }

    # Build match sets
    exact_emails = set()
    if external_emails:
        for e in external_emails:
            addr = e if isinstance(e, str) else e.get('email', '')
            if '@' in addr:
                exact_emails.add(addr.lower())

    # Only use domain matching for company domains, not generic ones
    match_domains = set()
    if external_domains:
        for d in external_domains:
            if d and d not in GENERIC_DOMAINS and d != config.team_domain:
                match_domains.add(d)

    if not exact_emails and not match_domains:
        return None

    now = datetime.now(pytz.UTC).replace(tzinfo=None)
    lookback_start = now - timedelta(days=90)

    try:
        events = get_upcoming_events(email, lookback_start, now)
        if not events:
            return None

        past_meetings = []
        for event in events:
            eid = event.get('id')
            if eid == current_event_id:
                continue

            attendees = event.get('attendees', [])
            attendee_emails_list = [a.get('email', '').lower() for a in attendees]

            # Check for exact email match first (always reliable)
            has_match = bool(exact_emails & set(attendee_emails_list))

            # Fall back to domain matching only for company domains
            if not has_match and match_domains:
                for ae in attendee_emails_list:
                    if '@' in ae:
                        domain = ae.split('@')[-1]
                        if domain in match_domains:
                            has_match = True
                            break

            if has_match:
                start = event.get('start', {}).get('dateTime', '')
                summary = event.get('summary', 'Untitled')
                if start:
                    try:
                        dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(pytz.UTC).replace(tzinfo=None)
                        days_ago = (now - dt).days
                        past_meetings.append({
                            'summary': summary,
                            'days_ago': days_ago,
                            'date': dt.strftime('%b %d'),
                        })
                    except Exception:
                        pass

        if not past_meetings:
            return None

        past_meetings.sort(key=lambda m: m['days_ago'])
        lines = []
        for m in past_meetings[:3]:
            lines.append(f"• {m['summary']} ({m['date']}, {m['days_ago']}d ago)")

        return '\n'.join(lines)

    except Exception as e:
        print(f"    Previous meeting lookup error: {e}", file=sys.stderr)
        return None


def get_next_meeting(email):
    """Get the next upcoming meeting for a user"""
    now = datetime.now(pytz.UTC).replace(tzinfo=None)
    end_time = now + timedelta(days=7)
    events = get_upcoming_events(email, now, end_time)

    if not events:
        return None

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
        except Exception:
            continue

    if not future_events:
        return None

    future_events.sort(key=lambda e: e['_parsed_start'])
    return future_events[0]
