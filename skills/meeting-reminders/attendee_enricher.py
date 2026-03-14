"""
Attendee research, LinkedIn lookup, HubSpot lookup, and brief generation.
Extracted from reminders.py as part of modular refactoring.
"""

import os
import sys
import re
from datetime import datetime
import pytz

# Shared config loader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.config import config
from lib.hubspot import (
    search_company as _search_company, get_deals_for_company,
    get_latest_note as _get_latest_note
)
from lib.gws import gws_gmail_search, gws_gmail_thread_get
from lib.claude import call_claude

# Enrichment library integration
try:
    from enrichment import EnrichmentService
    ENRICHMENT_AVAILABLE = True
except ImportError:
    print("Warning: Enrichment library not available")
    ENRICHMENT_AVAILABLE = False

# Team members with calendars and phone numbers (loaded from config)
TEAM_MEMBERS = {}
for m in config.team_members:
    TEAM_MEMBERS[m['email']] = {
        'name': m['name'].split()[0],  # First name only
        'phone': m['phone'],
        'timezone': m['timezone'],
        'enabled': m.get('reminders_enabled', True)
    }

# VC pipeline stage map with talking point suggestions
# Loaded from config.yaml if available, with hardcoded fallback
_DEFAULT_STAGE_MAP = {
    'qualifiedtobuy': {
        'label': 'Sourcing',
        'tips': 'Initial screen — validate thesis fit, team background, and market size. Ask what made them start this company.',
    },
    'appointmentscheduled': {
        'label': 'Screening',
        'tips': 'Deeper dive — understand product differentiation, early traction signals, and competitive landscape.',
    },
    'presentationscheduled': {
        'label': 'First Meeting',
        'tips': 'Get specifics: unit economics, customer pipeline, go-to-market plan. Assess founder-market fit.',
    },
    'decisionmakerboughtin': {
        'label': 'IC Review',
        'tips': 'Prepare for IC — gather reference points, comparable deals, and key risks to present.',
    },
    'contractsent': {
        'label': 'Due Diligence',
        'tips': 'Deep DD — financials, cap table, legal, customer references. Verify claims made in earlier meetings.',
    },
    'closedwon': {
        'label': 'Term Sheet Offered',
        'tips': 'Negotiate terms — valuation, board seat, pro-rata rights, milestones. Keep momentum.',
    },
    '1112320899': {
        'label': 'Term Sheet Signed',
        'tips': 'Legal close — coordinate with lawyers, finalize docs, wire timeline.',
    },
    '1112320900': {
        'label': 'Investment Closed',
        'tips': 'Post-close — discuss board cadence, reporting expectations, how you can help.',
    },
    '1008223160': {
        'label': 'Portfolio Monitoring',
        'tips': 'Check-in — KPIs, runway, hiring progress, any blockers you can help unblock.',
    },
    '1138024523': {
        'label': 'Keep on Radar',
        'tips': 'Light touch — see what has changed since you last spoke, if timing is better now.',
    },
}
# Prefer config.yaml stages, fall back to hardcoded
STAGE_MAP = config.get_stage_map() or _DEFAULT_STAGE_MAP


def format_attendees(attendees, owner_email):
    """Format attendee list (excluding owner)"""
    if not attendees:
        return "No other attendees"
    filtered = [a for a in attendees if a != owner_email and '@' in a]
    if not filtered:
        return "No other attendees"
    names = [a.split('@')[0].replace('.', ' ').title() for a in filtered[:3]]
    if len(filtered) > 3:
        return f"{', '.join(names)} and {len(filtered) - 3} others"
    return ', '.join(names)


def get_external_attendees(attendees, owner_email):
    """Get list of external (non-team-domain) attendee emails"""
    if not attendees:
        return []
    external = []
    for attendee in attendees:
        email = attendee.get('email', '') if isinstance(attendee, dict) else attendee
        if email and '@' in email and email != owner_email:
            if not email.endswith('@' + config.team_domain):
                external.append(email)
    return external


