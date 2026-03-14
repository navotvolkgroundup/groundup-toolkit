"""Phase 4: Report formatting, Google Drive upload, email sending."""

import re
import sys
import json

from datetime import datetime

from lib.whatsapp import send_whatsapp
from lib.email import send_email
from lib.gws import get_google_access_token

from .section_analyzer import ANALYSIS_SECTIONS


def html_escape(text):
    """Escape HTML special characters."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def markdown_to_html(text):
    """Convert basic markdown to HTML."""
    if not text:
        return ''
    lines = text.split('\n')
    html_lines = []
    in_list = False
    list_type = 'ul'

    for line in lines:
        stripped = line.strip()

        if stripped in ('---', '***', '___'):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append('<hr>')
            continue

        if stripped.startswith('### '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append(f'<h3>{html_escape(stripped[4:])}</h3>')
            continue
        if stripped.startswith('## '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append(f'<h2>{html_escape(stripped[3:])}</h2>')
            continue
        if stripped.startswith('# '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append(f'<h1>{html_escape(stripped[2:])}</h1>')
            continue

        # Bold
        stripped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)

        # Inline code
        stripped = re.sub(r'`(.+?)`', r'<code>\1</code>', stripped)

        # Bullet points
        if stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
                list_type = 'ul'
            elif in_list and list_type != 'ul':
                html_lines.append(f'</{list_type}>')
                html_lines.append('<ul>')
                list_type = 'ul'
            html_lines.append(f'<li>{stripped[2:]}</li>')
            continue

        # Numbered lists
        num_match = re.match(r'^(\d+)[.)]\s+(.+)', stripped)
        if num_match:
            if not in_list:
                html_lines.append('<ol>')
                in_list = True
                list_type = 'ol'
            elif in_list and list_type != 'ol':
                html_lines.append(f'</{list_type}>')
                html_lines.append('<ol>')
                list_type = 'ol'
            html_lines.append(f'<li>{num_match.group(2)}</li>')
            continue

        # Blockquote
        if stripped.startswith('> '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append(f'<blockquote>{stripped[2:]}</blockquote>')
            continue

        if not stripped:
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            continue

        # Table row
        if stripped.startswith('|') and stripped.endswith('|'):
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            # Skip separator rows (e.g., |---|---|)
            if all(re.match(r'^[-:]+$', c) for c in cells):
                continue
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            tag = 'th' if not any('<table>' in l for l in html_lines[-3:]) else 'td'
            row = ''.join(f'<{tag}>{c}</{tag}>' for c in cells)
            if tag == 'th':
                html_lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">')
            html_lines.append(f'<tr>{row}</tr>')
            continue

        if in_list:
            html_lines.append(f'</{list_type}>')
            in_list = False
        html_lines.append(f'<p>{stripped}</p>')

    if in_list:
        html_lines.append(f'</{list_type}>')

    # Close any open table
    if any('<table' in l for l in html_lines) and not any('</table>' in l for l in html_lines[-1:]):
        html_lines.append('</table>')

    return '\n'.join(html_lines)


def format_report_html(deck_data, section_results):
    """Generate a professionally styled HTML report for Google Docs."""
    company = html_escape(deck_data.get('company_name') or 'Unknown Company')
    date = datetime.now().strftime('%B %d, %Y')
    tldr = html_escape(section_results.get('tldr', ''))

    sections_html = []
    for section in ANALYSIS_SECTIONS:
        content = section_results.get(section['id'], 'Analysis not available.')
        sections_html.append(markdown_to_html(content))

    memo_html = markdown_to_html(section_results.get('investment_memo', ''))

    return f"""<!DOCTYPE html>
