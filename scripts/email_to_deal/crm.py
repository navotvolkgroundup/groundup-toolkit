"""HubSpot CRM operations: create company, create deal, search, associate."""

import logging
import requests
from difflib import SequenceMatcher

log = logging.getLogger("email-to-deal")

from .config import (MATON_API_KEY, MATON_BASE_URL, OWNER_IDS,
                      PIPELINE_NAMES, STAGE_NAMES)


def create_hubspot_company(company_data):
    if not MATON_API_KEY:
        log.error('MATON_API_KEY not set')
        return None
    url = f'{MATON_BASE_URL}/crm/v3/objects/companies'
    headers = {'Authorization': f'Bearer {MATON_API_KEY}', 'Content-Type': 'application/json'}
    payload = {'properties': {'name': company_data['name'], 'description': company_data.get('description', '')}}
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        log.info('Created company: %s (ID: %s)', company_data["name"], result["id"])
        return result['id']
    except Exception as e:
        log.error('Error creating company: %s', e)
        return None

def create_hubspot_deal(deal_name, company_id, owner_email, pipeline_id, stage_id):
    if not MATON_API_KEY:
        return None
    url = f'{MATON_BASE_URL}/crm/v3/objects/deals'
    headers = {'Authorization': f'Bearer {MATON_API_KEY}', 'Content-Type': 'application/json'}

    owner_id = OWNER_IDS.get(owner_email)

    payload = {
        'properties': {
            'dealname': deal_name,
            'dealstage': stage_id,
            'pipeline': pipeline_id
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        deal_id = result['id']
        log.info('Created deal: %s (ID: %s)', deal_name, deal_id)
        log.info('Pipeline: %s, Stage: %s', PIPELINE_NAMES.get(pipeline_id, pipeline_id), STAGE_NAMES.get(stage_id, stage_id))

        if owner_id:
            update_deal_owner(deal_id, owner_id, owner_email)

        if company_id:
            associate_deal_company(deal_id, company_id)
        return deal_id
    except Exception as e:
        log.error('Error creating deal: %s', e)
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            log.error('Response: %s', e.response.text)
        return None

def update_deal_owner(deal_id, owner_id, owner_email):
    url = f'{MATON_BASE_URL}/crm/v3/objects/deals/{deal_id}'
    headers = {'Authorization': f'Bearer {MATON_API_KEY}', 'Content-Type': 'application/json'}
    payload = {'properties': {'hubspot_owner_id': owner_id}}
    try:
        response = requests.patch(url, headers=headers, json=payload)
        response.raise_for_status()
        log.info('Assigned deal to %s (ID: %s)', owner_email, owner_id)
        return True
    except Exception as e:
        log.error('Error assigning owner: %s', e)
        return False

def associate_deal_company(deal_id, company_id):
    url = f'{MATON_BASE_URL}/crm/v4/objects/deals/{deal_id}/associations/companies/{company_id}'
    headers = {'Authorization': f'Bearer {MATON_API_KEY}', 'Content-Type': 'application/json'}
    payload = [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 341}]
    try:
        response = requests.put(url, headers=headers, json=payload)
        response.raise_for_status()
        log.info('Associated deal with company')
        return True
    except Exception as e:
        log.error('Error associating: %s', e)
        return False


def search_hubspot_company(company_name):
    """Search for existing company in HubSpot by name"""
    try:
        url = f'{MATON_BASE_URL}/crm/v3/objects/companies/search'
        headers = {
            'Authorization': f'Bearer {MATON_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'filterGroups': [{
                'filters': [{
                    'propertyName': 'name',
                    'operator': 'EQ',
                    'value': company_name
                }]
            }],
            'properties': ['name', 'description'],
            'limit': 1
        }

        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                return results[0]['id']
        return None
    except Exception as e:
        log.error('Error searching for company: %s', e)
        return None


