#!/usr/bin/env python3
"""Log watcher — monitors GroundUp skill logs for errors.
Usage: log-watcher.py scan|alert|digest
"""
import os, sys, re, json, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.expanduser('~/.openclaw'))
from lib.config import config
from lib.whatsapp import send_whatsapp

LOG_DIR = '/var/log'
LOG_FILES = [
    'meeting-bot.log', 'meeting-auto-join.log', 'deal-automation.log',
    'meeting-reminders.log', 'founder-scout.log', 'founder-briefs.log',
    'keep-on-radar.log', 'christina.log', 'daily-backup.log',
    'daily-maintenance.log', 'meeting-session-health.log',
]
ERROR_RE = re.compile(
    r'(ERROR|FAIL|Exception|Traceback|CRITICAL|could not|permission denied)', re.IGNORECASE)
STATE_FILE = Path(__file__).resolve().parent.parent / 'data' / 'log-watcher-seen.json'

def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return {k: v for k, v in data.items() if v > cutoff}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + '\n')

def error_hash(filename, line):
    return hashlib.md5(f"{filename}:{line.strip()}".encode()).hexdigest()[:12]

def _parse_ts(line):
    m = re.match(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', line)
    if m:
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None

def scan_logs(hours):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    errors = []
    for name in LOG_FILES:
        path = os.path.join(LOG_DIR, name)
        if not os.path.isfile(path):
            continue
        try:
            if datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc) < cutoff:
                continue
        except OSError:
            continue
        try:
            with open(path, 'r', errors='replace') as f:
                for line in f:
                    if not ERROR_RE.search(line):
                        continue
                    ts = _parse_ts(line)
                    if ts and ts < cutoff:
                        continue
                    errors.append((name, line.rstrip('\n')))
        except OSError as e:
            print(f"  Warning: cannot read {path}: {e}", file=sys.stderr)
    return errors

def _group(errors):
    by_file = {}
    for name, line in errors:
        by_file.setdefault(name, []).append(line)
    return by_file

def cmd_scan():
    errors = scan_logs(24)
    if not errors:
        print("All clear — no errors in last 24h"); return
    by_file = _group(errors)
    print(f"Found {len(errors)} error(s) across {len(by_file)} log(s) in last 24h:\n")
    for name, lines in sorted(by_file.items()):
        print(f"  [{name}] {len(lines)} error(s)")
        for l in lines[:5]:
            print(f"    {l[:120]}")
        if len(lines) > 5:
            print(f"    ... and {len(lines) - 5} more")
        print()


def _require_phone():
    phone = config.alert_phone
    if not phone:
        print("Error: config.alert_phone not set", file=sys.stderr); sys.exit(1)
    return phone

def _send(phone, msg):
    print(msg)
    if not send_whatsapp(phone, msg):
        print("Failed to send WhatsApp message", file=sys.stderr); sys.exit(1)

def cmd_alert():
    phone = _require_phone()
    errors = scan_logs(2)
    state, now = load_state(), datetime.now(timezone.utc).isoformat()
    new_errors = []
    for name, line in errors:
        h = error_hash(name, line)
        if h not in state:
            state[h] = now
            new_errors.append((name, line))
    save_state(state)
    if not new_errors:
        print("No new errors in last 2h"); return
    parts = [f"Log Alert - {len(new_errors)} error(s) in last 2h:", ""]
    for name, line in new_errors[:15]:
        parts.append(f"[{name}] {line[:100]}")
    if len(new_errors) > 15:
        parts.append(f"... and {len(new_errors) - 15} more")
    _send(phone, "\n".join(parts))

def cmd_digest():
    phone = _require_phone()
    errors = scan_logs(24)
    if not errors:
        _send(phone, "All clear — no errors in last 24h"); return
    by_file = _group(errors)
    parts = [f"Daily Log Digest — {len(errors)} error(s) across {len(by_file)} log(s):", ""]
    for name, lines in sorted(by_file.items()):
        parts.append(f"[{name}] {len(lines)} error(s)")
        for l in lines[:3]:
            parts.append(f"  {l[:100]}")
        if len(lines) > 3:
            parts.append(f"  ... and {len(lines) - 3} more")
        parts.append("")
    _send(phone, "\n".join(parts))

COMMANDS = {'scan': cmd_scan, 'alert': cmd_alert, 'digest': cmd_digest}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <{'|'.join(COMMANDS)}>"); sys.exit(1)
    COMMANDS[sys.argv[1]]()