<html>
<head>
<style>
body {{ font-family: 'Arial', sans-serif; color: #333; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 40px 20px; }}
h1 {{ color: #1a1a2e; font-size: 28px; border-bottom: 3px solid #16213e; padding-bottom: 10px; }}
h2 {{ color: #16213e; font-size: 22px; margin-top: 30px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
h3 {{ color: #0f3460; font-size: 18px; }}
.subtitle {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
.tldr {{ background: #f0f4ff; border-left: 4px solid #1a1a2e; padding: 15px 20px; margin: 20px 0; font-size: 15px; }}
.section {{ margin-bottom: 30px; }}
hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 30px 0; }}
.disclaimer {{ color: #999; font-size: 12px; font-style: italic; margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }}
strong {{ color: #1a1a2e; }}
ul, ol {{ padding-left: 25px; }}
li {{ margin-bottom: 5px; }}
</style>
</head>
<body>
<h1>Investment Analysis: {company}</h1>
<p class="subtitle">Generated: {date} | GroundUp Ventures Deal Evaluation</p>

<div class="tldr">
<strong>TL;DR:</strong> {tldr}
</div>

<hr>

{''.join(f'<div class="section">{s}</div><hr>' for s in sections_html)}

<div class="section">
<h2>12. Investment Memo Summary</h2>
{memo_html}
</div>

<hr>

<p class="disclaimer">This analysis was generated by GroundUp's AI deal evaluation system.
All assessments should be validated through direct founder engagement and independent due diligence.</p>

</body>
</html>"""


def create_google_doc(deck_data, section_results):
    """Create a Google Doc from the analysis report. Returns (doc_url, doc_id) or (None, None)."""
    from analyzer import _session

    company = deck_data.get('company_name') or 'Unknown Company'
    date = datetime.now().strftime('%Y-%m-%d')
    doc_title = f"Deal Evaluation: {company} ({date})"

    print(f"  Creating Google Doc: {doc_title}...")

    access_token = get_google_access_token()
    if not access_token:
        print("  Could not get Google access token, skipping Google Doc.", file=sys.stderr)
        return (None, None)

    html_content = format_report_html(deck_data, section_results)

    # Upload HTML as Google Doc via Drive API multipart upload
    metadata = json.dumps({
        'name': doc_title,
        'mimeType': 'application/vnd.google-apps.document',
    })
    boundary = '---deal-report-boundary---'
    body = (
        f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'
        f'{metadata}\r\n'
        f'--{boundary}\r\nContent-Type: text/html\r\n\r\n'
    ).encode('utf-8') + html_content.encode('utf-8') + f'\r\n--{boundary}--\r\n'.encode('utf-8')

    try:
        resp = _session.post(
            'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': f'multipart/related; boundary={boundary}',
            },
            data=body,
            timeout=30,
        )

        if resp.status_code not in (200, 201):
            print(f"  Drive upload failed: HTTP {resp.status_code}", file=sys.stderr)
            return (None, None)

        doc_id = resp.json()['id']

        # Share: anyone with link can view
        _session.post(
            f'https://www.googleapis.com/drive/v3/files/{doc_id}/permissions',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            json={'role': 'reader', 'type': 'anyone'},
            timeout=10,
        )

        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        print(f"  Google Doc created: {doc_url}")
        return (doc_url, doc_id)

    except Exception as e:
        print(f"  Google Doc creation failed: {e}", file=sys.stderr)
        return (None, None)


def format_full_report(deck_data, section_results):
    company = deck_data.get('company_name') or 'Unknown Company'
    date = datetime.now().strftime('%B %d, %Y')

    parts = [
        f"# Investment Analysis: {company}",
        f"*Generated: {date} | GroundUp Ventures Deal Evaluation*",
        "",
    ]

    # TL;DR at top
    tldr = section_results.get('tldr', '')
    if tldr:
        parts.extend([
            f"**TL;DR:** {tldr}",
            "",
        ])

    parts.extend(["---", ""])

    # Sections 1-11
    for section in ANALYSIS_SECTIONS:
        result = section_results.get(section['id'], 'Analysis not available for this section.')
        parts.append(result)
        parts.append("")
        parts.append("---")
        parts.append("")

    # Section 12 (synthesis)
    memo = section_results.get('investment_memo', 'Synthesis not available.')
    parts.append(memo)
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("*This analysis was generated by GroundUp's AI deal evaluation system. "
                 "All assessments should be validated through direct founder engagement "
                 "and independent due diligence.*")

    return '\n'.join(parts)


def format_whatsapp_summary(deck_data, section_results, doc_url=None):
    company = deck_data.get('company_name') or 'Unknown Company'
    tldr = section_results.get('tldr', '')
    memo = section_results.get('investment_memo', '')
    date = datetime.now().strftime('%B %d, %Y')

    # Truncate memo to fit WhatsApp limit
    memo_text = memo[:2500] if len(memo) > 2500 else memo

    link_line = f"*Full Report:* {doc_url}" if doc_url else "_Full 12-section report sent to your email._"

    return f"""*Deal Evaluation: {company}*
{date}

*TL;DR:* {tldr}

{memo_text}

---
{link_line}"""


def format_hubspot_note(deck_data, section_results, tldr=None, doc_url=None):
    """Format a condensed version for HubSpot company notes."""
    company = deck_data.get('company_name') or 'Unknown Company'
    tldr = tldr or section_results.get('tldr', '')
    memo = section_results.get('investment_memo', 'No analysis available')

    parts = [
        f"DEAL EVALUATION: {company} (AI-Generated, {datetime.now().strftime('%b %d %Y')})",
        "",
    ]
    if doc_url:
        parts.extend([f"Full report: {doc_url}", ""])
    if tldr:
        parts.extend([f"TL;DR: {tldr}", ""])

    parts.append(memo[:3000])

    if len(memo) > 3000:
        parts.append("\n[Full 12-section analysis available via email]")

    return '\n'.join(parts)


def format_email_with_link(deck_data, section_results, doc_url):
    """Format email with TL;DR summary and link to Google Doc."""
    company = deck_data.get('company_name') or 'Unknown Company'
    date = datetime.now().strftime('%B %d, %Y')
    tldr = section_results.get('tldr', '')

    return f"""Deal Evaluation: {company}
{date}

TL;DR
{tldr}

Full 12-Section Report
{doc_url}

---
This analysis was generated by GroundUp's AI deal evaluation system.
All assessments should be validated through direct founder engagement and independent due diligence."""


def deliver_results(deck_data, section_results, phone, email=None):
    from analyzer import config, save_state

    company = deck_data.get('company_name') or 'Unknown Company'

    # Resolve email
    if not email:
        member = config.get_member_by_phone(phone)
        if member:
            email = member['email']

    # Create Google Doc
    doc_url, doc_id = create_google_doc(deck_data, section_results)

    # WhatsApp: executive summary + doc link
    wa_summary = format_whatsapp_summary(deck_data, section_results, doc_url=doc_url)
    send_whatsapp(phone, wa_summary)

    # Email: TL;DR + doc link (or full report as fallback)
    if email:
        if doc_url:
            email_body = format_email_with_link(deck_data, section_results, doc_url)
        else:
            email_body = format_full_report(deck_data, section_results)
        send_email(email, f"Deal Evaluation: {company}", email_body)

    # Save state for HubSpot logging (include doc_url)
    save_state(deck_data, section_results, section_results.get('tldr'), doc_url=doc_url)

    # Ask about HubSpot
    send_whatsapp(phone, f"Want me to log this analysis to HubSpot under *{company}*? Just reply 'log to hubspot'.")

    # Tell agent everything was already delivered
    print(f"DELIVERED: Full evaluation for {company} sent to WhatsApp and email. Do not send any additional messages.")
