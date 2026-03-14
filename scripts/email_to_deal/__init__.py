"""Email-to-deal automation package.

Orchestration: main(), process_email(), process_whatsapp_deal(),
process_roastmydeck_email().
"""

import os
import sys
import re
import json
import fcntl
import tempfile
import logging
import requests
from datetime import datetime

log = logging.getLogger("email-to-deal")

from lib.config import config
from lib.gws import gws_gmail_thread_get
from scripts.portfolio_monitor import handle_portfolio_email, PORTFOLIO

from .config import (
    ANTHROPIC_API_KEY, TEAM_MEMBERS, OWNER_IDS,
    MATON_API_KEY, MATON_BASE_URL,
    DEFAULT_PIPELINE, DEFAULT_STAGE,
    SECONDARY_PIPELINE, SECONDARY_STAGE,
    PIPELINE_NAMES, STAGE_NAMES,
    EMAIL_TO_PHONE,
    is_lp_email, should_skip_email, _is_own_firm_name,
)

from .scanner import (
    check_recent_emails, get_email_body, mark_email_processed,
    check_roastmydeck_emails, get_email_attachments, download_attachment,
    extract_pdf_text, check_whatsapp_deals,
)

from .extractor import (
    extract_company_info, _extract_company_from_email_domains,
    _extract_company_with_claude, _is_bad_company_name, _classify_email_intent,
    extract_deck_links, is_papermark_link, is_docsend_link,
    fetch_papermark_with_camofox, fetch_docsend_with_camofox,
    analyze_deck_images_with_claude, fetch_deck_with_browser,
    analyze_deck_with_claude, format_deck_description,
    extract_company_name_from_analysis, parse_analysis_to_deck_data,
    save_deal_analyzer_state,
)

from .crm import (
    create_hubspot_company, create_hubspot_deal, update_deal_owner,
    associate_deal_company, search_hubspot_company, search_hubspot_deal,
)

from .notifications import (
    send_whatsapp, send_confirmation_email, send_email_simple,
)


def process_whatsapp_deal(msg, sender_email, sender_name, phone):
    """Process a deal submission from WhatsApp"""
    message = msg['message']

    # Extract company name
    # Try different patterns
    patterns = [
        r'deal:\s*(.+?)(?:\s*-\s*|\s*$)',
        r'company:\s*(.+?)(?:\s*-\s*|\s*$)',
        r'pitch:\s*(.+?)(?:\s*-\s*|\s*$)',
        r'deck:\s*(.+?)(?:\s*-\s*|\s*$)',
        r'startup:\s*(.+?)(?:\s*-\s*|\s*$)'
    ]

    company_name = None
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            company_name = match.group(1).strip()
            break

    if not company_name:
        # Try to extract company name from phrases like "Chief Architect of MoonActive" or "CEO at StartupCo"
        company_patterns = [
            r'(?:of|at|from)\s+([A-Z][A-Za-z0-9\s&.-]+?)(?:\s|$)',  # "of MoonActive", "at StartupCo"
            r'([A-Z][A-Za-z0-9\s&.-]+?)(?:\s+(?:CEO|CTO|CFO|COO|Founder|Co-founder))',  # "MoonActive CEO"
        ]

        for pattern in company_patterns:
            match = re.search(pattern, message)
            if match:
                company_name = match.group(1).strip()
                # Remove trailing words like "Inc", "Ltd", etc if they're alone
                company_name = re.sub(r'\s+(Inc|Ltd|LLC|Corp)\.?$', '', company_name, flags=re.IGNORECASE)
                break

        # If still no match, use whole message but clean it up
        if not company_name:
            company_name = message.strip()
            # Remove common prefixes
            company_name = re.sub(r'^(Chief|Senior|Lead|Head of)\s+', '', company_name, flags=re.IGNORECASE)
            company_name = re.sub(r'\s+(Architect|Engineer|Developer|Manager|Director)\s+of\s+', ' - ', company_name, flags=re.IGNORECASE)

    # Check for LP mention
    is_lp = bool(re.search(r'\bLP\b|\bL\.P\.\b|limited partner', message, re.IGNORECASE))

    # Determine pipeline and stage
    if is_lp:
        pipeline_id = SECONDARY_PIPELINE
        stage_id = SECONDARY_STAGE
        deal_suffix = ' - LP'
        category = 'LP Deal'
    else:
        pipeline_id = DEFAULT_PIPELINE
        stage_id = DEFAULT_STAGE
        deal_suffix = ' - Initial Meeting'
        category = 'VC Deal Flow'

    log.info('Company: %s', company_name)
    log.info('Category: %s', category)

    # Create company and deal
    company_data = {
        'name': company_name,
        'description': f'Created from WhatsApp by {sender_name}'
    }

    company_id = create_hubspot_company(company_data)
    if not company_id:
        send_whatsapp(phone, f"\u274c Error creating company '{company_name}'. Please try again or contact your admin.")
        return

    deal_name = company_name
    deal_id = create_hubspot_deal(deal_name, company_id, sender_email, pipeline_id, stage_id)

    if deal_id:
        deal_url = f'https://app.hubspot.com/contacts/{config.hubspot_portal_id}/record/0-3/{deal_id}'
        pipeline_name = PIPELINE_NAMES.get(pipeline_id, pipeline_id)
        stage_name = STAGE_NAMES.get(stage_id, stage_id)

        confirmation = f"""\u2705 Deal Created: {company_name}

Pipeline: {pipeline_name}
Stage: {stage_name}

View: {deal_url}

- Deal Bot"""

        send_whatsapp(phone, confirmation)
        log.info('Deal created and confirmation sent')
    else:
        send_whatsapp(phone, f"\u274c Error creating deal for '{company_name}'. Please try again.")


