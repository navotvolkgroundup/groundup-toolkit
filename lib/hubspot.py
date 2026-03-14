"""
Shared HubSpot CRM operations via Maton API gateway.

Usage:
    from lib.hubspot import (
        search_company, create_company, create_deal,
        update_deal_stage, add_note, associate_deal_company,
        get_company_for_deal, get_deals_for_company, get_latest_note,
        fetch_deals_by_stage
    )

    company_id = search_company(name="Acme Corp")
    company_id = search_company(domain="acme.com")
    deal_id = create_deal("Acme Corp - Seed", company_id=company_id)
"""

import sys
import requests
from datetime import datetime
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from lib.config import config

MATON_API_KEY = config.maton_api_key
MATON_BASE_URL = config.hubspot_api_gateway

_HEADERS = {
    "Authorization": f"Bearer {MATON_API_KEY}",
    "Content-Type": "application/json"
}

# Reuse TCP connections across calls within the same process
_session = requests.Session()
_session.headers.update(_HEADERS)

# Automatic retries for transient HTTP errors
_retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
_adapter = HTTPAdapter(max_retries=_retry_strategy)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

# --- Association type IDs (HubSpot standard) ---
ASSOC_DEAL_TO_COMPANY = 341
ASSOC_NOTE_TO_COMPANY = 190
ASSOC_NOTE_TO_DEAL = 214


def _url(path):
    """Build full API URL."""
    return f"{MATON_BASE_URL}/{path.lstrip('/')}"


# --- Company Operations ---

def search_company(name=None, domain=None):
    """Search HubSpot for a company by name or domain.

    Args:
        name: Company name (uses CONTAINS_TOKEN search).
        domain: Company domain (uses EQ search).

    Returns:
        Company dict with id and properties, or None.
    """
    if not MATON_API_KEY:
        return None

    if domain:
        filters = [{"propertyName": "domain", "operator": "EQ", "value": domain}]
    elif name:
        filters = [{"propertyName": "name", "operator": "CONTAINS_TOKEN", "value": name}]
    else:
        return None

    try:
        response = _session.post(
            _url("crm/v3/objects/companies/search"),
            headers=_HEADERS,
            json={
                "filterGroups": [{"filters": filters}],
                "properties": ["name", "domain", "industry", "description"],
                "limit": 5,
            },
            timeout=10,
        )
        if response.status_code != 200:
            return None

        results = response.json().get("results", [])
        if not results:
            return None

        # Exact name match preferred
        if name:
            for r in results:
                if r.get("properties", {}).get("name", "").lower() == name.lower():
                    return r
        return results[0]
    except Exception as e:
        print(f"  HubSpot search error: {e}", file=sys.stderr)
        return None


