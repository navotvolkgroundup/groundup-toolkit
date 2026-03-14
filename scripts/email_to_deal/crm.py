"""HubSpot CRM operations: create company, create deal, search, associate."""

import logging
import requests

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
