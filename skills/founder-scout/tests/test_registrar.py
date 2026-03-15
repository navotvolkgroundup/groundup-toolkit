"""Tests for modules/registrar.py — Israeli Companies Registrar monitor."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.registrar import (
    _parse_date_flexible, _normalize_record, _extract_date,
    match_against_watchlist, is_tech_company,
)


# ---------------------------------------------------------------------------
# _parse_date_flexible()
# ---------------------------------------------------------------------------

def test_parse_iso_date():
    assert _parse_date_flexible('2024-03-15') == '2024-03-15'

def test_parse_iso_with_time():
    assert _parse_date_flexible('2024-03-15T10:30:00') == '2024-03-15'

def test_parse_dd_mm_yyyy_slash():
    assert _parse_date_flexible('15/03/2024') == '2024-03-15'

def test_parse_dd_mm_yyyy_dot():
    assert _parse_date_flexible('15.03.2024') == '2024-03-15'

def test_parse_dd_mm_yyyy_dash():
    assert _parse_date_flexible('15-03-2024') == '2024-03-15'

def test_parse_empty():
    assert _parse_date_flexible(None) is None
    assert _parse_date_flexible('') is None
    assert _parse_date_flexible('  ') is None


# ---------------------------------------------------------------------------
# _extract_date()
# ---------------------------------------------------------------------------

def test_extract_date_hebrew_field():
    record = {'תאריך_התאגדות': '2024-01-20'}
    assert _extract_date(record) == '2024-01-20'

def test_extract_date_english_field():
    record = {'registration_date': '15/06/2024'}
    assert _extract_date(record) == '2024-06-15'

def test_extract_date_missing():
    assert _extract_date({'other_field': 'value'}) is None


# ---------------------------------------------------------------------------
# _normalize_record()
# ---------------------------------------------------------------------------

def test_normalize_hebrew_fields():
    record = {
        'שם_חברה': 'חברה לדוגמה',
        'מספר_חברה': '515000123',
        'תאריך_התאגדות': '2024-03-01',
        'מטרת_החברה': 'פיתוח תוכנה',
    }
    result = _normalize_record(record)
    assert result['company_name'] == 'חברה לדוגמה'
    assert result['registration_number'] == '515000123'
    assert result['registration_date'] == '2024-03-01'
    assert result['stated_purpose'] == 'פיתוח תוכנה'

def test_normalize_english_fields():
    record = {
        'company_name': 'Example Ltd',
        'company_number': '515000456',
        'registration_date': '2024-06-15',
        'stated_purpose': 'Software development',
        'directors': '["John Doe", "Jane Smith"]',
    }
    result = _normalize_record(record)
    assert result['company_name'] == 'Example Ltd'
    assert result['directors'] == ['John Doe', 'Jane Smith']


# ---------------------------------------------------------------------------
# match_against_watchlist()
# ---------------------------------------------------------------------------

def test_match_exact():
    reg = {'directors': ['Yosef Cohen']}
    assert match_against_watchlist(reg, ['Yosef Cohen']) == 'Yosef Cohen'

def test_match_reordered():
    reg = {'directors': ['Cohen Yosef']}
    assert match_against_watchlist(reg, ['Yosef Cohen']) == 'Yosef Cohen'

def test_match_case_insensitive():
    reg = {'directors': ['YOSEF COHEN']}
    assert match_against_watchlist(reg, ['yosef cohen']) == 'yosef cohen'

def test_no_match():
    reg = {'directors': ['David Levi']}
    assert match_against_watchlist(reg, ['Yosef Cohen']) is None

def test_match_empty_directors():
    reg = {'directors': []}
    assert match_against_watchlist(reg, ['Yosef Cohen']) is None

def test_match_no_watchlist():
    reg = {'directors': ['Yosef Cohen']}
    assert match_against_watchlist(reg, []) is None


# ---------------------------------------------------------------------------
# is_tech_company()
# ---------------------------------------------------------------------------

def test_tech_english():
    assert is_tech_company('Development of AI software platform') is True
    assert is_tech_company('Cloud computing solutions') is True

def test_tech_hebrew():
    assert is_tech_company('פיתוח תוכנה וטכנולוגיה') is True
    assert is_tech_company('סייבר') is True

def test_not_tech():
    assert is_tech_company('Real estate investment') is False
    assert is_tech_company('Restaurant and catering services') is False

def test_tech_none():
    assert is_tech_company(None) is False
    assert is_tech_company('') is False
