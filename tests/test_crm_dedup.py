"""Tests for HubSpot company deduplication (scripts/email_to_deal/crm.py).

All HTTP calls are mocked — no real API requests are made.
"""

import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

# Ensure repo root on path
REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, REPO_ROOT)

# Mock lib.config before anything imports it
_fake_config = MagicMock()
_fake_config.maton_api_key = 'test-api-key'
_fake_config.hubspot_api_gateway = 'https://gateway.example.com/hubspot'
_fake_config.hubspot_default_pipeline = 'pipeline-default'
_fake_config.hubspot_deal_stage = 'stage-default'
_fake_config.team_domain = 'groundup.vc'

_fake_lib_config = types.ModuleType('lib.config')
_fake_lib_config.config = _fake_config

if 'lib' in sys.modules and not hasattr(sys.modules['lib'], '__path__'):
    del sys.modules['lib']
sys.modules['lib.config'] = _fake_lib_config

# Stub the email_to_deal.config module with the constants crm.py needs
_fake_etd_config = types.ModuleType('scripts.email_to_deal.config')
_fake_etd_config.MATON_API_KEY = 'test-api-key'
_fake_etd_config.MATON_BASE_URL = 'https://gateway.example.com/hubspot'
_fake_etd_config.OWNER_IDS = {'test@groundup.vc': '1'}
_fake_etd_config.PIPELINE_NAMES = {}
_fake_etd_config.STAGE_NAMES = {}

# Register scripts as a proper package so scripts.email_to_deal.crm can import
_scripts = types.ModuleType('scripts')
_scripts.__path__ = [os.path.join(REPO_ROOT, 'scripts')]
sys.modules['scripts'] = _scripts

_etd = types.ModuleType('scripts.email_to_deal')
_etd.__path__ = [os.path.join(REPO_ROOT, 'scripts', 'email_to_deal')]
sys.modules['scripts.email_to_deal'] = _etd
_scripts.email_to_deal = _etd

sys.modules['scripts.email_to_deal.config'] = _fake_etd_config
_etd.config = _fake_etd_config

from scripts.email_to_deal.crm import (  # noqa: E402
    find_or_create_company, search_hubspot_company,
    _fuzzy_search_company, _search_company_by_domain,
    create_hubspot_company,
)
import scripts.email_to_deal.crm as crm_module  # noqa: E402
_etd.crm = crm_module

BASE = 'https://gateway.example.com/hubspot'


class TestSearchCompanyByDomain(unittest.TestCase):

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_domain_match_found(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [{'id': '100', 'properties': {'name': 'Acme', 'domain': 'acme.com'}}]
        }
        mock_post.return_value = mock_resp

        result = _search_company_by_domain('acme.com')
        self.assertEqual(result, '100')

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_domain_not_found(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'results': []}
        mock_post.return_value = mock_resp

        result = _search_company_by_domain('nonexistent.com')
        self.assertIsNone(result)

    def test_domain_none(self):
        result = _search_company_by_domain(None)
        self.assertIsNone(result)


class TestFuzzySearchCompany(unittest.TestCase):

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_fuzzy_match_high_similarity(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [
                {'id': '200', 'properties': {'name': 'Acme Corporation', 'domain': ''}},
                {'id': '201', 'properties': {'name': 'Beta Inc', 'domain': ''}},
            ]
        }
        mock_post.return_value = mock_resp

        # "Acme Corp" vs "Acme Corporation" should be above 0.85
        result = _fuzzy_search_company('Acme Corporation')
        self.assertEqual(result, '200')

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_fuzzy_match_low_similarity_rejected(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [
                {'id': '300', 'properties': {'name': 'Totally Different Company', 'domain': ''}},
            ]
        }
        mock_post.return_value = mock_resp

        result = _fuzzy_search_company('Acme Corp')
        self.assertIsNone(result)

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_fuzzy_match_exact_name(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [
                {'id': '400', 'properties': {'name': 'Fluent.ai', 'domain': ''}},
            ]
        }
        mock_post.return_value = mock_resp

        result = _fuzzy_search_company('Fluent.ai')
        self.assertEqual(result, '400')

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_fuzzy_no_results(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'results': []}
        mock_post.return_value = mock_resp

        result = _fuzzy_search_company('NoSuchCompany')
        self.assertIsNone(result)

    def test_fuzzy_empty_name(self):
        result = _fuzzy_search_company('')
        self.assertIsNone(result)


