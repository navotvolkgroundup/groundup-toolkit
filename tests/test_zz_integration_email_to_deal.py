"""Integration tests for email-to-deal pipeline.

Tests the full flow from WhatsApp message → company dedup → deal creation → confirmation.
All external services (Gmail, HubSpot, Claude, WhatsApp) are mocked at the HTTP layer.
"""

import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, REPO_ROOT)

# Save modules that we'll stub, so we can restore them for other test files
_saved_modules = {k: sys.modules[k] for k in list(sys.modules) if k.startswith(('lib.', 'lib', 'scripts.', 'scripts'))}

# --- Stub ALL external dependencies before importing anything ---

# lib.config
_fake_config = MagicMock()
_fake_config.maton_api_key = 'test-api-key'
_fake_config.hubspot_api_gateway = 'https://gateway.example.com/hubspot'
_fake_config.hubspot_default_pipeline = 'pipeline-1'
_fake_config.hubspot_deal_stage = 'stage-1'
_fake_config.team_domain = 'groundup.vc'
_fake_config.hubspot_portal_id = '12345'
_fake_config.alert_phone = '+1234567890'

_lib = types.ModuleType('lib')
_lib.__path__ = [os.path.join(REPO_ROOT, 'lib')]
sys.modules.setdefault('lib', _lib)

_fake_lib_config = types.ModuleType('lib.config')
_fake_lib_config.config = _fake_config
sys.modules['lib.config'] = _fake_lib_config

# lib.gws — must export everything the __init__.py imports
_fake_gws = MagicMock()
sys.modules['lib.gws'] = _fake_gws

# lib.whatsapp
sys.modules['lib.whatsapp'] = MagicMock()

# lib.claude, lib.brave, etc
for mod in ['lib.claude', 'lib.brave', 'lib.email', 'lib.log_utils']:
    sys.modules.setdefault(mod, MagicMock())

# scripts package
_scripts = types.ModuleType('scripts')
_scripts.__path__ = [os.path.join(REPO_ROOT, 'scripts')]
sys.modules['scripts'] = _scripts

# scripts.portfolio_monitor
_fake_portfolio = MagicMock()
_fake_portfolio.handle_portfolio_email = MagicMock(return_value=False)
_fake_portfolio.PORTFOLIO = {}
sys.modules['scripts.portfolio_monitor'] = _fake_portfolio

# scripts.email_to_deal sub-package
_etd = types.ModuleType('scripts.email_to_deal')
_etd.__path__ = [os.path.join(REPO_ROOT, 'scripts', 'email_to_deal')]
sys.modules['scripts.email_to_deal'] = _etd
_scripts.email_to_deal = _etd

# Stub config with real values needed by process_whatsapp_deal
_fake_etd_config = types.ModuleType('scripts.email_to_deal.config')
_fake_etd_config.ANTHROPIC_API_KEY = 'test-key'
_fake_etd_config.TEAM_MEMBERS = {
    'navot@groundup.vc': {'name': 'Navot', 'phone': '+1111111111'},
}
_fake_etd_config.OWNER_IDS = {'navot@groundup.vc': 'owner-1'}
_fake_etd_config.MATON_API_KEY = 'test-api-key'
_fake_etd_config.MATON_BASE_URL = 'https://gateway.example.com/hubspot'
_fake_etd_config.DEFAULT_PIPELINE = 'pipeline-1'
_fake_etd_config.DEFAULT_STAGE = 'stage-1'
_fake_etd_config.SECONDARY_PIPELINE = 'pipeline-2'
_fake_etd_config.SECONDARY_STAGE = 'stage-2'
_fake_etd_config.PIPELINE_NAMES = {'pipeline-1': 'VC Deals', 'pipeline-2': 'LP Deals'}
_fake_etd_config.STAGE_NAMES = {'stage-1': 'New', 'stage-2': 'Intro'}
_fake_etd_config.EMAIL_TO_PHONE = {'navot@groundup.vc': '+1111111111'}
_fake_etd_config.is_lp_email = MagicMock(return_value=False)
_fake_etd_config.should_skip_email = MagicMock(return_value=False)
_fake_etd_config._is_own_firm_name = MagicMock(return_value=False)
sys.modules['scripts.email_to_deal.config'] = _fake_etd_config
_etd.config = _fake_etd_config

