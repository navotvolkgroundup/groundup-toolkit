"""Report generation — daily digest, status display, weekly briefing orchestration."""

import logging
from datetime import datetime, timedelta

from lib.config import config
from lib.email import send_email
from modules.notifications import send_weekly_briefing
from modules.retention_clock import get_expiring_founders, get_approaching_founders

log = logging.getLogger("founder-scout")


def run_weekly_briefing(db, SCOUT_RECIPIENTS):
    """Send weekly watchlist update — signals from tracked people."""
    log.info("Sending Founder Scout weekly briefing...")

    since = (datetime.now() - timedelta(days=7)).isoformat()
    recent_signals = db.get_signals_since(since)

    high_signals = [s for s in recent_signals if s['signal_tier'] == 'high']
    medium_signals = [s for s in recent_signals if s['signal_tier'] == 'medium']

    db_stats = db.get_stats()
    stats = {'active': db_stats['active']}

    send_weekly_briefing(SCOUT_RECIPIENTS, high_signals, medium_signals, stats)

    db.log_scan('weekly_briefing', signals_detected=len(recent_signals))
    log.info("Briefing sent: %d high, %d medium", len(high_signals), len(medium_signals))


def run_daily_digest(db, SCOUT_RECIPIENTS):
    """Send daily digest of CRITICAL and HIGH signals from the past 24 hours."""
    log.info("Sending daily digest...")
    since = (datetime.now() - timedelta(hours=24)).isoformat()
    recent_signals = db.get_signals_since(since)

    # Get people with CRITICAL/HIGH scores
    people = db.get_active_people()
    critical = [p for p in people if p.get('score_classification') == 'CRITICAL']
    high = [p for p in people if p.get('score_classification') == 'HIGH']

    if not recent_signals and not critical:
        log.info("No signals or CRITICAL scores in the last 24h. Skipping digest.")
        return

    date_str = datetime.now().strftime('%b %d, %Y')
    subject = f"Founder Scout Daily Digest - {date_str}"

    for recipient in SCOUT_RECIPIENTS:
        lines = [
            f"Hi {recipient['first_name']},",
            "",
            f"Founder Scout digest for {date_str}.",
            "",
        ]

        if critical:
            lines.append("CRITICAL PRIORITY")
            lines.append("=" * 40)
            for p in critical:
                score = p.get('composite_score', 0)
                lines.append(f"  {p['name']} (score: {score})")
                if p.get('last_signal'):
                    lines.append(f"    Signal: {p['last_signal'][:80]}")
                if p.get('linkedin_url'):
                    lines.append(f"    {p['linkedin_url']}")
                lines.append("")

        if high:
            lines.append("HIGH PRIORITY")
            lines.append("-" * 40)
            for p in high[:10]:
                score = p.get('composite_score', 0)
                lines.append(f"  {p['name']} (score: {score})")
                if p.get('last_signal'):
                    lines.append(f"    {p['last_signal'][:80]}")
                lines.append("")

        if recent_signals:
            lines.append(f"Signals (last 24h): {len(recent_signals)}")
            high_sigs = [s for s in recent_signals if s['signal_tier'] == 'high']
            if high_sigs:
                lines.append(f"  High: {len(high_sigs)}")
                for s in high_sigs[:5]:
                    lines.append(f"    - {s.get('name', '?')}: {s.get('description', '')[:60]}")
            lines.append("")

        # Retention clock
        with db._conn() as conn:
            imminent = get_expiring_founders(conn, status='IMMINENT')
        if imminent:
            lines.append("Retention Clocks - IMMINENT")
            lines.append("-" * 40)
            for f in imminent[:5]:
                lines.append(f"  {f.get('founder_name', '?')} — {f.get('acquired_company', '?')} "
                             f"(acquired by {f.get('acquiring_company', '?')})")
            lines.append("")

        lines.extend([
            f"Watchlist: {len(people)} active",
            f"CRITICAL: {len(critical)} | HIGH: {len(high)}",
            "",
            f"-- {config.assistant_name}",
        ])

        send_email(recipient['email'], subject, '\n'.join(lines))
        log.info("Sent digest to %s", recipient['first_name'])

    db.log_scan('daily_digest')


def run_status_v2(db):
    """Enhanced status with composite scores."""
    stats = db.get_stats()
    people = db.get_active_people()

    log.info("Founder Scout v2 Status - %s", datetime.now().strftime('%Y-%m-%d %H:%M'))
    log.info("=" * 70)
    log.info("Active watchlist: %d", stats['active'])
    log.info("Total signals: %d", stats['total_signals'])
    log.info("Total scans: %d", stats['total_scans'])

    # Score distribution
    critical = [p for p in people if p.get('score_classification') == 'CRITICAL']
    high = [p for p in people if p.get('score_classification') == 'HIGH']
    medium = [p for p in people if p.get('score_classification') == 'MEDIUM']
    low = [p for p in people if p.get('score_classification') in ('LOW', 'WATCHING', None)]

    log.info("Score Distribution:")
    log.info("CRITICAL: %d | HIGH: %d | MEDIUM: %d | LOW/WATCHING: %d", len(critical), len(high), len(medium), len(low))

    if critical:
        log.info("CRITICAL Priority:")
        for p in critical:
            score = p.get('composite_score', 0)
            signal = p.get('last_signal', '')[:50]
            li = f" {p['linkedin_url']}" if p.get('linkedin_url') else ""
            log.info("[%d] %s%s", score, p['name'], li)
            if signal:
                log.info("    %s", signal)

    if high:
        log.info("HIGH Priority:")
        for p in high:
            score = p.get('composite_score', 0)
            approached = " [approached]" if p.get('approached') else ""
            log.info("[%d] %s%s", score, p['name'], approached)

    # Retention clocks
    with db._conn() as conn:
        imminent = get_expiring_founders(conn, 'IMMINENT')
        approaching = get_approaching_founders(conn)
    if imminent or approaching:
        log.info("Retention Clocks:")
        for f in imminent:
            log.info("IMMINENT: %s (%s)", f.get('founder_name', '?'), f.get('acquired_company', '?'))
        for f in approaching:
            if f.get('current_status') != 'IMMINENT':
                log.info("APPROACHING: %s (%s)", f.get('founder_name', '?'), f.get('acquired_company', '?'))