def parse_roastmydeck_email(body):
    """Parse structured fields from a RoastMyDeck email body."""
    fields = {}
    for key in ["Source", "Company", "Recommendation", "Signal", "Founder", "Founder Email", "Analyzed"]:
        match = re.search(rf"^{key}:\s*(.+)$", body, re.MULTILINE)
        if match:
            val = match.group(1).strip()
            if val and val != "N/A":
                fields[key] = val

    # Extract SUMMARY section
    summary_match = re.search(r"SUMMARY:\s*\n(.+?)(?=\n---|\nFULL REPORT:|\Z)", body, re.DOTALL)
    if summary_match:
        fields["summary"] = summary_match.group(1).strip()

    # Extract FULL REPORT section
    report_match = re.search(r"FULL REPORT:\s*\n(.+)", body, re.DOTALL)
    if report_match:
        fields["full_report"] = report_match.group(1).strip()

    return fields


def _signal_to_owner(signal, recommendation):
    """Map RoastMyDeck signal to a default deal owner.

    GREEN  -> navot (for now, first look)
    YELLOW -> navot
    RED    -> navot (logged but low priority)
    """
    return list(TEAM_MEMBERS.keys())[0]  # First team member as default


def process_roastmydeck_email(thread_id):
    """Process a single RoastMyDeck analysis email."""
    thread_data = gws_gmail_thread_get(thread_id, fmt="full")
    if not thread_data or not thread_data.get("messages"):
        log.warning('Could not fetch thread %s', thread_id)
        return False

    msg = thread_data["messages"][-1]
    headers = msg.get("payload", {}).get("headers", [])
    subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")

    # Get plain text body
    import base64
    body = ""
    payload = msg.get("payload", {})
    if payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break
            if part.get("parts"):
                for sp in part["parts"]:
                    if sp.get("mimeType") == "text/plain" and sp.get("body", {}).get("data"):
                        body = base64.urlsafe_b64decode(sp["body"]["data"]).decode("utf-8", errors="replace")
                        break
    if not body and payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    if not body:
        body = msg.get("snippet", "")

    fields = parse_roastmydeck_email(body)
    company_name = fields.get("Company", "")
    if not company_name:
        # Try extracting from subject: [RoastMyDeck] RECOMMENDATION - CompanyName
        subj_match = re.search(r"\[RoastMyDeck\]\s*\w+\s*-\s*(.+)", subject)
        company_name = subj_match.group(1).strip() if subj_match else ""

    if not company_name:
        log.warning('Skipping RoastMyDeck email: no company name found')
        mark_email_processed(thread_id)
        return False

    recommendation = fields.get("Recommendation", "UNKNOWN")
    signal = fields.get("Signal", "YELLOW")
    founder = fields.get("Founder", "")
    founder_email = fields.get("Founder Email", "")
    summary = fields.get("summary", "")
    full_report = fields.get("full_report", "")

    log.info('RoastMyDeck: %s [%s] (%s)', company_name, recommendation, signal)

    # Build rich description for company
    company_desc_parts = [f"Source: RoastMyDeck analysis"]
    if recommendation:
        company_desc_parts.append(f"Recommendation: {recommendation} ({signal})")
    if founder:
        company_desc_parts.append(f"Founder: {founder}")
    if founder_email:
        company_desc_parts.append(f"Founder email: {founder_email}")
    if summary:
        company_desc_parts.append(f"\n--- SUMMARY ---\n{summary}")
    if full_report:
        company_desc_parts.append(f"\n--- FULL ANALYSIS ---\n{full_report}")

    company_description = "\n".join(company_desc_parts)

    # Check for existing company
    existing_company_id = search_hubspot_company(company_name)
    if existing_company_id:
        log.info('Found existing company: %s (ID: %s)', company_name, existing_company_id)
        # Update description with analysis
        try:
            url = f"{MATON_BASE_URL}/crm/v3/objects/companies/{existing_company_id}"
            h = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}
            requests.patch(url, headers=h, json={"properties": {"description": company_description}})
            log.info('Updated company description with RoastMyDeck analysis')
        except Exception:
            pass
        company_id = existing_company_id
    else:
        company_data = {"name": company_name, "description": company_description}
        company_id = create_hubspot_company(company_data)
        if not company_id:
            return False

    # Build deal description
    deal_desc_parts = [f"RoastMyDeck Analysis \u2014 {recommendation} ({signal})"]
    if founder:
        deal_desc_parts.append(f"Founder: {founder}")
    if founder_email:
        deal_desc_parts.append(f"Contact: {founder_email}")
    if summary:
        deal_desc_parts.append(f"\n{summary}")
    if full_report:
        deal_desc_parts.append(f"\n--- FULL REPORT ---\n{full_report}")

    deal_description = "\n".join(deal_desc_parts)

    # Check for existing deal (dedup) -- check both with and without [RoastMyDeck] prefix
    existing_deal_id = search_hubspot_deal(company_name) or search_hubspot_deal(f"[RoastMyDeck] {company_name}")
    if existing_deal_id:
        log.info('Skipping: deal %r already exists (ID: %s)', company_name, existing_deal_id)
        mark_email_processed(thread_id)
        return True

    # Map recommendation to pipeline stage
    pipeline_id = DEFAULT_PIPELINE
    recommendation_clean = recommendation.upper().replace(" ", "_")
    if recommendation_clean in ("STRONG_INVEST", "INVEST"):
        stage_id = "appointmentscheduled"  # Screening
    else:
        stage_id = "closedlost"  # Passed/Not Pursuing (MONITOR, PASS, STRONG_PASS)

    # Assign to first team member by default
    owner_email = _signal_to_owner(signal, recommendation)

    # Create deal with description
    owner_id = OWNER_IDS.get(owner_email)
    url = f"{MATON_BASE_URL}/crm/v3/objects/deals"
    h = {"Authorization": f"Bearer {MATON_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "properties": {
            "dealname": f"[RoastMyDeck] {company_name}",
            "dealstage": stage_id,
            "pipeline": pipeline_id,
            "description": deal_description,
        }
    }
    try:
        response = requests.post(url, headers=h, json=payload)
        response.raise_for_status()
        result = response.json()
        deal_id = result["id"]
        log.info('Created deal: %s (ID: %s)', company_name, deal_id)
        log.info('Pipeline: %s, Stage: %s', PIPELINE_NAMES.get(pipeline_id, pipeline_id), STAGE_NAMES.get(stage_id, stage_id))

        if owner_id:
            update_deal_owner(deal_id, owner_id, owner_email)
        if company_id:
            associate_deal_company(deal_id, company_id)

        # Create a note with the full analysis attached to the deal
        if full_report:
            note_body = f"RoastMyDeck Deck Analysis \u2014 {company_name}\n"
            note_body += f"Recommendation: {recommendation} ({signal})\n"
            if founder:
                note_body += f"Founder: {founder}\n"
            if founder_email:
                note_body += f"Contact: {founder_email}\n"
            note_body += f"\n{full_report}"

            note_url = f"{MATON_BASE_URL}/crm/v3/objects/notes"
            note_payload = {
                "properties": {
                    "hs_note_body": note_body,
                    "hs_timestamp": datetime.now().isoformat() + "Z",
                },
                "associations": [
                    {
                        "to": {"id": deal_id},
                        "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 214}],
                    }
                ],
            }
            try:
                note_resp = requests.post(note_url, headers=h, json=note_payload)
                note_resp.raise_for_status()
                log.info('Created note with full analysis on deal')
            except Exception as e:
                log.warning('Could not create note: %s', e)

        # Send confirmation (to first team member)
        deal_url = f"https://app.hubspot.com/contacts/{config.hubspot_portal_id}/record/0-3/{deal_id}"
        pipeline_name = PIPELINE_NAMES.get(pipeline_id, pipeline_id)
        stage_name = STAGE_NAMES.get(stage_id, stage_id)
        send_confirmation_email(owner_email, company_name, pipeline_name, stage_name, deal_url)

        mark_email_processed(thread_id)
        return True

    except Exception as e:
        log.error('Error creating RoastMyDeck deal: %s', e)
        return False