def is_internal_meeting(attendees, owner_email):
    """Check if all attendees are internal — no external guests"""
    return len(get_external_attendees(attendees, owner_email)) == 0


def search_hubspot_company(email_domain):
    """Search HubSpot for company by domain."""
    return _search_company(domain=email_domain)


def get_company_deals(company_id):
    """Get active deals for a company."""
    return get_deals_for_company(company_id, limit=3)


def get_latest_note(company_id):
    """Get the latest note for a company."""
    return _get_latest_note(company_id)


def get_hubspot_context(attendees, owner_email):
    """Get HubSpot context for external attendees"""
    external_emails = get_external_attendees(attendees, owner_email)
    if not external_emails:
        return None

    first_email = external_emails[0] if isinstance(external_emails[0], str) else external_emails[0].get('email', '')
    domain = first_email.split('@')[-1]
    print(f"    Looking up HubSpot data for {domain}...")

    company = search_hubspot_company(domain)
    if not company:
        print(f"    No HubSpot company found")
        return None

    company_id = company.get('id')
    company_name = company.get("properties", {}).get("name") or domain
    company_industry = company.get('properties', {}).get('industry', '')
    print(f"    Found company: {company_name}")

    deals = get_company_deals(company_id)
    latest_note = get_latest_note(company_id)

    return {
        'company_id': company_id,
        'company_name': company_name,
        'industry': company_industry,
        'deals': deals,
        'latest_note': latest_note
    }


def get_deal_stage_info(deals):
    """Extract deal stage info for stage-aware suggestions"""
    if not deals:
        return None, None
    deal = deals[0]
    stage_id = deal.get('properties', {}).get('dealstage', '')
    stage_info = STAGE_MAP.get(stage_id)
    return stage_id, stage_info


def get_recent_email_context(external_emails, attendee_names=None, max_threads=3):
    """Search Gmail for recent email threads with external attendees.

    Searches by exact email AND by name (for forwarded emails where from: doesn't match).
    Returns a short summary of recent email exchanges.
    """
    if not external_emails and not attendee_names:
        return None

    # Build search query — combine email addresses AND names
    query_parts = []

    # Search by exact email
    for email in (external_emails or []):
        e = email if isinstance(email, str) else email.get('email', '')
        if '@' in e:
            query_parts.append(f"from:{e} OR to:{e}")

    # Also search by name (catches forwarded emails and form submissions)
    if attendee_names:
        for name in attendee_names[:3]:
            name = name.strip()
            if name and len(name) > 2:
                query_parts.append(f'"{name}"')

    if not query_parts:
        return None

    query = f"({' OR '.join(query_parts)}) newer_than:30d"

    try:
        threads = gws_gmail_search(query, max_results=max_threads)
        if not threads:
            return None

        snippets = []
        for thread in threads[:max_threads]:
            thread_id = thread.get('id')
            if not thread_id:
                continue
            thread_data = gws_gmail_thread_get(thread_id, fmt="metadata")
            if not thread_data:
                continue

            messages = thread_data.get('messages', [])
            if not messages:
                continue

            # Get subject from first message headers
            headers = messages[0].get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No subject')
            # Clean subject
            subject = re.sub(r'^(re|fwd|fw):\s*', '', subject, flags=re.IGNORECASE).strip()

            snippet = thread.get('snippet', '')[:120]
            date_ms = int(messages[-1].get('internalDate', 0))
            date_str = datetime.fromtimestamp(date_ms / 1000).strftime('%b %d') if date_ms else ''

            snippets.append(f"• {subject} ({date_str}): {snippet}")

        return '\n'.join(snippets) if snippets else None

    except Exception as e:
        print(f"    Email context error: {e}", file=sys.stderr)
        return None


