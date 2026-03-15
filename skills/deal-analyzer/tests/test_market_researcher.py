"""Tests for modules/market_researcher.py — research query building."""

from modules.market_researcher import build_research_queries, format_research_for_section


# ---------------------------------------------------------------------------
# build_research_queries()
# ---------------------------------------------------------------------------

def test_queries_full_data(sample_deck_data):
    queries = build_research_queries(sample_deck_data)
    assert 'market_size' in queries
    assert 'competitors' in queries
    assert 'founder_linkedin' in queries
    assert 'company_linkedin' in queries
    assert 'comparable_exits' in queries

def test_queries_saas_unit_economics(sample_deck_data):
    queries = build_research_queries(sample_deck_data)
    assert 'unit_economics' in queries
    assert 'SaaS' in queries['unit_economics']

def test_queries_non_saas():
    data = {
        'company_name': 'Test',
        'industry': 'healthtech',
        'business_model': 'marketplace',
        'founder_names': [],
    }
    queries = build_research_queries(data)
    assert 'unit_economics' in queries
    assert 'SaaS' not in queries['unit_economics']

def test_queries_no_industry():
    data = {'company_name': 'Test', 'industry': None, 'founder_names': ['John Doe']}
    queries = build_research_queries(data)
    assert 'market_size' not in queries
    assert 'founder_linkedin' in queries

def test_queries_no_founders():
    data = {'company_name': 'Test', 'industry': 'fintech', 'founder_names': []}
    queries = build_research_queries(data)
    assert 'founder_linkedin' not in queries
    assert 'market_size' in queries

def test_queries_multiple_founders():
    data = {
        'company_name': 'Test',
        'industry': 'AI',
        'founder_names': ['Alice', 'Bob', 'Charlie', 'Dave'],
    }
    queries = build_research_queries(data)
    assert 'founder_linkedin' in queries
    assert 'founder_linkedin_2' in queries
    assert 'founder_linkedin_3' in queries
    assert 'founder_linkedin_4' not in queries

def test_queries_empty_data():
    queries = build_research_queries({})
    assert isinstance(queries, dict)


# ---------------------------------------------------------------------------
# format_research_for_section()
# ---------------------------------------------------------------------------

def test_format_with_results():
    results = {
        'market_size': [
            {'title': 'AI Market Report', 'description': '$500B by 2030'},
            {'title': 'Growth Analysis', 'description': '25% CAGR expected'},
        ],
        'competitors': [
            {'title': 'Top Players', 'description': 'Major competitors listed'},
        ],
    }
    text = format_research_for_section(results, ['market_size', 'competitors'])
    assert 'AI Market Report' in text
    assert 'Top Players' in text

def test_format_no_results():
    text = format_research_for_section({}, ['market_size'])
    assert text == 'No relevant research data available.'

def test_format_missing_keys():
    results = {'market_size': [{'title': 'Report', 'description': 'Data'}]}
    text = format_research_for_section(results, ['nonexistent_key'])
    assert text == 'No relevant research data available.'

def test_format_limits_to_4_items():
    results = {
        'key': [
            {'title': f'Result {i}', 'description': f'Desc {i}'} for i in range(10)
        ],
    }
    text = format_research_for_section(results, ['key'])
    assert 'Result 0' in text
    assert 'Result 3' in text
    assert 'Result 4' not in text