def create_company(name, description=""):
    """Create a new HubSpot company.

    Returns:
        Company ID string, or None on failure.
    """
    if not MATON_API_KEY:
        return None

    try:
        response = _session.post(
            _url("crm/v3/objects/companies"),
            headers=_HEADERS,
            json={"properties": {"name": name, "description": description}},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        print(f"  Created company: {name} (ID: {result['id']})")
        return result["id"]
    except Exception as e:
        print(f"  Error creating company: {e}", file=sys.stderr)
        return None


# --- Deal Operations ---

def create_deal(deal_name, company_id=None, owner_id=None, pipeline_id=None, stage_id=None):
    """Create a new HubSpot deal.

    Args:
        deal_name: Deal name.
        company_id: Optional company ID to associate.
        owner_id: Optional HubSpot owner ID.
        pipeline_id: Pipeline ID (default: from config).
        stage_id: Deal stage ID (default: from config).

    Returns:
        Deal ID string, or None on failure.
    """
    if not MATON_API_KEY:
        return None

    pipeline_id = pipeline_id or config.hubspot_default_pipeline
    stage_id = stage_id or config.hubspot_deal_stage

    properties = {
        "dealname": deal_name,
        "dealstage": stage_id,
        "pipeline": pipeline_id,
    }
    if owner_id:
        properties["hubspot_owner_id"] = str(owner_id)

    try:
        response = _session.post(
            _url("crm/v3/objects/deals"),
            headers=_HEADERS,
            json={"properties": properties},
            timeout=10,
        )
        response.raise_for_status()
        deal_id = response.json()["id"]
        print(f"  Created deal: {deal_name} (ID: {deal_id})")

        if company_id:
            associate_deal_company(deal_id, company_id)

        return deal_id
    except Exception as e:
        print(f"  Error creating deal: {e}", file=sys.stderr)
        return None


def update_deal_stage(deal_id, stage_id, close_date=None):
    """Move a deal to a new stage.

    Args:
        deal_id: HubSpot deal ID.
        stage_id: Target stage ID (e.g., "closedlost").
        close_date: Optional close date string (YYYY-MM-DD).

    Returns:
        True on success, False on failure.
    """
    properties = {"dealstage": stage_id}
    if close_date:
        properties["closedate"] = close_date

    try:
        response = _session.patch(
            _url(f"crm/v3/objects/deals/{deal_id}"),
            json={"properties": properties},
            timeout=10,
        )
        if response.status_code == 200:
            return True
        print(f"  Failed to update deal {deal_id}: {response.status_code}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  Error updating deal: {e}", file=sys.stderr)
        return False


def update_deal_owner(deal_id, owner_id):
    """Assign a deal to an owner.

    Returns:
        True on success, False on failure.
    """
    try:
        response = _session.patch(
            _url(f"crm/v3/objects/deals/{deal_id}"),
            json={"properties": {"hubspot_owner_id": str(owner_id)}},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"  Error assigning owner: {e}", file=sys.stderr)
        return False


def fetch_deals_by_stage(stage_id, properties=None):
    """Fetch all deals in a specific stage.

    Args:
        stage_id: Deal stage ID.
        properties: List of property names to fetch.

    Returns:
        List of deal dicts.
    """
    if not MATON_API_KEY:
        return []

    properties = properties or ["dealname", "hubspot_owner_id", "description", "createdate", "hs_lastmodifieddate"]

    try:
        response = _session.post(
            _url("crm/v3/objects/deals/search"),
            headers=_HEADERS,
            json={
                "filterGroups": [{"filters": [{"propertyName": "dealstage", "operator": "EQ", "value": stage_id}]}],
                "properties": properties,
                "limit": 100,
            },
            timeout=15,
        )
        if response.status_code == 200:
            return response.json().get("results", [])
        return []
    except Exception as e:
        print(f"  Error fetching deals: {e}", file=sys.stderr)
        return []


# --- Association Operations ---

def associate_deal_company(deal_id, company_id):
    """Associate a deal with a company.

    Returns:
        True on success, False on failure.
    """
    try:
        response = _session.put(
            _url(f"crm/v4/objects/deals/{deal_id}/associations/companies/{company_id}"),
            json=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC_DEAL_TO_COMPANY}],
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"  Error associating deal/company: {e}", file=sys.stderr)
        return False


