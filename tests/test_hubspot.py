"""Tests for the shared HubSpot CRM library (lib/hubspot.py).

All HTTP calls are mocked via unittest.mock.patch so no real API requests
are made.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the repo root is on sys.path and mock lib.config before importing
REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, REPO_ROOT)

# Build a fake config that satisfies module-level attribute accesses
_fake_config = MagicMock()
_fake_config.maton_api_key = 'test-api-key'
_fake_config.hubspot_api_gateway = 'https://gateway.example.com/hubspot'
_fake_config.hubspot_default_pipeline = 'pipeline-default'
_fake_config.hubspot_deal_stage = 'stage-default'

_fake_lib_config = MagicMock()
_fake_lib_config.config = _fake_config

# Remove any stale 'lib' mock from sys.modules (e.g. from other test files),
# then register our fake config so the real lib package can import cleanly.
if 'lib' in sys.modules and not hasattr(sys.modules['lib'], '__path__'):
    del sys.modules['lib']
sys.modules['lib.config'] = _fake_lib_config

import lib.hubspot as hubspot  # noqa: E402


BASE = 'https://gateway.example.com/hubspot'


# ---------------------------------------------------------------------------
# Tests: _url helper
# ---------------------------------------------------------------------------

class TestUrlHelper(unittest.TestCase):

    def test_simple_path(self):
        self.assertEqual(hubspot._url('crm/v3/objects/deals'), f'{BASE}/crm/v3/objects/deals')

    def test_leading_slash_stripped(self):
        self.assertEqual(hubspot._url('/crm/v3/objects/deals'), f'{BASE}/crm/v3/objects/deals')

    def test_empty_path(self):
        self.assertEqual(hubspot._url(''), f'{BASE}/')


# ---------------------------------------------------------------------------
# Tests: search_company
# ---------------------------------------------------------------------------

class TestSearchCompany(unittest.TestCase):

    @patch.object(hubspot._session, 'post')
    def test_search_by_domain_found(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [{
                'id': '100',
                'properties': {'name': 'Acme Corp', 'domain': 'acme.com'}
            }]
        }
        mock_post.return_value = mock_resp

        result = hubspot.search_company(domain='acme.com')
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], '100')
        # Verify correct URL was called
        call_args = mock_post.call_args
        self.assertIn('companies/search', call_args[0][0])

    @patch.object(hubspot._session, 'post')
    def test_search_by_name_exact_match_preferred(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [
                {'id': '200', 'properties': {'name': 'Acme Industries'}},
                {'id': '201', 'properties': {'name': 'Acme Corp'}},
            ]
        }
        mock_post.return_value = mock_resp

        result = hubspot.search_company(name='Acme Corp')
        self.assertEqual(result['id'], '201')

    @patch.object(hubspot._session, 'post')
    def test_search_by_name_no_exact_returns_first(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [
                {'id': '300', 'properties': {'name': 'Acme Industries'}},
                {'id': '301', 'properties': {'name': 'Acme Ltd'}},
            ]
        }
        mock_post.return_value = mock_resp

        result = hubspot.search_company(name='Acme Corp')
        self.assertEqual(result['id'], '300')

    @patch.object(hubspot._session, 'post')
    def test_search_not_found(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'results': []}
        mock_post.return_value = mock_resp

        result = hubspot.search_company(domain='nonexistent.com')
        self.assertIsNone(result)

    @patch.object(hubspot._session, 'post')
    def test_search_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        result = hubspot.search_company(domain='acme.com')
        self.assertIsNone(result)

    @patch.object(hubspot._session, 'post')
    def test_search_exception(self, mock_post):
        mock_post.side_effect = ConnectionError('network down')

        result = hubspot.search_company(domain='acme.com')
        self.assertIsNone(result)

    def test_search_no_params(self):
        result = hubspot.search_company()
        self.assertIsNone(result)

    def test_search_no_api_key(self):
        original = hubspot.MATON_API_KEY
        try:
            hubspot.MATON_API_KEY = ''
            result = hubspot.search_company(domain='acme.com')
            self.assertIsNone(result)
        finally:
            hubspot.MATON_API_KEY = original


# ---------------------------------------------------------------------------
# Tests: create_deal
# ---------------------------------------------------------------------------

class TestCreateDeal(unittest.TestCase):

    @patch.object(hubspot, 'associate_deal_company')
    @patch.object(hubspot._session, 'post')
    def test_create_deal_success(self, mock_post, mock_assoc):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'id': '500'}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        deal_id = hubspot.create_deal('Acme - Seed', company_id='100', owner_id='42')
        self.assertEqual(deal_id, '500')
        mock_assoc.assert_called_once_with('500', '100')

        # Check properties sent
        call_json = mock_post.call_args[1]['json']
        self.assertEqual(call_json['properties']['dealname'], 'Acme - Seed')
        self.assertEqual(call_json['properties']['hubspot_owner_id'], '42')

    @patch.object(hubspot, 'associate_deal_company')
    @patch.object(hubspot._session, 'post')
    def test_create_deal_no_company(self, mock_post, mock_assoc):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'id': '501'}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        deal_id = hubspot.create_deal('Solo Deal')
        self.assertEqual(deal_id, '501')
        mock_assoc.assert_not_called()

    @patch.object(hubspot._session, 'post')
    def test_create_deal_failure(self, mock_post):
        mock_post.side_effect = Exception('API error')

        result = hubspot.create_deal('Bad Deal')
        self.assertIsNone(result)

    def test_create_deal_no_api_key(self):
        original = hubspot.MATON_API_KEY
        try:
            hubspot.MATON_API_KEY = ''
            result = hubspot.create_deal('No Key Deal')
            self.assertIsNone(result)
        finally:
            hubspot.MATON_API_KEY = original

    @patch.object(hubspot, 'associate_deal_company')
    @patch.object(hubspot._session, 'post')
    def test_create_deal_custom_pipeline(self, mock_post, mock_assoc):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'id': '502'}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        hubspot.create_deal('Custom', pipeline_id='my-pipe', stage_id='my-stage')
        call_json = mock_post.call_args[1]['json']
        self.assertEqual(call_json['properties']['pipeline'], 'my-pipe')
        self.assertEqual(call_json['properties']['dealstage'], 'my-stage')


# ---------------------------------------------------------------------------
# Tests: add_note
# ---------------------------------------------------------------------------

class TestAddNote(unittest.TestCase):

    @patch.object(hubspot._session, 'post')
    def test_add_note_to_deal_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        result = hubspot.add_note('500', 'This is a note')
        self.assertTrue(result)

        call_json = mock_post.call_args[1]['json']
        self.assertEqual(call_json['properties']['hs_note_body'], 'This is a note')
        # Default object_type is deals
        assoc = call_json['associations'][0]
        self.assertEqual(assoc['to']['id'], '500')
        self.assertEqual(assoc['types'][0]['associationTypeId'], hubspot.ASSOC_NOTE_TO_DEAL)

    @patch.object(hubspot._session, 'post')
    def test_add_note_to_company(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = hubspot.add_note('100', 'Company note', object_type='companies')
        self.assertTrue(result)

        call_json = mock_post.call_args[1]['json']
        assoc = call_json['associations'][0]
        self.assertEqual(assoc['types'][0]['associationTypeId'], hubspot.ASSOC_NOTE_TO_COMPANY)

    @patch.object(hubspot._session, 'post')
    def test_add_note_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_post.return_value = mock_resp

        result = hubspot.add_note('500', 'Bad note')
        self.assertFalse(result)

    @patch.object(hubspot._session, 'post')
    def test_add_note_exception(self, mock_post):
        mock_post.side_effect = Exception('timeout')

        result = hubspot.add_note('500', 'Timeout note')
        self.assertFalse(result)

    @patch.object(hubspot._session, 'post')
    def test_add_note_url(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        hubspot.add_note('500', 'test')
        call_url = mock_post.call_args[0][0]
        self.assertIn('crm/v3/objects/notes', call_url)


if __name__ == '__main__':
    unittest.main()
