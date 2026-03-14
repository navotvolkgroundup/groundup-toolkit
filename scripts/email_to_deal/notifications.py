"""WhatsApp and email notifications, confirmation messages."""

import subprocess
import logging

log = logging.getLogger("email-to-deal")

from lib.gws import gws_gmail_send

from .config import WHATSAPP_ACCOUNT


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


def send_confirmation_email(to_email, company_name, pipeline_name, stage_name, deal_url):
    """Send confirmation email to the sender via gws."""
    message = f"""Hi,

Your email about {company_name} has been processed and added to HubSpot:

Pipeline: {pipeline_name}
Stage: {stage_name}

View deal: {deal_url}

- Deal Automation Bot
"""

    subject = f'Deal Created: {company_name}'
    result = gws_gmail_send(to_email, subject, message)
    if result:
        log.info('Sent confirmation email to %s', to_email)
        return True
    else:
        log.error('Error sending confirmation')
        return False


def send_email_simple(to_email, subject, body):
    """Send email via gws."""
    result = gws_gmail_send(to_email, subject, body)
    if result:
        log.info('Sent confirmation email to %s', to_email)
        return True
    else:
        log.error('Error sending email')
        return False