def process_email(thread):
    thread_id = thread.get('id', '')

    # Fetch thread metadata to get From/Subject (search only returns id+snippet)
    thread_data = gws_gmail_thread_get(thread_id, fmt='metadata')
    if not thread_data or not thread_data.get('messages'):
        log.warning('Skipping thread %s: could not fetch metadata', thread_id)
        return False

    # Use the LAST message (most recent -- the forwarding team member)
    last_msg = thread_data['messages'][-1]
    headers = last_msg.get('payload', {}).get('headers', [])
    from_email = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')

    sender_match = re.search(r'<(.+?)>', from_email)
    sender_email = sender_match.group(1) if sender_match else from_email.strip()
    if sender_email not in TEAM_MEMBERS:
        # Scan ALL messages in thread for a team member sender
        found_team_sender = None
        for msg in thread_data['messages']:
            msg_headers = msg.get('payload', {}).get('headers', [])
            msg_from = next((h['value'] for h in msg_headers if h['name'].lower() == 'from'), '')
            msg_match = re.search(r'<(.+?)>', msg_from)
            msg_sender = msg_match.group(1) if msg_match else msg_from.strip()
            if msg_sender in TEAM_MEMBERS:
                found_team_sender = msg_sender
                break
        if found_team_sender:
            sender_email = found_team_sender
        else:
            log.warning('Skipping: no team member sender found in thread (last sender: %s, subject: %s)', sender_email, subject)
            return False

    log.info('Processing: %s', subject)

    # Get email body to check for LP mentions and filtering
    body = get_email_body(thread_id)

    # Skip system/automated emails
    if should_skip_email(subject, body):
        log.debug('Skipped: System/automated email (not a deal)')
        mark_email_processed(thread_id)
        return False

    # Check if sender explicitly asked for portfolio logging
    explicit_portfolio = bool(re.search(r'portfolio\s*(update|monitoring|company|log)', f'{subject} {body}', re.IGNORECASE))

    # Check if this is a portfolio company update (not a deal)
    portfolio_result = handle_portfolio_email(sender_email, subject, body)
    if portfolio_result:
        if portfolio_result.get('ask_sender'):
            # Portfolio company recognized but not in HubSpot -- ask sender via WhatsApp + email
            company = portfolio_result.get('company_name', '?')
            sender_phone = EMAIL_TO_PHONE.get(sender_email)
            msg = f"I got your email about {company}. It looks like a portfolio update but I can't find {company} in HubSpot. Should I create it as a portfolio company, or log it as a new deal?"
            if sender_phone:
                send_whatsapp(sender_phone, msg)
            send_email_simple(sender_email, f"Re: {subject}", msg + "\n\n- Christina")
            log.info('Asked sender about portfolio company: %s', company)
            mark_email_processed(thread_id)
            return False
        log.info('Handled as portfolio update for %s', portfolio_result["company_name"])
        mark_email_processed(thread_id)
        return True

    # If sender explicitly said "portfolio" but we couldn't match a company, ask which one
    if explicit_portfolio and not portfolio_result:
        sender_phone = EMAIL_TO_PHONE.get(sender_email)
        msg = f"You mentioned this is a portfolio update, but I couldn't match it to a portfolio company. Which company is this for?"
        if sender_phone:
            send_whatsapp(sender_phone, msg)
        send_email_simple(sender_email, f"Re: {subject}", msg + "\n\n- Christina")
        log.info('Asked sender to clarify portfolio company')
        mark_email_processed(thread_id)
        return False

    is_lp = is_lp_email(subject, body)

    # Determine pipeline and stage
    if is_lp:
        pipeline_id = SECONDARY_PIPELINE
        stage_id = SECONDARY_STAGE
        deal_suffix = ' - LP'
        log.info('Detected: LP Deal')
    else:
        pipeline_id = DEFAULT_PIPELINE
        stage_id = DEFAULT_STAGE
        deal_suffix = ' - Initial Meeting'
        log.info('Detected: VC Deal Flow')

    company_data = extract_company_info({"subject": subject, "from": from_email, "id": thread_id})

    # Check for deck links and analyze if found (may override company name)
    deck_links = extract_deck_links(f'{subject} {body}')
    deck_description = None
    analysis = None

    if deck_links and ANTHROPIC_API_KEY:
        link = deck_links[0]
        log.info('Found deck link: %s...', link[:50])
        log.debug('Analyzing deck with Claude...')

        if is_papermark_link(link):
            log.debug('Papermark link detected \u2014 using Camofox browser')
            images = fetch_papermark_with_camofox(link)
            if images:
                log.info('Captured %d page(s), sending to Claude vision...', len(images))
                analysis = analyze_deck_images_with_claude(images, company_data['name'])
            else:
                log.warning('Could not fetch Papermark deck via browser')
        elif is_docsend_link(link):
            log.debug('DocSend link detected \u2014 using Camofox browser')
            images = fetch_docsend_with_camofox(link)
            if images:
                log.info('Captured %d page(s), sending to Claude vision...', len(images))
                analysis = analyze_deck_images_with_claude(images, company_data['name'])
            else:
                log.warning('Could not fetch DocSend deck via browser')
        else:
            deck_content = fetch_deck_with_browser(link, sender_email)
            if deck_content:
                analysis = analyze_deck_with_claude(deck_content, company_data['name'])
            else:
                log.warning('Could not fetch deck')

        if analysis:
            deck_description = format_deck_description(analysis)
            log.info('Deck analyzed successfully')

            # Extract company name from analysis
            extracted_name = extract_company_name_from_analysis(analysis)
            if extracted_name:
                company_data['name'] = extracted_name
                log.info('Company name: %s', extracted_name)

            # Update company description with deck analysis
            if deck_description:
                company_data['description'] = deck_description
        elif deck_links:
            log.warning('Deck analysis failed')

    # Check for deck attachments if no link found
    if not deck_description and ANTHROPIC_API_KEY:
        attachments = get_email_attachments(thread_id)
        pdf_attachments = [a for a in attachments if a['filename'].lower().endswith('.pdf')]

        if pdf_attachments:
            attachment = pdf_attachments[0]  # Process first PDF
            log.info('Found deck attachment: %s', attachment["filename"])
            log.debug('Downloading and analyzing with Claude...')

            pdf_path = download_attachment(attachment['message_id'], attachment['id'], attachment['filename'])
            if pdf_path:
                pdf_text = extract_pdf_text(pdf_path)
                if pdf_text:
                    analysis = analyze_deck_with_claude(pdf_text, company_data['name'])
                    if analysis:
                        deck_description = format_deck_description(analysis)
                        log.info('Deck attachment analyzed successfully')

                        # Extract company name from analysis
                        extracted_name = extract_company_name_from_analysis(analysis)
                        if extracted_name:
                            company_data['name'] = extracted_name
                            log.info('Company name: %s', extracted_name)

                        # Update company description with deck analysis
                        if deck_description:
                            company_data['description'] = deck_description
                    else:
                        log.warning('Deck analysis failed')
                else:
                    log.warning('Could not extract text from PDF')

                # Clean up temp file
                try:
                    os.remove(pdf_path)
                except OSError:
                    pass
            else:
                log.warning('Could not download attachment')

    # Fallback: if company name looks bad, try domain extraction then Claude
    if _is_bad_company_name(company_data['name']):
        log.debug('Bad company name "%s" \u2014 trying fallbacks', company_data["name"])
        # Try extracting from email domains in thread
        domain_name = _extract_company_from_email_domains(thread_data)
        if domain_name and not _is_bad_company_name(domain_name):
            log.debug('Domain fallback: %s', domain_name)
            company_data['name'] = domain_name
        else:
            # Try Claude extraction
            claude_name = _extract_company_with_claude(subject, body)
            if claude_name and not _is_bad_company_name(claude_name):
                company_data['name'] = claude_name
            else:
                log.warning('All fallbacks failed for company name')

    # If company name couldn't be resolved, ask the user via WhatsApp
    if not company_data['name'] or _is_bad_company_name(company_data['name']):
        sender_phone = EMAIL_TO_PHONE.get(sender_email)
        if sender_phone:
            send_whatsapp(sender_phone, f"New email: \"{subject}\"\n\nI couldn't figure out the company name. What's the company?")
            log.info('Asked user for company name via WhatsApp')
        else:
            log.warning('Skipped: Could not determine company name and no phone for sender')
        mark_email_processed(thread_id)
        return False

    # Check if this company is actually a portfolio company
    portfolio_companies = {v.lower(): v for v in PORTFOLIO.values()}
    company_lower = company_data['name'].lower()
    matched_portfolio = None
    for pc_lower, pc_name in portfolio_companies.items():
        if company_lower == pc_lower or company_lower in pc_lower or pc_lower in company_lower:
            matched_portfolio = pc_name
            break

    if matched_portfolio:
        log.info('Detected portfolio company: %s', matched_portfolio)
        sender_phone = EMAIL_TO_PHONE.get(sender_email)
        msg = f"I got your email about {matched_portfolio}. This looks like a portfolio company update, not a new deal. Should I log it as a portfolio touchpoint, or is this actually a new deal?"
        if sender_phone:
            send_whatsapp(sender_phone, msg)
        send_email_simple(sender_email, f"Re: {subject}", msg + "\n\n- Christina")
        log.info('Asked sender about portfolio company: %s', matched_portfolio)
        mark_email_processed(thread_id)
        return False

    # When uncertain (no deck, no analysis), ask sender what to do
    if not deck_links and not analysis:
        intent = _classify_email_intent(subject, body)
        if intent == 'UNCERTAIN':
            sender_phone = EMAIL_TO_PHONE.get(sender_email)
            msg = f"I got your email \"{subject}\" but I'm not sure what to do with it. Should I:\n1. Log as a new deal\n2. Log as a portfolio update\n3. Ignore it"
            if sender_phone:
                send_whatsapp(sender_phone, msg)
            send_email_simple(sender_email, f"Re: {subject}", msg + "\n\n- Christina")
            log.info('Asked sender about uncertain email intent')
            mark_email_processed(thread_id)
            return False

    # Check for existing company to avoid duplicates
    existing_company_id = search_hubspot_company(company_data['name'])
    if existing_company_id:
        log.info('Found existing company: %s (ID: %s)', company_data["name"], existing_company_id)
        company_id = existing_company_id

        # Update description if we have new deck analysis
        if deck_description:
            try:
                url = f'{MATON_BASE_URL}/crm/v3/objects/companies/{company_id}'
                headers = {
                    'Authorization': f'Bearer {MATON_API_KEY}',
                    'Content-Type': 'application/json'
                }
                payload = {'properties': {'description': company_data['description']}}
                requests.patch(url, headers=headers, json=payload, timeout=10)
                log.info('Updated company description with deck analysis')
            except Exception:
                pass
    else:
        company_id = create_hubspot_company(company_data)
        if not company_id:
            return False

    deal_name = company_data['name']

    # Check for existing deal before creating a duplicate
    existing_deal_id = search_hubspot_deal(deal_name)
    if existing_deal_id:
        existing_deal_url = f'https://app.hubspot.com/contacts/{config.hubspot_portal_id}/record/0-3/{existing_deal_id}'
        log.info('Deal already exists: %s (ID: %s)', deal_name, existing_deal_id)
        sender_phone = EMAIL_TO_PHONE.get(sender_email)
        if sender_phone:
            send_whatsapp(sender_phone, f"I got your email about {deal_name}, but there's already a deal in HubSpot:\n{existing_deal_url}\n\nShould I update it or create a new one?")
            log.info('Asked sender about existing deal')
        mark_email_processed(thread_id)
        return True

    deal_id = create_hubspot_deal(deal_name, company_id, sender_email, pipeline_id, stage_id)

    if deal_id:
        # Send confirmation email
        deal_url = f'https://app.hubspot.com/contacts/{config.hubspot_portal_id}/record/0-3/{deal_id}'
        pipeline_name = PIPELINE_NAMES.get(pipeline_id, pipeline_id)
        stage_name = STAGE_NAMES.get(stage_id, stage_id)
        send_confirmation_email(sender_email, company_data['name'], pipeline_name, stage_name, deal_url)

        # Save state for manual full report request (user must explicitly ask)
        if analysis:
            deck_data = parse_analysis_to_deck_data(analysis)
            deck_url_for_state = deck_links[0] if deck_links else None
            save_deal_analyzer_state(deck_data, deck_url_for_state)

        mark_email_processed(thread_id)
        return True

    return False