class TestFindOrCreateCompany(unittest.TestCase):

    @patch('scripts.email_to_deal.crm._search_company_by_domain')
    @patch('scripts.email_to_deal.crm.search_hubspot_company')
    @patch('scripts.email_to_deal.crm._fuzzy_search_company')
    @patch('scripts.email_to_deal.crm.create_hubspot_company')
    def test_domain_match_returns_early(self, mock_create, mock_fuzzy, mock_exact, mock_domain):
        mock_domain.return_value = '100'

        result = find_or_create_company('Acme', domain='acme.com')
        self.assertEqual(result, '100')
        mock_exact.assert_not_called()
        mock_fuzzy.assert_not_called()
        mock_create.assert_not_called()

    @patch('scripts.email_to_deal.crm._search_company_by_domain')
    @patch('scripts.email_to_deal.crm.search_hubspot_company')
    @patch('scripts.email_to_deal.crm._fuzzy_search_company')
    @patch('scripts.email_to_deal.crm.create_hubspot_company')
    def test_exact_match_returns_early(self, mock_create, mock_fuzzy, mock_exact, mock_domain):
        mock_domain.return_value = None
        mock_exact.return_value = '200'

        result = find_or_create_company('Acme', domain='acme.com')
        self.assertEqual(result, '200')
        mock_fuzzy.assert_not_called()
        mock_create.assert_not_called()

    @patch('scripts.email_to_deal.crm._search_company_by_domain')
    @patch('scripts.email_to_deal.crm.search_hubspot_company')
    @patch('scripts.email_to_deal.crm._fuzzy_search_company')
    @patch('scripts.email_to_deal.crm.create_hubspot_company')
    def test_fuzzy_match_returns_early(self, mock_create, mock_fuzzy, mock_exact, mock_domain):
        mock_domain.return_value = None
        mock_exact.return_value = None
        mock_fuzzy.return_value = '300'

        result = find_or_create_company('Acme Corp')
        self.assertEqual(result, '300')
        mock_create.assert_not_called()

    @patch('scripts.email_to_deal.crm._search_company_by_domain')
    @patch('scripts.email_to_deal.crm.search_hubspot_company')
    @patch('scripts.email_to_deal.crm._fuzzy_search_company')
    @patch('scripts.email_to_deal.crm.create_hubspot_company')
    def test_no_match_creates_new(self, mock_create, mock_fuzzy, mock_exact, mock_domain):
        mock_domain.return_value = None
        mock_exact.return_value = None
        mock_fuzzy.return_value = None
        mock_create.return_value = '400'

        result = find_or_create_company('BrandNewCo', description='Test company')
        self.assertEqual(result, '400')
        mock_create.assert_called_once_with({'name': 'BrandNewCo', 'description': 'Test company'})

    @patch('scripts.email_to_deal.crm._search_company_by_domain')
    @patch('scripts.email_to_deal.crm.search_hubspot_company')
    @patch('scripts.email_to_deal.crm._fuzzy_search_company')
    @patch('scripts.email_to_deal.crm.create_hubspot_company')
    def test_no_domain_skips_domain_search(self, mock_create, mock_fuzzy, mock_exact, mock_domain):
        mock_exact.return_value = '500'

        result = find_or_create_company('Acme')
        self.assertEqual(result, '500')
        mock_domain.assert_not_called()

    @patch('scripts.email_to_deal.crm._search_company_by_domain')
    @patch('scripts.email_to_deal.crm.search_hubspot_company')
    @patch('scripts.email_to_deal.crm._fuzzy_search_company')
    @patch('scripts.email_to_deal.crm.create_hubspot_company')
    def test_create_failure_returns_none(self, mock_create, mock_fuzzy, mock_exact, mock_domain):
        mock_domain.return_value = None
        mock_exact.return_value = None
        mock_fuzzy.return_value = None
        mock_create.return_value = None

        result = find_or_create_company('FailCo')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