def enrich_external_attendees(attendees, owner_email):
    """Enrich external attendees with LinkedIn, Crunchbase, GitHub, News"""
    if not ENRICHMENT_AVAILABLE:
        return []

    team_emails = set(TEAM_MEMBERS.keys())
    enriched_results = []
    service = EnrichmentService()

    for attendee in attendees:
        email = attendee.get('email', '').lower()
        name = attendee.get('displayName', email)

        if email in team_emails or email == owner_email.lower():
            continue
        if not email or '@' not in email:
            continue
        if any(x in email for x in ['noreply', 'no-reply', 'calendar', 'bot', 'notification']):
            continue

        try:
            enrichment = service.enrich_attendee(email, name, use_cache=True)
            has_data = (
                enrichment.get('linkedin') or enrichment.get('crunchbase') or
                enrichment.get('github') or enrichment.get('recent_news')
            )
            if has_data:
                formatted = service.format_enrichment(enrichment)
                enriched_results.append(formatted)
        except Exception as e:
            print(f"    Warning: Could not enrich {name} ({email}): {e}")
            continue

    return enriched_results


def generate_ai_brief(summary, member_name, attendee_names, hubspot_context,
                      email_context, previous_meetings, stage_info):
    """Use Claude to generate a concise, actionable meeting prep brief."""

    context_parts = []
    context_parts.append(f"Meeting: {summary}")
    context_parts.append(f"Team member: {member_name}")
    context_parts.append(f"External attendees: {attendee_names}")

    if hubspot_context:
        context_parts.append(f"\nHubSpot company: {hubspot_context.get('company_name', 'Unknown')}")
        if hubspot_context.get('industry'):
            context_parts.append(f"Industry: {hubspot_context['industry']}")
        if hubspot_context.get('deals'):
            deal = hubspot_context['deals'][0]
            props = deal.get('properties', {})
            deal_name = props.get('dealname', 'Unknown')
            stage_id = props.get('dealstage', '')
            stage_label = STAGE_MAP.get(stage_id, {}).get('label', stage_id)
            context_parts.append(f"Deal: {deal_name} (Stage: {stage_label})")
        if hubspot_context.get('latest_note'):
            context_parts.append(f"Latest CRM note: {hubspot_context['latest_note']}")

    if email_context:
        context_parts.append(f"\nRecent email threads with this person/company:\n{email_context}")
        context_parts.append("NOTE: Some emails above may be about OTHER companies or people — only reference emails that clearly involve the meeting attendee.")

    if previous_meetings:
        context_parts.append(f"\nPrevious meetings with this contact:\n{previous_meetings}")

    if stage_info:
        context_parts.append(f"\nStage guidance: {stage_info.get('tips', '')}")

    context_text = '\n'.join(context_parts)

    system = (
        f"You are {config.assistant_name}, a VC firm assistant at GroundUp Ventures. "
        "Write a meeting prep note for a team member. "
        "Format for WhatsApp readability: use short lines with line breaks between each point. "
        "\n\n"
        "Structure: "
        "Line 1: One sentence — who you are meeting and the context (e.g. their role, company, relationship). "
        "Then a blank line. "
        "Then 2-3 bullet points (use the bullet character) with specific, actionable talking points. "
        "Then a blank line. "
        "Final line: one concrete goal or decision to aim for in this meeting. "
        "\n\n"
        "CRITICAL RULES:\n"
        "- NEVER fabricate or infer information not explicitly in the data. If you don't have data, say so.\n"
        "- NEVER invent narratives about past interactions (e.g. 'last connected at a gathering').\n"
        "- Only reference emails/meetings that clearly involve the meeting attendee — ignore unrelated emails about other companies.\n"
        "- Do not mention deck reviews, pitches, or analyses unless they are specifically about this attendee's company.\n"
        "- Be specific, not generic. No filler like 'catch up on momentum' or 'explore synergies'.\n"
        "- If previous meetings exist, state them factually (date, topic) — don't embellish.\n"
        "- If no meaningful data exists, write: 'No prior context found — first real interaction.' and suggest discovery questions.\n"
        "- No markdown formatting (no ** or #). Plain text only.\n"
        "- Total length: 5-8 short lines max."
    )

    try:
        brief = call_claude(
            context_text,
            system_prompt=system,
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            timeout=30,
        )
        return brief
    except Exception as e:
        print(f"    AI brief generation error: {e}", file=sys.stderr)
        return None
