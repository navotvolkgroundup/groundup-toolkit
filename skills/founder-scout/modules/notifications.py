"""Email and WhatsApp notification formatting and sending for Founder Scout."""

import logging
from datetime import datetime, timedelta

from lib.config import config
from lib.email import send_email
from lib.whatsapp import send_whatsapp

log = logging.getLogger("founder-scout")


# --- Formatting ---

def format_scan_email(recipient_name, profiles):
    """Format daily scan email with relevant profiles."""
    now = datetime.now()
    date_str = now.strftime('%b %d, %Y')

    lines = [
        f"Hi {recipient_name},",
        "",
        f"Today's LinkedIn scout results ({date_str}):",
        "",
    ]

    if profiles:
        lines.append(f"{len(profiles)} relevant profiles found:")
        lines.append("-" * 40)
        for i, p in enumerate(profiles, 1):
            headline = p.get('headline') or ''
            summary = p.get('analysis_summary') or ''
            title = p.get('current_title') or ''
            lines.append(f"{i}. {p['name']}")
            if title:
                lines.append(f"   {title}")
            elif headline:
                lines.append(f"   {headline}")
            if summary:
                lines.append(f"   Why: {summary}")
            lines.append(f"   {p['linkedin_url']}")
            lines.append("")
    else:
        lines.append("No relevant profiles found today.")
        lines.append("")

    lines.extend([
        f"-- {config.assistant_name}",
    ])

    return '\n'.join(lines)


def format_scan_whatsapp(recipient_name, profiles):
    """Format compact WhatsApp daily scan summary."""
    lines = [
        "Founder Scout Daily",
        "",
        f"Hi {recipient_name}, today's scan found {len(profiles)} relevant profiles.",
        "",
    ]

    for i, p in enumerate(profiles[:5], 1):
        summary = p.get('analysis_summary') or ''
        title = p.get('current_title') or p.get('headline') or ''
        entry = f"{i}. {p['name']}"
        if title:
            entry += f" — {title[:50]}"
        if summary:
            entry += f"\n   {summary[:80]}"
        lines.append(entry)

    if len(profiles) > 5:
        lines.append(f"... and {len(profiles) - 5} more")

    lines.extend(["", "Full list sent to your email."])
    return '\n'.join(lines)


