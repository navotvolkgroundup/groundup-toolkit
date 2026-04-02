#!/usr/bin/env python3
"""
Meeting Logger — Log meeting notes to HubSpot portfolio company records.

Usage:
    meeting-logger log <company_name> <notes...>
    meeting-logger log-message <full_message>
"""
import os, sys, re, json
from pathlib import Path

TOOLKIT_ROOT = os.environ.get("TOOLKIT_ROOT", str(Path.home() / ".openclaw"))
sys.path.insert(0, TOOLKIT_ROOT)
sys.path.insert(0, os.path.join(TOOLKIT_ROOT, "scripts"))

from portfolio_monitor import handle_whatsapp_log, fuzzy_lookup_name
from lib.claude import call_claude


# -- Message parsing -----------------------------------------------------------

# Patterns: "log to Company: notes", "meeting notes for Company: notes", etc.
_PATTERNS = [
    re.compile(r"(?i)^log\s+(?:to|for)\s+(.+?):\s*([\s\S]+)", re.DOTALL),
    re.compile(r"(?i)^meeting\s+notes?\s+(?:for|from|with|about)\s+(.+?):\s*([\s\S]+)", re.DOTALL),
    re.compile(r"(?i)^notes?\s+(?:for|from|with|about)\s+(.+?):\s*([\s\S]+)", re.DOTALL),
    re.compile(r"(?i)^log\s+(?:under|in)\s+(.+?):\s*([\s\S]+)", re.DOTALL),
]


def parse_message(text):
    """Extract (company_name, notes) from a message. Returns (None, text) if no match."""
    text = text.strip()

    # Try regex patterns first (fast, no API call)
    for pattern in _PATTERNS:
        m = pattern.match(text)
        if m:
            company = m.group(1).strip().rstrip(".-,;")
            notes = m.group(2).strip()
            if company and notes:
                return company, notes

    # Fallback: ask Claude to find the company name in freeform notes
    prompt = f"""This message contains meeting notes that should be logged to a portfolio company record.
Extract the company name being discussed. Look for company names in meeting titles, headers, or context.

Message (first 1500 chars):
{text[:1500]}

Return ONLY valid JSON (no markdown fences):
{{"company": "company name or null if not identifiable"}}"""

    try:
        result = call_claude(prompt, system_prompt="You are a precise data extractor. Return only valid JSON.")
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', result.strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        company = data.get("company")
        if company and company.lower() != "null":
            return company, text
    except Exception:
        pass

    return None, text


# -- Commands ------------------------------------------------------------------

def cmd_log(company_name, notes, sender_phone=""):
    """Log meeting notes for a specific company."""
    # Fuzzy match first to give a good error message
    matched = fuzzy_lookup_name(company_name)
    if not matched:
        print(f'Could not match "{company_name}" to a portfolio company. '
              f"Please specify the exact company name.")
        return

    result = handle_whatsapp_log(matched, notes, sender_phone)

    if result and "error" in result:
        print(f"Error: {result['error']}")
        return

    if result and "company_name" in result:
        co = result["company_name"]
        metrics = result.get("metrics", {})
        health = metrics.get("health_score", "")
        summary = metrics.get("summary", "")

        lines = [f"Logged meeting notes to {co} in HubSpot."]
        if summary:
            lines.append(f"Summary: {summary}")
        if health:
            lines.append(f"Health: {health}")
        actions = metrics.get("next_actions", [])
        if actions:
            lines.append("Action items:")
            for a in actions[:5]:
                lines.append(f"  - {a}")
        print("\n".join(lines))
    else:
        print("Failed to log meeting notes.")


def cmd_log_message(message, sender_phone=""):
    """Parse a full message to extract company and notes, then log."""
    company, notes = parse_message(message)
    if not company:
        print("Could not identify which portfolio company these notes are for.\n"
              'Try: "log to [Company Name]: [your notes]"')
        return
    cmd_log(company, notes, sender_phone)


# -- Main ----------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <log|log-message> [args...]")
        sys.exit(1)

    action = sys.argv[1]

    if action == "log":
        if len(sys.argv) < 4:
            print(f"Usage: {sys.argv[0]} log <company_name> <notes...>")
            sys.exit(1)
        company = sys.argv[2]
        notes = " ".join(sys.argv[3:])
        phone = os.environ.get("SENDER_PHONE", "")
        cmd_log(company, notes, phone)

    elif action == "log-message":
        message = " ".join(sys.argv[2:])
        phone = os.environ.get("SENDER_PHONE", "")
        cmd_log_message(message, phone)

    else:
        print(f"Unknown command: {action}")
        sys.exit(1)
