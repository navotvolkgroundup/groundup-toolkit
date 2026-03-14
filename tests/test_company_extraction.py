"""Tests for email-to-deal company extraction logic.

Tests extract_company_info(), _extract_company_from_email_domains(),
_is_bad_company_name(), and _is_own_firm_name() from the email-to-deal
automation script.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# The script lives at scripts/email-to-deal-automation.py (with hyphens).
# We can't import it normally, so we mock heavy dependencies and use importlib.
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import importlib


def _import_module():
    """Import the email-to-deal-automation module with mocked dependencies."""
    # Build a fake config object that satisfies all module-level references
    fake_config = MagicMock()
    fake_config.anthropic_api_key = 'fake-key'
    fake_config.maton_api_key = 'fake-maton-key'
    fake_config.hubspot_api_gateway = 'https://fake-gateway'
    fake_config.hubspot_default_pipeline = 'default'
    fake_config.hubspot_deal_stage = 'stage1'
    fake_config.hubspot_pipelines = [
        {'id': 'p1', 'name': 'Pipeline 1', 'stage_names': {}, 'default_stage': 's1'},
        {'id': 'p2', 'name': 'Pipeline 2', 'stage_names': {}, 'default_stage': 's2'},
    ]
    fake_config.team_members = [
        {'email': 'alice@groundup.vc', 'name': 'Alice Test', 'hubspot_owner_id': '123'}
    ]
    fake_config.team_domain = 'groundup.vc'
    fake_config.team_phones = {}
    fake_config.whatsapp_account = 'fake'

    # Pre-populate sys.modules to prevent real imports
    fake_lib_config = MagicMock()
    fake_lib_config.config = fake_config
    sys.modules.setdefault('lib', MagicMock())
    sys.modules['lib.config'] = fake_lib_config
    sys.modules['lib.gws'] = MagicMock()
    sys.modules['lib.safe_url'] = MagicMock()
    sys.modules['scripts'] = MagicMock()
    sys.modules['scripts.portfolio_monitor'] = MagicMock()
    sys.modules['scripts.portfolio_monitor'].PORTFOLIO = {}

    # Import via importlib since the filename has hyphens
    spec = importlib.util.spec_from_file_location(
        'email_to_deal_automation',
        os.path.join(SCRIPTS_DIR, 'email-to-deal-automation.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _import_module()
extract_company_info = _mod.extract_company_info
_extract_company_from_email_domains = _mod._extract_company_from_email_domains
_is_bad_company_name = _mod._is_bad_company_name
_is_own_firm_name = _mod._is_own_firm_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_thread(subject):
    """Build a minimal thread dict for extract_company_info."""
    return {'subject': subject}


# ---------------------------------------------------------------------------
# Tests: Fwd/Re prefix stripping
# ---------------------------------------------------------------------------

class TestPrefixStripping(unittest.TestCase):
    """Verify that Fwd:/Re:/Fw: prefixes are fully stripped."""

    def test_single_re(self):
        result = extract_company_info(_make_thread('Re: Acme Corp deck'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_single_fwd(self):
        result = extract_company_info(_make_thread('Fwd: Acme Corp deck'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_single_fw(self):
        result = extract_company_info(_make_thread('Fw: Acme Corp deck'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_nested_re_fwd(self):
        result = extract_company_info(_make_thread('Re: Fwd: Acme Corp deck'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_nested_fwd_re_fwd(self):
        result = extract_company_info(_make_thread('Fwd: Re: Fwd: Acme Corp pitch'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_mixed_case_prefixes(self):
        result = extract_company_info(_make_thread('RE: FWD: Acme Corp deck'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_lowercase_prefixes(self):
        result = extract_company_info(_make_thread('re: fwd: Acme Corp presentation'))
        self.assertEqual(result['name'], 'Acme Corp')


# ---------------------------------------------------------------------------
# Tests: Company name extraction from clean subjects
# ---------------------------------------------------------------------------

class TestCompanyNameExtraction(unittest.TestCase):
    """Test company name extraction from various subject formats."""

    def test_deck_keyword(self):
        result = extract_company_info(_make_thread('Acme Corp deck'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_pitch_keyword(self):
        result = extract_company_info(_make_thread('WidgetCo pitch'))
        self.assertEqual(result['name'], 'WidgetCo')

    def test_presentation_keyword(self):
        result = extract_company_info(_make_thread('FooBar presentation'))
        self.assertEqual(result['name'], 'FooBar')

    def test_preso_keyword(self):
        result = extract_company_info(_make_thread('DataStream preso'))
        self.assertEqual(result['name'], 'DataStream')

    def test_plain_subject_no_keyword(self):
        """Without a deck/pitch keyword the whole cleaned subject becomes the name."""
        result = extract_company_info(_make_thread('Acme Corp'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_meeting_request_suffix_stripped(self):
        result = extract_company_info(_make_thread('Acme Corp - meeting request'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_intro_to_prefix_stripped(self):
        result = extract_company_info(_make_thread('Intro to Acme Corp'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_introduction_to_prefix_stripped(self):
        result = extract_company_info(_make_thread('Introduction to Acme Corp'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_connect_with_prefix_stripped(self):
        result = extract_company_info(_make_thread('Connect with Acme Corp'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_description_includes_original_subject(self):
        result = extract_company_info(_make_thread('Re: Fwd: Acme Corp deck'))
        self.assertIn('Re: Fwd: Acme Corp deck', result['description'])

    def test_own_firm_name_rejected(self):
        """Our own firm name should not become a deal name."""
        result = extract_company_info(_make_thread('GroundUp Ventures'))
        self.assertEqual(result['name'], '')

    def test_x_pattern_picks_non_firm_side(self):
        """'Firm x Startup' pattern should pick the non-firm side."""
        result = extract_company_info(_make_thread('GroundUp x Acme Corp'))
        self.assertEqual(result['name'], 'Acme Corp')

    def test_intro_pattern_picks_non_firm_side(self):
        result = extract_company_info(_make_thread('GroundUp intro Acme Corp'))
        self.assertEqual(result['name'], 'Acme Corp')


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Edge-case handling for extract_company_info."""

    def test_empty_subject(self):
        result = extract_company_info(_make_thread(''))
        self.assertEqual(result['name'], '')

    def test_subject_only_prefixes(self):
        """A subject like 'Re: Fwd: ' with nothing after should produce empty name."""
        result = extract_company_info(_make_thread('Re: Fwd: '))
        self.assertEqual(result['name'], '')

    def test_missing_subject_key(self):
        result = extract_company_info({})
        self.assertEqual(result['name'], '')

    def test_lp_mention_stripped(self):
        result = extract_company_info(_make_thread('Acme LP deck'))
        self.assertEqual(result['name'], 'Acme')

    def test_limited_partner_stripped(self):
        result = extract_company_info(_make_thread('Acme Limited Partner deck'))
        self.assertEqual(result['name'], 'Acme')


