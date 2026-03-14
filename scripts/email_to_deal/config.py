"""Configuration constants, team email lists, sender detection, and opt-in handling."""

import os
import sys
import json
import re
import tempfile
import logging
from datetime import datetime

log = logging.getLogger("email-to-deal")

# Support both local (scripts/../lib/) and server (~/.openclaw/lib/) layouts
# sys.path fixed for gws migration
sys.path.insert(0, os.path.expanduser('~/.openclaw'))
from lib.config import config
from lib.gws import (gws_gmail_search, gws_gmail_thread_get, gws_gmail_modify, gws_gmail_send)

ANTHROPIC_API_KEY = config.anthropic_api_key

TEAM_MEMBERS = {m['email']: m['name'].split()[0] for m in config.team_members}

OWNER_IDS = {m['email']: m.get('hubspot_owner_id', '') for m in config.team_members}

MATON_API_KEY = config.maton_api_key
MATON_BASE_URL = 'https://gateway.maton.ai/hubspot'
# Pipeline config from config.yaml
DEFAULT_PIPELINE = config.hubspot_default_pipeline
DEFAULT_STAGE = config.hubspot_deal_stage

# Build pipeline/stage lookups from config
PIPELINE_NAMES = {p['id']: p['name'] for p in config.hubspot_pipelines}
STAGE_NAMES = {}
for p in config.hubspot_pipelines:
    STAGE_NAMES.update(p.get('stage_names', {}))

# Secondary pipelines (by index in config)
_pipelines = config.hubspot_pipelines
SECONDARY_PIPELINE = _pipelines[1]['id'] if len(_pipelines) > 1 else DEFAULT_PIPELINE
SECONDARY_STAGE = _pipelines[1].get('default_stage', DEFAULT_STAGE) if len(_pipelines) > 1 else DEFAULT_STAGE

PROCESSED_LABEL = 'HubSpot-Processed'
WHATSAPP_ACCOUNT = config.whatsapp_account

TEAM_PHONES = config.team_phones
EMAIL_TO_PHONE = {email: phone for phone, email in TEAM_PHONES.items()}

# Deal analyzer state file (shared with skills/deal-analyzer)
_TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
_DATA_DIR = os.path.join(_TOOLKIT_ROOT, 'data')
os.makedirs(_DATA_DIR, exist_ok=True)
DEAL_ANALYZER_STATE = os.path.join(_DATA_DIR, "deal-analyzer-state.json")


def _is_own_firm_name(name):
    """Check if a name matches our own firm (should never be a deal)."""
    normalized = re.sub(r'[\s\-_]+', '', name).lower()
    domain_base = re.sub(r'[\s\-_\.]+', '', config.team_domain.split('.')[0]).lower()
    # Match domain-based names: "groundup", "groundupventures", "groundupvc", etc.
    return normalized.startswith(domain_base)

def is_lp_email(subject, body):
    """Check if email mentions LP (Limited Partner)"""
    lp_pattern = r'\bLP\b|\bL\.P\.\b|limited partner'
    text_to_check = f'{subject} {body}'
    return bool(re.search(lp_pattern, text_to_check, re.IGNORECASE))

def should_skip_email(subject, body):
    """Check if email should be skipped (not a deal)"""
    # Patterns for system/automated emails to skip
    skip_patterns = [
        r'accept your invitation',
        r'calendar invitation',
        r'event invitation',
        r'shared calendar',
        r'calendar notification',
        r'out of office',
        r'automatic reply',
        r'auto.reply',
        r'delivery status notification',
        r'undeliverable',
        r'mail delivery failed',
        r'meeting accepted',
        r'meeting declined',
        r'meeting tentative',
        r'has accepted',
        r'has declined',
        r'has tentatively accepted'
    ]

    text_to_check = f'{subject} {body}'.lower()

    for pattern in skip_patterns:
        if re.search(pattern, text_to_check, re.IGNORECASE):
            return True

    return False


def check_optin_optout_requests():
    """Check for meeting brief opt-in/opt-out requests using JSON config file."""
    from .notifications import send_email_simple
    from .scanner import mark_email_processed

    _TOOLKIT_ROOT = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
    OPTIN_FILE = os.path.join(_TOOLKIT_ROOT, 'data', 'meeting-brief-optin.json')
    OPTIN_LABEL = 'MeetingBrief-Processed'

    def _load_optin():
        try:
            with open(OPTIN_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_optin(data):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OPTIN_FILE))
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, OPTIN_FILE)
        except Exception:
            os.unlink(tmp)
            raise

    log.debug('Checking opt-in/opt-out requests...')

    team_emails = ' OR '.join([f'from:{email}' for email in TEAM_MEMBERS.keys()])
    query = f'in:inbox -{OPTIN_LABEL} ({team_emails}) (subject:"meeting brief" OR body:"meeting brief") newer_than:1d'

    threads = gws_gmail_search(query, max_results=10)
    if not threads:
        log.debug('No opt-in/out requests')
        return

    log.info('Found %d potential opt-in/out requests', len(threads))

    for thread in threads:
        from_email = thread.get('from', '')
        subject = thread.get('subject', '')
        thread_id = thread.get('id', '')

        sender_match = re.search(r'<(.+?)>', from_email)
        sender_email = sender_match.group(1) if sender_match else from_email

        if sender_email not in TEAM_MEMBERS:
            continue

        # Get thread body
        thread_details = gws_gmail_thread_get(thread_id)
        if not thread_details or 'messages' not in thread_details:
            continue

        body = ""
        for msg in thread_details['messages']:
            body += msg.get('snippet', '') + " "

        text_to_check = f"{subject} {body}".lower()

        opt_in = bool(re.search(r'\bopt\s*in\b', text_to_check))
        opt_out = bool(re.search(r'\bopt\s*out\b', text_to_check))

        if not opt_in and not opt_out:
            continue

        member_name = TEAM_MEMBERS[sender_email]

        try:
            optin_data = _load_optin()
            current_status = optin_data.get(sender_email, {}).get('opted_in', False)

            if opt_in and not current_status:
                optin_data[sender_email] = {'opted_in': True, 'updated_at': datetime.now().isoformat()}
                _save_optin(optin_data)
                log.info('Opted in: %s (%s)', member_name, sender_email)

                confirmation = f"""Hi {member_name},

You've been successfully opted in to Smart Meeting Briefs!

You'll receive intelligent meeting prep via WhatsApp 10 minutes before each meeting with:
- HubSpot deal context
- Smart questions based on deal stage
- Attendee information

Make sure your calendar is shared with {config.assistant_email}

To opt out: email "opt out of meeting briefs"

- Meeting Brief Bot"""

                send_email_simple(sender_email, "Meeting Briefs - Opted In", confirmation)

            elif opt_out and current_status:
                optin_data[sender_email] = {'opted_in': False, 'updated_at': datetime.now().isoformat()}
                _save_optin(optin_data)
                log.info('Opted out: %s (%s)', member_name, sender_email)

                confirmation = f"""Hi {member_name},

You've been opted out of Smart Meeting Briefs.

You won't receive any more meeting prep messages.

To opt back in: email "opt in to meeting briefs"

- Meeting Brief Bot"""

                send_email_simple(sender_email, "Meeting Briefs - Opted Out", confirmation)

            else:
                action = "opted in" if current_status else "opted out"
                log.debug('%s already %s', member_name, action)

            # Mark as processed
            mark_email_processed(thread_id)

        except Exception as e:
            log.error('Error processing opt-in/out: %s', e)
