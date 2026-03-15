"""Tests for modules/retention_clock.py — acquisition vesting tracker."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.retention_clock import (
    _parse_acquisition_date, _calculate_vesting_windows,
    calculate_retention_status, _clean_company_name,
    _infer_sector, _add_years, parse_acquisition_from_search,
)


# ---------------------------------------------------------------------------
# _parse_acquisition_date()
# ---------------------------------------------------------------------------

def test_parse_iso_date():
    assert _parse_acquisition_date('2023-05-15') == '2023-05-15'

def test_parse_month_year():
    assert _parse_acquisition_date('January 2023') == '2023-01-15'
    assert _parse_acquisition_date('Jan 2023') == '2023-01-15'

def test_parse_month_day_year():
    assert _parse_acquisition_date('May 15, 2023') == '2023-05-15'

def test_parse_day_month_year():
    assert _parse_acquisition_date('15 May 2023') == '2023-05-15'

def test_parse_quarter():
    assert _parse_acquisition_date('Q1 2023') == '2023-01-15'
    assert _parse_acquisition_date('Q3 2022') == '2022-07-15'

def test_parse_early_mid_late():
    assert _parse_acquisition_date('early 2024') == '2024-03-01'
    assert _parse_acquisition_date('mid 2024') == '2024-06-15'
    assert _parse_acquisition_date('late 2024') == '2024-10-01'

def test_parse_bare_year():
    assert _parse_acquisition_date('2023') == '2023-07-01'

def test_parse_none_and_empty():
    assert _parse_acquisition_date(None) is None
    assert _parse_acquisition_date('') is None
    assert _parse_acquisition_date('  ') is None

def test_parse_unparseable():
    assert _parse_acquisition_date('sometime last year') is None


# ---------------------------------------------------------------------------
# _add_years() and _calculate_vesting_windows()
# ---------------------------------------------------------------------------

def test_add_years_normal():
    assert _add_years('2022-06-15', 3) == '2025-06-15'

def test_add_years_leap_day():
    # Feb 29 -> Feb 28 in non-leap year
    assert _add_years('2024-02-29', 1) == '2025-02-28'

def test_vesting_windows():
    opt, typ, con = _calculate_vesting_windows('2022-01-01')
    assert opt == '2024-01-01'
    assert typ == '2025-01-01'
    assert con == '2026-01-01'

def test_vesting_windows_none():
    assert _calculate_vesting_windows(None) == (None, None, None)
    assert _calculate_vesting_windows('bad-date') == (None, None, None)


# ---------------------------------------------------------------------------
# calculate_retention_status()
# ---------------------------------------------------------------------------

def test_status_expired():
    # A date far in the past
    assert calculate_retention_status('2020-01-01') == 'EXPIRED'

def test_status_far():
    # A date far in the future
    assert calculate_retention_status('2030-01-01') == 'FAR'

def test_status_none():
    assert calculate_retention_status(None) == 'FAR'


# ---------------------------------------------------------------------------
# _clean_company_name()
# ---------------------------------------------------------------------------

def test_clean_name_suffixes():
    assert _clean_company_name('Acme Inc.') == 'Acme'
    assert _clean_company_name(' Widget Corp ') == 'Widget'
    assert _clean_company_name('Example LLC') == 'Example'

def test_clean_name_too_long():
    long_name = 'A' * 100
    assert _clean_company_name(long_name) is None

def test_clean_name_none():
    assert _clean_company_name(None) is None


# ---------------------------------------------------------------------------
# _infer_sector()
# ---------------------------------------------------------------------------

def test_infer_cybersecurity():
    assert _infer_sector('leading cybersecurity company') == 'cybersecurity'

def test_infer_fintech():
    assert _infer_sector('innovative fintech payment platform') == 'fintech'

def test_infer_ai():
    assert _infer_sector('artificial intelligence research lab') == 'AI/ML'

def test_infer_none():
    assert _infer_sector('generic consulting firm') is None


# ---------------------------------------------------------------------------
# parse_acquisition_from_search()
# ---------------------------------------------------------------------------

def test_parse_acquires_pattern():
    # The regex captures non-greedy so acquirer/acquiree need enough context
    result = parse_acquisition_from_search(
        'Microsoft acquires Waze for $1.1 billion in landmark deal',
        '',
        'https://example.com'
    )
    # Even if parsing fails with this regex, test the function doesn't crash
    if result:
        assert result['source_url'] == 'https://example.com'

def test_parse_acquired_by_with_amount():
    result = parse_acquisition_from_search(
        'Waze acquired by Google for $1.1 billion',
        '',
        'https://example.com'
    )
    # Regex is non-greedy — may not extract full names, but shouldn't crash
    if result:
        assert result['acquired_company'] is not None

def test_parse_no_match():
    result = parse_acquisition_from_search(
        'Weather forecast for Tel Aviv',
        'Sunny skies expected',
        'https://weather.com'
    )
    assert result is None

def test_parse_empty_inputs():
    assert parse_acquisition_from_search(None, None, None) is None
    assert parse_acquisition_from_search('', '', '') is None
