"""Tests for modules/advisor_tracker.py — advisory role accumulation detection."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.advisor_tracker import (
    extract_advisory_roles, detect_advisory_accumulation,
    extract_verticals, _parse_title_company,
)


# ---------------------------------------------------------------------------
# extract_advisory_roles()
# ---------------------------------------------------------------------------

def test_extract_static_text_roles():
    profile = '''## Experience
StaticText "Board Advisor"
StaticText "CyberTech Ltd"
StaticText "Jan 2024 - Present"
StaticText "Angel Investor"
StaticText "AI Startup Inc"
'''
    roles = extract_advisory_roles(profile)
    assert len(roles) >= 2
    assert any(r['title'] == 'Board Advisor' for r in roles)
    assert any(r['title'] == 'Angel Investor' for r in roles)

def test_extract_at_pattern():
    profile = 'StaticText "Advisor at Acme Corp"'
    roles = extract_advisory_roles(profile)
    assert len(roles) == 1
    assert roles[0]['company'] == 'Acme Corp'

def test_extract_empty():
    assert extract_advisory_roles('') == []
    assert extract_advisory_roles(None) == []

def test_extract_no_advisory():
    profile = '''StaticText "Software Engineer"
StaticText "Google"
StaticText "2020 - Present"'''
    roles = extract_advisory_roles(profile)
    assert len(roles) == 0


# ---------------------------------------------------------------------------
# detect_advisory_accumulation()
# ---------------------------------------------------------------------------

def test_accumulation_high_left_role():
    roles = [
        {'title': 'Advisor', 'company': 'A', 'is_advisory': True},
        {'title': 'Angel', 'company': 'B', 'is_advisory': True},
        {'title': 'Mentor', 'company': 'C', 'is_advisory': True},
    ]
    result = detect_advisory_accumulation(roles, 0, employment_status='left_role')
    assert result is not None
    assert result['tier'] == 'high'
    assert result['advisory_count'] == 3

def test_accumulation_medium_employed():
    roles = [
        {'title': 'Advisor', 'company': 'A', 'is_advisory': True},
        {'title': 'Angel', 'company': 'B', 'is_advisory': True},
    ]
    result = detect_advisory_accumulation(roles, 0, employment_status='employed')
    assert result is not None
    assert result['tier'] == 'medium'

def test_accumulation_no_change():
    roles = [{'title': 'Advisor', 'company': 'A', 'is_advisory': True}]
    result = detect_advisory_accumulation(roles, 1)
    assert result is None  # No new roles

def test_accumulation_empty():
    assert detect_advisory_accumulation([], 0) is None
    assert detect_advisory_accumulation(None, 0) is None


# ---------------------------------------------------------------------------
# extract_verticals()
# ---------------------------------------------------------------------------

def test_verticals_cybersecurity():
    roles = [
        {'title': 'Advisor', 'company': 'CyberDefense Inc'},
        {'title': 'Angel', 'company': 'SecurityFirst AI'},
    ]
    verticals = extract_verticals(roles)
    assert 'cybersecurity' in verticals

def test_verticals_multiple():
    roles = [
        {'title': 'Advisor', 'company': 'FinTech Payments'},
        {'title': 'Angel', 'company': 'AI Solutions'},
        {'title': 'Mentor', 'company': 'Cloud Platform'},
    ]
    verticals = extract_verticals(roles)
    assert len(verticals) >= 1

def test_verticals_empty():
    assert extract_verticals([]) == []
    assert extract_verticals(None) == []
