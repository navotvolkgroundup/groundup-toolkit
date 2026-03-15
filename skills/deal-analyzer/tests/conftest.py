"""Shared fixtures for deal-analyzer tests.

Sets up sys.path and provides a mock config so module imports don't crash.
"""

import sys
import os
import types
import pytest

# Add repo root so `lib` package is importable
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, repo_root)

# Add deal-analyzer dir so `modules` is importable
skill_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, skill_dir)

# Provide a minimal stub for lib.config before anything imports it
# This prevents the FileNotFoundError when config.yaml is missing locally
if 'lib.config' not in sys.modules:
    _config_mod = types.ModuleType('lib.config')

    class _StubConfig:
        def __getattr__(self, name):
            return None
        def get(self, *args, **kwargs):
            return args[1] if len(args) > 1 else None
        def get_member_by_phone(self, *a):
            return None

    _config_mod.config = _StubConfig()
    sys.modules['lib.config'] = _config_mod

# Stub lib.brave
if 'lib.brave' not in sys.modules:
    _brave_mod = types.ModuleType('lib.brave')
    _brave_mod.brave_search = lambda *a, **k: []
    sys.modules['lib.brave'] = _brave_mod

# Stub lib.whatsapp
if 'lib.whatsapp' not in sys.modules:
    _wa_mod = types.ModuleType('lib.whatsapp')
    _wa_mod.send_whatsapp = lambda *a, **k: None
    sys.modules['lib.whatsapp'] = _wa_mod

# Stub lib.email
if 'lib.email' not in sys.modules:
    _email_mod = types.ModuleType('lib.email')
    _email_mod.send_email = lambda *a, **k: None
    sys.modules['lib.email'] = _email_mod

# Stub lib.gws
if 'lib.gws' not in sys.modules:
    _gws_mod = types.ModuleType('lib.gws')
    _gws_mod.get_google_access_token = lambda: None
    sys.modules['lib.gws'] = _gws_mod


@pytest.fixture
def sample_deck_data():
    """A typical deck data dict as returned by extract_deck_data."""
    return {
        'company_name': 'Acme AI',
        'product_overview': 'AI-powered document analysis platform',
        'problem_solution': 'Manual document review is slow and error-prone',
        'key_capabilities': 'NLP extraction, classification, summarization',
        'team_background': 'Ex-Google ML engineers with 15+ years experience',
        'gtm_strategy': 'Enterprise SaaS, targeting legal and finance teams',
        'traction': '$1.2M ARR, 30 customers, 3x YoY growth',
        'fundraising': 'Raising $5M Series A at $25M pre-money',
        'industry': 'AI/ML',
        'competitors_mentioned': ['DocuSign', 'Kofax', 'ABBYY'],
        'founder_names': ['Alice Chen', 'Bob Smith'],
        'location': 'Tel Aviv, Israel',
        'business_model': 'SaaS subscription',
        'target_customers': 'Enterprise legal and financial services',
    }


@pytest.fixture
def sparse_deck_data():
    """Minimal deck data with most fields null."""
    return {
        'company_name': 'Stealth Co',
        'product_overview': None,
        'problem_solution': None,
        'key_capabilities': None,
        'team_background': None,
        'gtm_strategy': None,
        'traction': None,
        'fundraising': None,
        'industry': None,
        'competitors_mentioned': [],
        'founder_names': [],
        'location': None,
        'business_model': None,
        'target_customers': None,
    }


@pytest.fixture
def sample_section_results():
    """Sample section_results dict for report formatting."""
    return {
        'tldr': 'Strong team, early traction, competitive market. Worth a meeting.',
        'investment_memo': '## Investment Recommendation\n\n**Proceed to partner meeting.** Strong founders with relevant domain expertise.',
        'market_opportunity': '## Market Opportunity\n\nLarge TAM of $50B.',
        'competitive_landscape': '## Competitive Landscape\n\nCrowded but differentiated.',
    }
