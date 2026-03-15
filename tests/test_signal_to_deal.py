"""Tests for scripts/signal_to_deal.py — signal-to-deal pipeline.

Note: signal_to_deal imports lib.config at module level. We mock it.
"""

import os
import sys
import sqlite3
from unittest.mock import MagicMock

# Mock lib.config before importing signal_to_deal
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
mock_config = MagicMock()
mock_config.maton_api_key = ""
mock_config.hubspot_default_pipeline = "default"
mock_config.hubspot_deal_stage = "123"
mock_config.team_members = []
sys.modules.setdefault('lib.config', MagicMock(config=mock_config))

from scripts.signal_to_deal import get_person_company, get_person


# ---------------------------------------------------------------------------
# get_person_company
# ---------------------------------------------------------------------------

def test_company_from_at_pattern():
    person = {"headline": "CTO at Stealth AI", "last_signal": ""}
    assert get_person_company(person) == "Stealth AI"

def test_company_from_at_sign():
    person = {"headline": "Founder @ DeepTech Labs", "last_signal": ""}
    assert get_person_company(person) == "DeepTech Labs"

def test_company_empty_headline():
    person = {"headline": "", "last_signal": ""}
    assert get_person_company(person) == ""

def test_company_no_at():
    person = {"headline": "Serial Entrepreneur", "last_signal": ""}
    assert get_person_company(person) == ""

def test_company_none_headline():
    person = {"headline": None, "last_signal": None}
    assert get_person_company(person) == ""


# ---------------------------------------------------------------------------
# get_person (with temp DB)
# ---------------------------------------------------------------------------

def test_get_person_found(tmp_path):
    import scripts.signal_to_deal as std
    db_path = str(tmp_path / "test.db")
    old_path = std.SCOUT_DB_PATH
    std.SCOUT_DB_PATH = db_path

    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE tracked_people (
        id INTEGER PRIMARY KEY, name TEXT, linkedin_url TEXT,
        headline TEXT, signal_tier TEXT, last_signal TEXT,
        hubspot_contact_id TEXT, github_url TEXT
    )''')
    conn.execute(
        'INSERT INTO tracked_people VALUES (1, "Alice Smith", "https://linkedin.com/in/alice", '
        '"CTO at TestCo", "high", "Left Google", NULL, NULL)'
    )
    conn.commit()
    conn.close()

    try:
        person = get_person(1)
        assert person is not None
        assert person['name'] == "Alice Smith"
        assert person['headline'] == "CTO at TestCo"
    finally:
        std.SCOUT_DB_PATH = old_path

def test_get_person_not_found(tmp_path):
    import scripts.signal_to_deal as std
    db_path = str(tmp_path / "test.db")
    old_path = std.SCOUT_DB_PATH
    std.SCOUT_DB_PATH = db_path

    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE tracked_people (
        id INTEGER PRIMARY KEY, name TEXT, linkedin_url TEXT,
        headline TEXT, signal_tier TEXT, last_signal TEXT,
        hubspot_contact_id TEXT, github_url TEXT
    )''')
    conn.commit()
    conn.close()

    try:
        person = get_person(999)
        assert person is None
    finally:
        std.SCOUT_DB_PATH = old_path