def _enrich_signal(signal):
    """Add intro path and thesis fit context to a signal dict (best-effort)."""
    enrichment = {}

    # Intro path from relationship graph
    try:
        from lib.relationship_graph import RelationshipGraph
        graph = RelationshipGraph()
        identifier = signal.get('linkedin_url') or signal.get('name')
        if identifier:
            connections = graph.get_connections(identifier, limit=3)
            if connections:
                parts = []
                for c in connections[:2]:
                    p = c.get('person', {})
                    name = p.get('name', 'Unknown')
                    rel = c.get('rel_type', '').replace('_', ' ')
                    strength = c.get('strength', 1)
                    parts.append(f"{name} ({rel}, ×{strength})")
                enrichment['intro'] = "Connected via: " + ", ".join(parts)
    except Exception:
        pass

    # Thesis fit
    try:
        import os
        toolkit_root = os.environ.get('TOOLKIT_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))
        thesis_path = os.path.join(toolkit_root, 'skills', 'founder-scout', 'thesis.yaml')
        if os.path.exists(thesis_path):
            try:
                import yaml
                with open(thesis_path, 'r') as f:
                    thesis_config = yaml.safe_load(f)
            except ImportError:
                thesis_config = None

            if thesis_config:
                from modules.scoring import apply_thesis_matching
                profile_text = f"{signal.get('headline', '')} {signal.get('description', '')}"
                _, match = apply_thesis_matching(50, profile_text, thesis_config)
                if match and not match.startswith('Anti'):
                    enrichment['thesis'] = match
    except Exception:
        pass

    return enrichment


def _format_enriched_signal(i, s, include_enrichment=True):
    """Format a single signal entry with optional enrichment."""
    lines = []
    lines.append(f"{i}. {s['name']}")
    if s.get('linkedin_url'):
        lines.append(f"   LinkedIn: {s['linkedin_url']}")
    lines.append(f"   Signal: {s.get('description', 'N/A')}")

    if include_enrichment:
        enrichment = _enrich_signal(s)
        if enrichment.get('intro'):
            lines.append(f"   {enrichment['intro']}")
        if enrichment.get('thesis'):
            lines.append(f"   Thesis fit: {enrichment['thesis']}")

    # Render additional signals for this person as sub-bullets
    for extra in s.get('extra_signals', []):
        lines.append(f"   + {extra.get('description', 'N/A')}")

    lines.append("")
    return lines


def format_briefing_email(recipient_name, high_signals, medium_signals, stats):
    """Format weekly briefing email for watchlist signals."""
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime('%b %d')
    week_end = now.strftime('%b %d, %Y')

    lines = [
        f"Hi {recipient_name},",
        "",
        f"Founder Scout weekly watchlist update ({week_start} - {week_end}).",
        "",
    ]

    if high_signals:
        lines.append("HIGH SIGNAL")
        lines.append("-" * 40)
        for i, s in enumerate(high_signals, 1):
            lines.extend(_format_enriched_signal(i, s))

    if medium_signals:
        lines.append("MEDIUM SIGNAL")
        lines.append("-" * 40)
        for i, s in enumerate(medium_signals, 1):
            lines.extend(_format_enriched_signal(i, s))

    if not high_signals and not medium_signals:
        lines.append("No new signals on watchlist this week.")
        lines.append("")

    lines.extend([
        f"Watchlist: {stats.get('active', 0)} active people tracked",
        "",
        f"-- {config.assistant_name}",
    ])

    return '\n'.join(lines)


# --- Sending ---

def send_scan_results(recipients, profiles):
    """Send daily scan results via email + WhatsApp to all recipients."""
    date_str = datetime.now().strftime('%b %d, %Y')
    subject = f"Founder Scout - {date_str}"

    log.info("Sending results (%d people) to team...", len(profiles))
    for recipient in recipients:
        email_body = format_scan_email(recipient['first_name'], profiles)
        send_email(recipient['email'], subject, email_body)

        wa_message = format_scan_whatsapp(recipient['first_name'], profiles)
        send_whatsapp(recipient['phone'], wa_message)


def send_weekly_briefing(recipients, high_signals, medium_signals, stats):
    """Send weekly briefing email to all recipients."""
    week_str = datetime.now().strftime('%b %d, %Y')
    subject = f"Founder Scout Weekly - {week_str}"

    for recipient in recipients:
        email_body = format_briefing_email(
            recipient['first_name'], high_signals, medium_signals, stats
        )
        log.info("Sending email to %s...", recipient['email'])
        send_email(recipient['email'], subject, email_body)


def send_github_alerts(recipients, high_signals):
    """Send immediate email alerts for high-tier GitHub signals."""
    if not high_signals or not recipients:
        return
    subject = f"GitHub Alert: {len(high_signals)} new signal{'s' if len(high_signals) > 1 else ''}"
    body_lines = ["GitHub Signals Detected", "=" * 25, ""]
    for s in high_signals:
        url = s.get('source_url', '')
        body_lines.append(f"- {s['name']}: {s['description']}")
        if url:
            body_lines.append(f"  {url}")
        body_lines.append("")
    for recip in recipients:
        send_email(recip['email'], subject, '\n'.join(body_lines))
        log.info("Emailed %s", recip['first_name'])


def send_registrar_alerts(recipients, high_signals):
    """Send immediate alerts for company registration matches."""
    if not high_signals or not recipients:
        return
    subject = f"Company Registration Alert: {len(high_signals)} match{'es' if len(high_signals) > 1 else ''}"
    body_lines = ["Israeli Company Registration Match", "=" * 35, ""]
    for s in high_signals:
        body_lines.append(f"- {s['description']}")
        body_lines.append("")
    for recip in recipients:
        send_email(recip['email'], subject, '\n'.join(body_lines))
        send_whatsapp(recip['phone'], '\n'.join(body_lines))