def search_hubspot_deal(deal_name):
    """Search for existing deal in HubSpot by name (case-insensitive)."""
    try:
        url = f'{MATON_BASE_URL}/crm/v3/objects/deals/search'
        headers = {
            'Authorization': f'Bearer {MATON_API_KEY}',
            'Content-Type': 'application/json'
        }
        # Normalize: strip common suffixes like Ltd, Inc, .ai etc for broader match
        name_clean = deal_name.strip()
        payload = {
            'filterGroups': [{
                'filters': [{
                    'propertyName': 'dealname',
                    'operator': 'EQ',
                    'value': name_clean
                }]
            }],
            'properties': ['dealname', 'dealstage'],
            'limit': 1
        }
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                return results[0]['id']
        return None
    except Exception as e:
        log.error('Error searching for deal: %s', e)
        return None


def _fuzzy_search_company(company_name):
    """Search HubSpot for a company using fuzzy CONTAINS_TOKEN matching.

    Returns company ID if a result scores >= 0.85 similarity, else None.
    """
    if not MATON_API_KEY or not company_name:
        return None
    try:
        url = f'{MATON_BASE_URL}/crm/v3/objects/companies/search'
        headers = {
            'Authorization': f'Bearer {MATON_API_KEY}',
            'Content-Type': 'application/json'
        }
        # Use the longest token (word) for CONTAINS_TOKEN search
        tokens = company_name.split()
        search_token = max(tokens, key=len) if tokens else company_name
        payload = {
            'filterGroups': [{
                'filters': [{
                    'propertyName': 'name',
                    'operator': 'CONTAINS_TOKEN',
                    'value': search_token
                }]
            }],
            'properties': ['name', 'domain'],
            'limit': 10
        }
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code != 200:
            return None

        results = response.json().get('results', [])
        if not results:
            return None

        name_lower = company_name.lower().strip()
        best_id = None
        best_ratio = 0.0

        for r in results:
            hs_name = r.get('properties', {}).get('name', '')
            ratio = SequenceMatcher(None, name_lower, hs_name.lower().strip()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_id = r['id']

        if best_ratio >= 0.85:
            log.info('Fuzzy match: "%s" ~ HubSpot company ID %s (%.0f%%)', company_name, best_id, best_ratio * 100)
            return best_id
        return None
    except Exception as e:
        log.error('Error in fuzzy company search: %s', e)
        return None


def _search_company_by_domain(domain):
    """Search HubSpot for a company by domain (exact match).

    Returns company ID or None.
    """
    if not MATON_API_KEY or not domain:
        return None
    try:
        url = f'{MATON_BASE_URL}/crm/v3/objects/companies/search'
        headers = {
            'Authorization': f'Bearer {MATON_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'filterGroups': [{
                'filters': [{
                    'propertyName': 'domain',
                    'operator': 'EQ',
                    'value': domain
                }]
            }],
            'properties': ['name', 'domain'],
            'limit': 1
        }
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                log.info('Domain match: %s -> company ID %s', domain, results[0]['id'])
                return results[0]['id']
        return None
    except Exception as e:
        log.error('Error searching company by domain: %s', e)
        return None


def find_or_create_company(name, description='', domain=None):
    """Find an existing HubSpot company or create a new one.

    Multi-strategy dedup:
      1. Search by domain (exact match) if provided
      2. Search by exact name (EQ)
      3. Search by fuzzy name (CONTAINS_TOKEN + SequenceMatcher >= 0.85)
      4. Create new company if no match found

    Returns:
        Company ID string, or None on failure.
    """
    # Strategy 1: domain match
    if domain:
        company_id = _search_company_by_domain(domain)
        if company_id:
            return company_id

    # Strategy 2: exact name match
    company_id = search_hubspot_company(name)
    if company_id:
        return company_id

    # Strategy 3: fuzzy name match
    company_id = _fuzzy_search_company(name)
    if company_id:
        return company_id

    # Strategy 4: create new
    log.info('No existing company found for "%s" — creating new', name)
    return create_hubspot_company({'name': name, 'description': description})
