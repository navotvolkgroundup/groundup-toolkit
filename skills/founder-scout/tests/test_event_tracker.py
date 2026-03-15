"""Tests for modules/event_tracker.py — event appearance detection."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.event_tracker import (
    _extract_event_date, _classify_role, _assess_signal_level,
)


# ---------------------------------------------------------------------------
# _extract_event_date()
# ---------------------------------------------------------------------------

def test_extract_iso_date():
    assert _extract_event_date('Event on 2026-03-15') == '2026-03-15'

def test_extract_month_year():
    assert _extract_event_date('Geektime conference March 2026') == '2026-03-01'

def test_extract_no_date():
    assert _extract_event_date('Some text without dates') is None


# ---------------------------------------------------------------------------
# _classify_role()
# ---------------------------------------------------------------------------

def test_classify_speaker():
    role, is_speaker = _classify_role('John Smith was a keynote speaker at the event')
    assert is_speaker is True
    assert 'keynote' in role or 'speaker' in role

def test_classify_panelist():
    role, is_speaker = _classify_role('Joining as panelist for the startup track')
    assert is_speaker is True

def test_classify_judge():
    role, is_speaker = _classify_role('Served as judge in the pitch competition')
    assert is_speaker is True

def test_classify_mentioned():
    role, is_speaker = _classify_role('Attended the conference in Tel Aviv')
    assert is_speaker is False
    assert role == 'mentioned'


# ---------------------------------------------------------------------------
# _assess_signal_level()
# ---------------------------------------------------------------------------

def test_signal_high_new_venture():
    assert _assess_signal_level('Unveiling their new stealth startup at demo day', True) == 'high'
    assert _assess_signal_level('Launch of their new venture', False) == 'high'

def test_signal_medium_speaker():
    assert _assess_signal_level('Speaking at the conference', True) == 'medium'

def test_signal_low_mention():
    assert _assess_signal_level('Attended the networking event', False) == 'low'