# ---------------------------------------------------------------------------
# Tests: _is_bad_company_name
# ---------------------------------------------------------------------------

class TestIsBadCompanyName(unittest.TestCase):

    def test_none(self):
        self.assertTrue(_is_bad_company_name(None))

    def test_empty(self):
        self.assertTrue(_is_bad_company_name(''))

    def test_too_short(self):
        self.assertTrue(_is_bad_company_name('AB'))

    def test_question_mark(self):
        self.assertTrue(_is_bad_company_name('Intro call?'))

    def test_starts_with_intro(self):
        self.assertTrue(_is_bad_company_name('Intro to something'))

    def test_starts_with_meeting(self):
        self.assertTrue(_is_bad_company_name('Meeting about X'))

    def test_good_name(self):
        self.assertFalse(_is_bad_company_name('Acme Corp'))

    def test_good_name_three_chars(self):
        self.assertFalse(_is_bad_company_name('Xyz'))


# ---------------------------------------------------------------------------
# Tests: _extract_company_from_email_domains
# ---------------------------------------------------------------------------

class TestExtractCompanyFromDomains(unittest.TestCase):

    def test_external_domain_extracted(self):
        thread_data = {
            'messages': [{
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': 'founder@acmecorp.com'}
                    ]
                }
            }]
        }
        result = _extract_company_from_email_domains(thread_data)
        self.assertEqual(result, 'Acmecorp')

    def test_team_domain_skipped(self):
        thread_data = {
            'messages': [{
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': 'alice@groundup.vc'}
                    ]
                }
            }]
        }
        result = _extract_company_from_email_domains(thread_data)
        self.assertIsNone(result)

    def test_common_domains_skipped(self):
        thread_data = {
            'messages': [{
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': 'someone@gmail.com'}
                    ]
                }
            }]
        }
        result = _extract_company_from_email_domains(thread_data)
        self.assertIsNone(result)

    def test_empty_messages(self):
        result = _extract_company_from_email_domains({'messages': []})
        self.assertIsNone(result)

    def test_no_messages_key(self):
        result = _extract_company_from_email_domains({})
        self.assertIsNone(result)

    def test_short_domain_skipped(self):
        """Domain names shorter than 2 chars should be skipped."""
        thread_data = {
            'messages': [{
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': 'user@x.com'}
                    ]
                }
            }]
        }
        result = _extract_company_from_email_domains(thread_data)
        self.assertIsNone(result)

    def test_cc_header_used(self):
        thread_data = {
            'messages': [{
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': 'alice@groundup.vc'},
                        {'name': 'Cc', 'value': 'partner@bigfund.io'}
                    ]
                }
            }]
        }
        result = _extract_company_from_email_domains(thread_data)
        self.assertEqual(result, 'Bigfund')


# ---------------------------------------------------------------------------
# Tests: _is_own_firm_name
# ---------------------------------------------------------------------------

class TestIsOwnFirmName(unittest.TestCase):

    def test_exact_domain_base(self):
        self.assertTrue(_is_own_firm_name('groundup'))

    def test_with_suffix(self):
        self.assertTrue(_is_own_firm_name('GroundUp Ventures'))

    def test_with_vc_suffix(self):
        self.assertTrue(_is_own_firm_name('GroundUpVC'))

    def test_unrelated_name(self):
        self.assertFalse(_is_own_firm_name('Acme Corp'))


if __name__ == '__main__':
    unittest.main()