def get_company_for_deal(deal_id):
    """Get the associated company for a deal.

    Returns:
        Company dict with properties, or None.
    """
    try:
        response = _session.get(
            _url(f"crm/v4/objects/deals/{deal_id}/associations/companies"),
            headers=_HEADERS,
            timeout=10,
        )
        if response.status_code != 200:
            return None

        results = response.json().get("results", [])
        if not results:
            return None

        company_id = results[0]["toObjectId"]
        response = _session.get(
            _url(f"crm/v3/objects/companies/{company_id}"),
            headers=_HEADERS,
            params={"properties": "name,domain,description"},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


def get_deals_for_company(company_id, limit=3):
    """Get deals associated with a company.

    Args:
        company_id: HubSpot company ID.
        limit: Max deals to return (default: 3).

    Returns:
        List of deal dicts.
    """
    if not MATON_API_KEY or not company_id:
        return []

    try:
        response = _session.get(
            _url(f"crm/v3/objects/companies/{company_id}/associations/deals"),
            headers=_HEADERS,
            timeout=10,
        )
        if response.status_code != 200:
            return []

        deal_ids = [assoc["id"] for assoc in response.json().get("results", [])]
        if not deal_ids:
            return []

        deals = []
        for did in deal_ids[:limit]:
            resp = _session.get(
                _url(f"crm/v3/objects/deals/{did}"),
                headers=_HEADERS,
                params={"properties": "dealname,dealstage,amount,closedate"},
                timeout=10,
            )
            if resp.status_code == 200:
                deals.append(resp.json())
        return deals
    except Exception as e:
        print(f"  Error fetching deals: {e}", file=sys.stderr)
        return []


# --- Note Operations ---

def add_note(object_id, note_text, object_type="deals"):
    """Add a note to a HubSpot object (deal or company).

    Args:
        object_id: HubSpot object ID.
        note_text: Note body text.
        object_type: "deals" or "companies" (default: "deals").

    Returns:
        True on success, False on failure.
    """
    assoc_type = ASSOC_NOTE_TO_DEAL if object_type == "deals" else ASSOC_NOTE_TO_COMPANY

    try:
        response = _session.post(
            _url("crm/v3/objects/notes"),
            headers=_HEADERS,
            json={
                "properties": {
                    "hs_timestamp": str(int(datetime.now().timestamp() * 1000)),
                    "hs_note_body": note_text,
                },
                "associations": [{
                    "to": {"id": object_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": assoc_type}],
                }],
            },
            timeout=10,
        )
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"  HubSpot note error: {e}", file=sys.stderr)
        return False


def get_latest_note(company_id):
    """Get the latest note for a company.

    Returns:
        Note body text (truncated to 200 chars), or None.
    """
    if not MATON_API_KEY or not company_id:
        return None

    try:
        response = _session.get(
            _url(f"crm/v3/objects/companies/{company_id}/associations/notes"),
            headers=_HEADERS,
            params={"limit": 1},
            timeout=10,
        )
        if response.status_code != 200:
            return None

        results = response.json().get("results", [])
        if not results:
            return None

        note_id = results[0]["id"]
        resp = _session.get(
            _url(f"crm/v3/objects/notes/{note_id}"),
            headers=_HEADERS,
            params={"properties": "hs_note_body"},
            timeout=10,
        )
        if resp.status_code == 200:
            body = resp.json().get("properties", {}).get("hs_note_body", "")
            if len(body) > 200:
                body = body[:200] + "..."
            return body
        return None
    except Exception as e:
        print(f"  Error fetching notes: {e}", file=sys.stderr)
        return None


# --- Contact Operations ---

ASSOC_CONTACT_TO_COMPANY = 279
ASSOC_CONTACT_TO_DEAL = 4


def search_contact(email=None, linkedin_url=None, name=None):
    """Search HubSpot for a contact by email, LinkedIn URL, or name.

    Returns:
        Contact dict with id and properties, or None.
    """
    if not MATON_API_KEY:
        return None

    if email:
        filters = [{"propertyName": "email", "operator": "EQ", "value": email}]
    elif linkedin_url:
        filters = [{"propertyName": "hs_linkedin_url", "operator": "EQ", "value": linkedin_url}]
    elif name:
        filters = [{"propertyName": "firstname", "operator": "CONTAINS_TOKEN", "value": name.split()[0]}]
    else:
        return None

    try:
        response = _session.post(
            _url("crm/v3/objects/contacts/search"),
            headers=_HEADERS,
            json={
                "filterGroups": [{"filters": filters}],
                "properties": ["firstname", "lastname", "email", "hs_linkedin_url",
                               "lifecyclestage", "hs_lead_status", "company"],
                "limit": 5,
            },
            timeout=10,
        )
        if response.status_code != 200:
            return None

        results = response.json().get("results", [])
        if not results:
            return None

        # If searching by name, try to match full name
        if name and len(results) > 1:
            name_lower = name.lower()
            for r in results:
                props = r.get("properties", {})
                full = f"{props.get('firstname', '')} {props.get('lastname', '')}".strip().lower()
                if full == name_lower:
                    return r
        return results[0]
    except Exception as e:
        print(f"  HubSpot contact search error: {e}", file=sys.stderr)
        return None


def create_contact(firstname, lastname="", linkedin_url=None, properties=None):
    """Create a new HubSpot contact.

    Args:
        firstname: First name.
        lastname: Last name.
        linkedin_url: LinkedIn profile URL (stored in hs_linkedin_url).
        properties: Additional properties dict.

    Returns:
        Contact ID string, or None on failure.
    """
    if not MATON_API_KEY:
        return None

    props = {"firstname": firstname, "lastname": lastname,
             "lifecyclestage": "lead"}
    if linkedin_url:
        props["hs_linkedin_url"] = linkedin_url
    if properties:
        props.update(properties)

    try:
        response = _session.post(
            _url("crm/v3/objects/contacts"),
            headers=_HEADERS,
            json={"properties": props},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        print(f"  Created contact: {firstname} {lastname} (ID: {result['id']})")
        return result["id"]
    except Exception as e:
        detail = ""
        if hasattr(e, "response") and e.response is not None:
            try:
                detail = f" — {e.response.json().get('message', e.response.text[:200])}"
            except Exception:
                detail = f" — {e.response.text[:200]}"
        print(f"  Error creating contact: {e}{detail}", file=sys.stderr)
        return None


def update_contact(contact_id, properties):
    """Update a HubSpot contact's properties.

    Returns:
        True on success, False on failure.
    """
    try:
        response = _session.patch(
            _url(f"crm/v3/objects/contacts/{contact_id}"),
            json={"properties": properties},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        detail = ""
        if hasattr(e, "response") and e.response is not None:
            try:
                detail = f" — {e.response.json().get('message', e.response.text[:200])}"
            except Exception:
                detail = f" — {e.response.text[:200]}"
        print(f"  Error updating contact {contact_id}: {e}{detail}", file=sys.stderr)
        return False


def associate_contact_company(contact_id, company_id):
    """Associate a contact with a company.

    Returns:
        True on success, False on failure.
    """
    try:
        response = _session.put(
            _url(f"crm/v4/objects/contacts/{contact_id}/associations/companies/{company_id}"),
            json=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC_CONTACT_TO_COMPANY}],
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"  Error associating contact/company: {e}", file=sys.stderr)
        return False