def main():
    # Prevent overlapping cron runs with file lock
    lock_path = os.path.join(tempfile.gettempdir(), 'email-to-deal-automation.lock')
    lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.warning('Another instance is already running, exiting.')
        sys.exit(0)

    log.info('===== Email to Deal Automation =====')
    if not MATON_API_KEY:
        log.error('MATON_API_KEY not set')
        sys.exit(1)

    # Check for opt-in/opt-out requests first
    from .config import check_optin_optout_requests
    check_optin_optout_requests()

    # Check for WhatsApp deal submissions
    check_whatsapp_deals()

    # Check RoastMyDeck analysis emails
    rmd_threads = check_roastmydeck_emails()
    rmd_count = 0
    if rmd_threads:
        log.info('Found %d RoastMyDeck email(s)', len(rmd_threads))
        for t in rmd_threads:
            if process_roastmydeck_email(t["id"]):
                rmd_count += 1
        log.info('RoastMyDeck processed: %d/%d', rmd_count, len(rmd_threads))
    else:
        log.debug('No RoastMyDeck emails')

    threads = check_recent_emails()
    if not threads:
        log.info('No new emails')
        return
    log.info('Found %d emails', len(threads))
    processed = sum(1 for thread in threads if process_email(thread))
    log.info('Processed: %d/%d', processed, len(threads))
