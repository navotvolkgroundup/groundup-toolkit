"""Email scanning, Gmail connection, message fetching, and WhatsApp message checking."""

import os
import json
import re
import logging
import glob
from datetime import datetime, timedelta

log = logging.getLogger("email-to-deal")

from lib.gws import (gws_gmail_search, gws_gmail_thread_get, gws_gmail_modify,
                      gws_gmail_attachment_download)

from .config import (TEAM_MEMBERS, TEAM_PHONES, PROCESSED_LABEL)


def check_recent_emails():
    """Check for new emails via gws."""
    log.debug('Checking for new emails...')
    team_emails = ' OR '.join([f'from:{email}' for email in TEAM_MEMBERS.keys()])
    query = f'in:inbox -{PROCESSED_LABEL} ({team_emails}) newer_than:48h'
    return gws_gmail_search(query, max_results=100)


def get_email_body(thread_id):
    """Get email body via gws."""
    result = gws_gmail_thread_get(thread_id)
    if result and 'messages' in result:
        for msg in result['messages']:
            body = msg.get('snippet', '')
            return body
    return ''


def mark_email_processed(thread_id):
    """Add processed label, mark as read, and archive via gws."""
    result = gws_gmail_modify(thread_id, add_labels=[PROCESSED_LABEL], remove_labels=['UNREAD', 'INBOX'])
    if result is not None:
        log.info('Marked email as processed and archived')
        return True
    else:
        # Fallback: just archive without label
        log.warning('Could not add label, archiving anyway')
        fallback = gws_gmail_modify(thread_id, remove_labels=['UNREAD', 'INBOX'])
        if fallback is not None:
            log.info('Archived email (without label)')
            return True
        else:
            log.error('Error archiving email')
            return False


def check_roastmydeck_emails():
    """Check for new RoastMyDeck analysis emails."""
    log.debug('Checking RoastMyDeck emails...')
    query = f"in:inbox -{PROCESSED_LABEL} subject:[RoastMyDeck] newer_than:48h"
    return gws_gmail_search(query, max_results=100)


def get_email_attachments(thread_id):
    """Get list of PDF/PPTX attachments from email via gws."""
    result = gws_gmail_thread_get(thread_id)
    if not result:
        return []

    attachments = []
    try:
        # gws_gmail_thread_get returns {messages: [...]} directly (no 'thread' wrapper)
        messages = result.get('messages', [])
        for message in messages:
            payload = message.get('payload', {})
            parts = payload.get('parts', [])

            for part in parts:
                filename = part.get('filename', '')
                if filename.lower().endswith(('.pdf', '.pptx', '.ppt')):
                    attachment_id = part.get('body', {}).get('attachmentId')
                    if attachment_id:
                        attachments.append({
                            'id': attachment_id,
                            'filename': filename,
                            'message_id': message.get('id')
                        })
    except Exception as e:
        log.error('Error getting attachments: %s', e)

    return attachments


def download_attachment(message_id, attachment_id, filename):
    """Download attachment via gws."""
    import tempfile as _tempfile
    try:
        safe_filename = os.path.basename(filename)
        safe_filename = re.sub(r'[^\w.\-]', '_', safe_filename)
        if not safe_filename:
            safe_filename = 'attachment.pdf'

        temp_dir = _tempfile.gettempdir()
        output_path = os.path.join(temp_dir, safe_filename)

        if not os.path.realpath(output_path).startswith(os.path.realpath(temp_dir)):
            log.error('Security: rejected suspicious filename: %s', filename)
            return None

        success = gws_gmail_attachment_download(message_id, attachment_id, output_path)
        if success and os.path.exists(output_path):
            return output_path
        else:
            log.error('Error downloading attachment')
            return None
    except Exception as e:
        log.error('Error downloading attachment: %s', e)
        return None


def extract_pdf_text(pdf_path):
    """Extract text from PDF using pdftotext"""
    import subprocess
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception as e:
        log.error('Error extracting PDF text: %s', e)
        return None


def check_whatsapp_deals():
    """Check for WhatsApp messages with company/deal submissions from OpenClaw sessions"""
    log.debug('Checking WhatsApp deal submissions...')

    sessions_dir = os.path.expanduser('~/.openclaw/agents/main/sessions')
    processed_log = os.path.expanduser('~/.openclaw/whatsapp-processed.txt')

    if not os.path.exists(sessions_dir):
        log.debug('OpenClaw sessions directory not found')
        return

    # Read processed message IDs
    processed_ids = set()
    if os.path.exists(processed_log):
        with open(processed_log, 'r') as f:
            processed_ids = set(line.strip() for line in f)

    # Find recent session files (modified in last 24 hours)
    try:
        session_files = glob.glob(f'{sessions_dir}/*.jsonl')
        recent_files = []

        cutoff_time = datetime.now() - timedelta(hours=24)
        for filepath in session_files:
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            if mtime > cutoff_time:
                recent_files.append(filepath)

        if not recent_files:
            log.debug('No recent sessions')
            return

        # Parse WhatsApp messages from session files
        messages = []
        for filepath in recent_files:
            try:
                with open(filepath, 'r') as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            if data.get('type') == 'message' and data.get('message', {}).get('role') == 'user':
                                content = data.get('message', {}).get('content', [])
                                for item in content:
                                    if item.get('type') == 'text':
                                        text = item.get('text', '')
                                        # Check for WhatsApp message format
                                        # [WhatsApp +phone timestamp] message [message_id: ID]
                                        match = re.search(r'\[WhatsApp (\+\d+)[^\]]+\] (.+?)\s*\[message_id:\s*([^\]]+)\]', text, re.DOTALL)
                                        if match:
                                            phone, message, msg_id = match.groups()
                                            if msg_id not in processed_ids:
                                                messages.append({
                                                    'phone': phone,
                                                    'message': message.strip(),
                                                    'id': msg_id,
                                                    'timestamp': data.get('timestamp', '')
                                                })
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                continue

        if not messages:
            log.debug('No new WhatsApp messages')
            return

        log.info('Found %d new WhatsApp messages', len(messages))

        # Import here to avoid circular imports
        from . import process_whatsapp_deal

        for msg in messages:
            phone = msg['phone']
            message = msg['message']
            msg_id = msg['id']

            # Check if from team member
            if phone not in TEAM_PHONES:
                continue

            sender_email = TEAM_PHONES[phone]
            sender_name = TEAM_MEMBERS[sender_email]


            # Only process messages with EXPLICIT deal submission keywords
            message_lower = message.lower()

            # Skip bot messages (reflected openclaw messages)
            if message_lower.startswith('[openclaw]'):
                with open(processed_log, 'a') as f:
                    f.write(f'{msg_id}\n')
                continue

            # Require explicit deal keywords - no guessing from short messages
            deal_keywords = ['deal:', 'company:', 'pitch:', 'deck:', 'startup:', 'new deal', 'log deal', 'add deal']
            has_keyword = any(kwd in message_lower for kwd in deal_keywords)

            # Also accept forwarded deal emails
            is_forwarded_deal = bool(re.match(r'^(fwd|forward):', message_lower))

            if has_keyword or is_forwarded_deal:
                log.info('Processing deal from %s (%s)', sender_name, phone)
                log.debug('Message: %s', message[:100])
                process_whatsapp_deal(msg, sender_email, sender_name, phone)

                # Mark as processed
                with open(processed_log, 'a') as f:
                    f.write(f'{msg_id}\n')
            else:
                # Mark as processed but don't create deal
                with open(processed_log, 'a') as f:
                    f.write(f'{msg_id}\n')

    except Exception as e:
        log.error('Error checking WhatsApp: %s', e)