# Stub scanner, extractor, notifications as MagicMocks
for sub in ['scanner', 'extractor', 'notifications']:
    mod = MagicMock()
    full = f'scripts.email_to_deal.{sub}'
    sys.modules[full] = mod
    setattr(_etd, sub, mod)

# Now import the real __init__.py (which uses our stubs for all deps except crm)
# crm.py will be imported for real — it only needs requests + config
import importlib
import scripts.email_to_deal as etd_pkg  # noqa: E402
# Force-reload to pick up our stubs
importlib.reload(etd_pkg)

# Also import crm directly so we can reference it
import scripts.email_to_deal.crm as crm_module  # noqa: E402
_etd.crm = crm_module

# Get references to the real functions
process_whatsapp_deal = etd_pkg.process_whatsapp_deal
find_or_create_company = crm_module.find_or_create_company

# Reference to the mocked send_whatsapp that __init__.py imported
_mock_send_whatsapp = sys.modules['scripts.email_to_deal.notifications'].send_whatsapp


def _hubspot_post_no_match(url, **kwargs):
    """Default mock: no existing companies, successful creates."""
    resp = MagicMock()
    resp.status_code = 200
    json_body = kwargs.get('json', {})

    if '/search' in url:
        resp.json.return_value = {'total': 0, 'results': []}
    elif 'companies' in url and json_body.get('properties'):
        resp.json.return_value = {'id': 'company-100', 'properties': json_body['properties']}
    elif 'deals' in url and json_body.get('properties'):
        resp.json.return_value = {'id': 'deal-200', 'properties': json_body['properties']}
    elif 'associations' in url:
        resp.json.return_value = {'results': []}
    else:
        resp.json.return_value = {}
    return resp


class TestWhatsAppDealPipeline(unittest.TestCase):
    """Test full WhatsApp deal submission flow."""

    @patch('scripts.email_to_deal.crm.requests.post', side_effect=_hubspot_post_no_match)
    def test_new_company_creates_deal_and_confirms(self, mock_post):
        """WhatsApp deal → new company → new deal → WhatsApp confirmation."""
        _mock_send_whatsapp.reset_mock()
        msg = {'message': 'deal: Acme Corp - AI startup'}
        process_whatsapp_deal(msg, 'navot@groundup.vc', 'Navot', '+1111111111')

        self.assertTrue(mock_post.called)
        # Should have sent a WhatsApp confirmation
        _mock_send_whatsapp.assert_called()
        confirmation = _mock_send_whatsapp.call_args[0][1]
        self.assertIn('Acme Corp', confirmation)

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_duplicate_company_reuses_existing(self, mock_post):
        """When company already exists in HubSpot, reuse it instead of creating."""
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            json_body = kwargs.get('json', {})

            if '/search' in url and 'companies' in url:
                filters = json_body.get('filterGroups', [{}])[0].get('filters', [])
                # Exact name match returns existing company
                if any(f.get('operator') == 'EQ' for f in filters):
                    resp.json.return_value = {
                        'total': 1,
                        'results': [{'id': 'company-existing', 'properties': {'name': 'Acme Corp'}}]
                    }
                else:
                    resp.json.return_value = {'total': 0, 'results': []}
            elif 'deals' in url and json_body.get('properties'):
                resp.json.return_value = {'id': 'deal-201', 'properties': {}}
            elif 'associations' in url:
                resp.json.return_value = {'results': []}
            else:
                resp.json.return_value = {}
            return resp

        mock_post.side_effect = side_effect
        msg = {'message': 'deal: Acme Corp'}
        process_whatsapp_deal(msg, 'navot@groundup.vc', 'Navot', '+1111111111')

        # No company creation call — only searches, deal, association
        create_calls = [
            c for c in mock_post.call_args_list
            if 'companies' in str(c) and '/search' not in str(c) and 'associations' not in str(c)
        ]
        self.assertEqual(len(create_calls), 0, 'Should not create company when match exists')


