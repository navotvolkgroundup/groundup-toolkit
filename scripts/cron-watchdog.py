#!/usr/bin/env python3
"""Cron Watchdog — alerts when scheduled jobs stop running.

Checks log file modification times against expected intervals.
If a job's log hasn't been updated in 2x its interval, sends a WhatsApp alert.
Deduplicates alerts so you only get notified once per incident.

Usage:
    python3 scripts/cron-watchdog.py check
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.atomic_write import atomic_json_write
from lib.whatsapp import send_whatsapp
from lib.config import config

LOG_DIR = '/var/log'

# job_name -> (log_file, expected_interval_seconds)
EXPECTED_JOBS = {
    'email-to-deal': ('deal-automation.log', 600),        # every 10 min
    'meeting-reminders': ('meeting-reminders.log', 300),   # every 5 min
    'meeting-auto-join': ('meeting-auto-join.log', 60),     # every 1 min
    'meeting-bot': ('meeting-bot.log', 7200),              # every 2 hours
    'founder-scout': ('founder-scout.log', 86400),         # daily
    'health-check': ('toolkit-health.log', 900),           # every 15 min
}

# Alert if log hasn't updated in 2x the expected interval
STALENESS_MULTIPLIER = 2

STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'cron-watchdog-state.json')


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state):
    atomic_json_write(STATE_FILE, state)


def check_jobs():
    """Check all expected jobs and return list of stale ones."""
    now = time.time()
    stale = []

    for job_name, (log_file, interval) in EXPECTED_JOBS.items():
        log_path = os.path.join(LOG_DIR, log_file)

        if not os.path.isfile(log_path):
            stale.append((job_name, log_file, 'missing'))
            continue

        try:
            mtime = os.path.getmtime(log_path)
        except OSError:
            stale.append((job_name, log_file, 'unreadable'))
            continue

        age = now - mtime
        threshold = interval * STALENESS_MULTIPLIER

        if age > threshold:
            hours = age / 3600
            stale.append((job_name, log_file, f'stale ({hours:.1f}h)'))

    return stale


def cmd_check():
    stale = check_jobs()

    if not stale:
        print('All cron jobs running on schedule.')
        return

    state = _load_state()
    now_iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    new_alerts = []

    for job_name, log_file, reason in stale:
        if job_name in state:
            # Already alerted — skip
            continue
        state[job_name] = now_iso
        new_alerts.append((job_name, reason))

    # Clear recovered jobs
    for job_name in list(state.keys()):
        if job_name not in dict((s[0], s[2]) for s in stale):
            del state[job_name]
            print(f'  Recovered: {job_name}')

    _save_state(state)

    if not new_alerts:
        print(f'{len(stale)} stale job(s), already alerted.')
        return

    # Build alert message
    lines = [f'Cron Watchdog — {len(new_alerts)} job(s) overdue:']
    for job_name, reason in new_alerts:
        lines.append(f'  • {job_name}: {reason}')

    msg = '\n'.join(lines)
    print(msg)

    phone = config.alert_phone
    if phone:
        if send_whatsapp(phone, msg):
            print('Alert sent via WhatsApp.')
        else:
            print('Failed to send WhatsApp alert.', file=sys.stderr)
    else:
        print('No alert_phone configured — skipping WhatsApp.', file=sys.stderr)


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] != 'check':
        print(f'Usage: {sys.argv[0]} check')
        sys.exit(1)
    cmd_check()