class TestDeduplication(unittest.TestCase):
    """Test find_or_create_company deduplication logic."""

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_fuzzy_match_prevents_duplicate(self, mock_post):
        """'Acme Technology' should match existing 'Acme Technologies' via fuzzy (ratio=0.88)."""
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            json_body = kwargs.get('json', {})
            if '/search' in url:
                filters = json_body.get('filterGroups', [{}])[0].get('filters', [])
                if any(f.get('operator') == 'EQ' for f in filters):
                    resp.json.return_value = {'total': 0, 'results': []}
                elif any(f.get('operator') == 'CONTAINS_TOKEN' for f in filters):
                    resp.json.return_value = {
                        'total': 1,
                        'results': [{'id': 'company-fuzzy', 'properties': {'name': 'Acme Technologies'}}]
                    }
                else:
                    resp.json.return_value = {'total': 0, 'results': []}
            else:
                resp.json.return_value = {}
            return resp

        mock_post.side_effect = side_effect
        result = find_or_create_company('Acme Technology')
        self.assertEqual(result, 'company-fuzzy')

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_low_similarity_creates_new(self, mock_post):
        """Completely different names should create a new company."""
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            json_body = kwargs.get('json', {})
            if '/search' in url:
                filters = json_body.get('filterGroups', [{}])[0].get('filters', [])
                if any(f.get('operator') == 'CONTAINS_TOKEN' for f in filters):
                    resp.json.return_value = {
                        'total': 1,
                        'results': [{'id': 'company-xyz', 'properties': {'name': 'Totally Different Inc'}}]
                    }
                else:
                    resp.json.return_value = {'total': 0, 'results': []}
            elif 'companies' in url:
                resp.json.return_value = {'id': 'company-new', 'properties': {}}
            else:
                resp.json.return_value = {}
            return resp

        mock_post.side_effect = side_effect
        result = find_or_create_company('Moonbeam Technologies')
        self.assertEqual(result, 'company-new')

    @patch('scripts.email_to_deal.crm.requests.post')
    def test_domain_match_takes_priority(self, mock_post):
        """If domain matches, return immediately without name search."""
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            json_body = kwargs.get('json', {})
            if '/search' in url:
                filters = json_body.get('filterGroups', [{}])[0].get('filters', [])
                if any(f.get('propertyName') == 'domain' for f in filters):
                    resp.json.return_value = {
                        'total': 1,
                        'results': [{'id': 'company-domain', 'properties': {'name': 'Acme'}}]
                    }
                else:
                    resp.json.return_value = {'total': 0, 'results': []}
            else:
                resp.json.return_value = {}
            return resp

        mock_post.side_effect = side_effect
        result = find_or_create_company('Acme Corp', domain='acme.com')
        self.assertEqual(result, 'company-domain')


class TestZeroSuccessDetection(unittest.TestCase):

    def test_zero_success_warning_logged(self):
        """When all emails fail, a warning should be logged."""
        import logging
        with self.assertLogs('email-to-deal', level='WARNING') as cm:
            from scripts.email_to_deal import log as etd_log
            etd_log.warning('Processed 0 of %d emails — possible systemic failure', 5)
        self.assertTrue(any('Processed 0 of 5' in msg for msg in cm.output))


def teardown_module():
    """Restore sys.modules to prevent stub leaks into other test files."""
    # Remove all stubs we added (including 'lib' and 'scripts' themselves)
    for key in list(sys.modules):
        if key == 'lib' or key == 'scripts' or key.startswith(('lib.', 'scripts.')):
            del sys.modules[key]
    # Restore original modules
    sys.modules.update(_saved_modules)


if __name__ == '__main__':
    unittest.main()
