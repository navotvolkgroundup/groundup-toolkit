"""Tests for modules/scoring.py — composite scoring model."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.scoring import (
    classify, _signal_types, _has_signal,
    calculate_timing_score, calculate_pedigree_score,
    calculate_activity_score, calculate_network_score,
    calculate_intent_score, calculate_composite_score,
    analyze_weight_effectiveness, get_precision_by_tier,
    apply_thesis_matching, get_calibration_report,
    init_score_tables, save_score, WEIGHTS, DIMENSIONS,
    MIN_OUTCOMES_FOR_CALIBRATION,
)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------

def test_classify_critical():
    assert classify(85) == 'CRITICAL'
    assert classify(100) == 'CRITICAL'

def test_classify_high():
    assert classify(65) == 'HIGH'
    assert classify(84) == 'HIGH'

def test_classify_medium():
    assert classify(40) == 'MEDIUM'
    assert classify(64) == 'MEDIUM'

def test_classify_low():
    assert classify(20) == 'LOW'
    assert classify(39) == 'LOW'

def test_classify_watching():
    assert classify(0) == 'WATCHING'
    assert classify(19) == 'WATCHING'


# ---------------------------------------------------------------------------
# _signal_types() and _has_signal()
# ---------------------------------------------------------------------------

def test_signal_types_basic():
    signals = [
        {'signal_type': 'left_company', 'description': 'Left Google'},
        {'signal_type': 'stealth', 'description': 'Changed to stealth mode'},
    ]
    types = _signal_types(signals)
    assert 'left_company' in types
    assert 'stealth' in types

def test_signal_types_with_dict_value():
    """Regression: signal_type or type could be a dict instead of string."""
    signals = [
        {'signal_type': {'nested': 'value'}, 'description': 'bad data'},
        {'type': None, 'description': 'missing type'},
    ]
    types = _signal_types(signals)
    # Should not crash — values coerced to strings
    assert isinstance(types, set)

def test_signal_types_empty():
    assert _signal_types([]) == set()

def test_has_signal_match():
    signals = [{'signal_type': 'left_company', 'description': 'Departed from Google'}]
    assert _has_signal(signals, 'left_company') is True
    assert _has_signal(signals, 'departed') is True

def test_has_signal_no_match():
    signals = [{'signal_type': 'stealth', 'description': 'In stealth mode'}]
    assert _has_signal(signals, 'left_company') is False

def test_has_signal_with_dict_value():
    """Regression: should not crash if signal values are dicts."""
    signals = [{'signal_type': {'bad': 'data'}, 'description': {'also': 'bad'}}]
    assert _has_signal(signals, 'anything') is False


# ---------------------------------------------------------------------------
# calculate_timing_score()
# ---------------------------------------------------------------------------

def test_timing_retention_expired():
    person = {'notes': ''}
    signals = [{'signal_type': 'retention_expired', 'description': 'Vesting expired'}]
    score, expl = calculate_timing_score(person, signals)
    assert score == 90
    assert 'EXPIRED' in expl

def test_timing_left_company():
    person = {'notes': ''}
    signals = [{'signal_type': 'left_company', 'description': 'Left role'}]
    score, _ = calculate_timing_score(person, signals)
    assert score == 80

def test_timing_vague_title():
    person = {'notes': ''}
    signals = [{'signal_type': 'vague_title', 'description': 'exploring'}]
    score, _ = calculate_timing_score(person, signals)
    assert score == 70

def test_timing_from_notes():
    person = {'notes': 'Left Google, exploring next chapter'}
    signals = []
    score, _ = calculate_timing_score(person, signals)
    assert score == 80  # 'left' detected in notes

def test_timing_no_signal():
    person = {'notes': ''}
    signals = []
    score, _ = calculate_timing_score(person, signals)
    assert score == 10


# ---------------------------------------------------------------------------
# calculate_pedigree_score()
# ---------------------------------------------------------------------------

def test_pedigree_talpiot_founder():
    person = {'name': 'Test Person', 'notes': 'talpiot alumni, co-founder of previous startup'}
    score, _ = calculate_pedigree_score(person)
    assert score == 95

def test_pedigree_exit():
    person = {'name': 'Test', 'notes': 'company was acquired by Microsoft'}
    score, _ = calculate_pedigree_score(person)
    assert score == 90

def test_pedigree_8200_clevel():
    person = {'name': 'Test', 'notes': '8200 alumni, CTO at growth-stage startup'}
    score, _ = calculate_pedigree_score(person)
    assert score == 80

def test_pedigree_idf_override():
    """IDF classification from external data enriches pedigree scoring."""
    person = {'name': 'Test', 'notes': 'senior engineer at Google, co-founder'}
    score_without, _ = calculate_pedigree_score(person, idf_classification=None)
    score_with, _ = calculate_pedigree_score(person, idf_classification='Talpiot')
    # Without IDF: has senior+google+founder but no elite unit -> 30 (strong tech)
    # With Talpiot: talpiot + founder -> 95
    assert score_with > score_without

def test_pedigree_no_signals():
    person = {'name': 'Test', 'notes': 'Junior developer at small company'}
    score, _ = calculate_pedigree_score(person)
    assert score == 10


# ---------------------------------------------------------------------------
# calculate_activity_score()
# ---------------------------------------------------------------------------

def test_activity_company_registered():
    signals = [{'signal_type': 'company_registered', 'description': 'New company'}]
    score, _ = calculate_activity_score(signals)
    assert score == 95

def test_activity_github_new_org():
    github = [{'signal_type': 'new_org', 'description': 'Created org'}]
    score, _ = calculate_activity_score([], github_signals=github)
    assert score == 70

def test_activity_going_dark():
    score, _ = calculate_activity_score([], going_dark=True)
    assert score == 60

def test_activity_advisory():
    score, _ = calculate_activity_score([], advisory_count=4)
    assert score == 50

def test_activity_no_signals():
    score, _ = calculate_activity_score([])
    assert score == 5


# ---------------------------------------------------------------------------
# calculate_network_score()
# ---------------------------------------------------------------------------

def test_network_team_formation():
    sigs = [{'signal_type': 'team_formation', 'description': 'Co-founder pair'}]
    score, _ = calculate_network_score(sigs)
    assert score == 95

def test_network_vc_spike():
    sigs = [{'signal_type': 'vc_spike', 'description': 'Connected with 5 VCs'}]
    score, _ = calculate_network_score(sigs)
    assert score == 60

def test_network_no_signals():
    score, _ = calculate_network_score()
    assert score == 5


# ---------------------------------------------------------------------------
# calculate_intent_score()
# ---------------------------------------------------------------------------

def test_intent_company_registered():
    score, _ = calculate_intent_score([], company_registered=True)
    assert score == 100

def test_intent_multiple_signals():
    signals = [
        {'signal_type': 'stealth', 'description': 'In stealth mode'},
        {'signal_type': 'new_org', 'description': 'Created GitHub org'},
        {'signal_type': 'domain', 'description': 'New domain registered'},
    ]
    score, _ = calculate_intent_score(signals)
    assert score == 80

def test_intent_stealth_plus_one():
    signals = [
        {'signal_type': 'stealth', 'description': 'Stealth mode'},
        {'signal_type': 'left_company', 'description': 'Left job'},
    ]
    score, _ = calculate_intent_score(signals)
    assert score == 70

def test_intent_single_strong():
    signals = [{'signal_type': 'landing_page', 'description': 'Product page'}]
    score, _ = calculate_intent_score(signals)
    assert score == 50

def test_intent_single_weak():
    signals = [{'signal_type': 'departed', 'description': 'Left company'}]
    score, _ = calculate_intent_score(signals)
    assert score == 20

def test_intent_no_signals():
    score, _ = calculate_intent_score([])
    assert score == 5


# ---------------------------------------------------------------------------
# calculate_composite_score()
# ---------------------------------------------------------------------------

def test_composite_all_max():
    """Hot founder: all dimensions maxed out."""
    person = {'name': 'Test', 'notes': 'talpiot co-founder, company acquired'}
    signals = [
        {'signal_type': 'retention_expired', 'description': 'Vesting expired'},
        {'signal_type': 'company_registered', 'description': 'New company'},
    ]
    result = calculate_composite_score(
        person, signals,
        company_registered=True,
        connection_signals=[{'signal_type': 'team_formation', 'description': 'pair'}],
    )
    assert result['classification'] in ('CRITICAL', 'HIGH')
    assert result['composite_score'] >= 65
    assert 'breakdown' in result
    assert 'timing_explanation' in result['breakdown']

def test_composite_cold_lead():
    """Cold lead: no signals at all."""
    person = {'name': 'Test', 'notes': ''}
    result = calculate_composite_score(person, [])
    assert result['classification'] == 'WATCHING'
    assert result['composite_score'] < 20


# ---------------------------------------------------------------------------
# Conviction Engine: setup helpers
# ---------------------------------------------------------------------------

import sqlite3

def _make_conviction_db(num_positive=10, num_negative=10):
    """Create in-memory DB with tracked_people + person_scores + outcomes."""
    conn = sqlite3.connect(':memory:')
    conn.execute('''CREATE TABLE tracked_people (
        id INTEGER PRIMARY KEY, name TEXT, status TEXT DEFAULT 'active',
        outcome TEXT, linkedin_url TEXT, headline TEXT,
        signal_tier TEXT, last_signal TEXT, last_scanned TEXT
    )''')
    init_score_tables(conn)

    pid = 0
    # Positive outcomes: high scores on timing + intent
    for i in range(num_positive):
        pid += 1
        outcome = 'invested' if i % 2 == 0 else 'met'
        conn.execute(
            'INSERT INTO tracked_people (id, name, outcome) VALUES (?, ?, ?)',
            (pid, f'Pos_{i}', outcome)
        )
        conn.execute(
            '''INSERT INTO person_scores
               (person_id, timing_score, pedigree_score, activity_score,
                network_score, intent_score, composite_score, classification, calculated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))''',
            (pid, 80, 60, 70, 50, 85, 72, 'HIGH')
        )

    # Negative outcomes: low scores on timing + intent
    for i in range(num_negative):
        pid += 1
        outcome = 'noise' if i % 2 == 0 else 'passed'
        conn.execute(
            'INSERT INTO tracked_people (id, name, outcome) VALUES (?, ?, ?)',
            (pid, f'Neg_{i}', outcome)
        )
        conn.execute(
            '''INSERT INTO person_scores
               (person_id, timing_score, pedigree_score, activity_score,
                network_score, intent_score, composite_score, classification, calculated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))''',
            (pid, 20, 40, 30, 35, 15, 28, 'LOW')
        )

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# analyze_weight_effectiveness()
# ---------------------------------------------------------------------------

def test_effectiveness_no_outcomes():
    conn = sqlite3.connect(':memory:')
    conn.execute('''CREATE TABLE tracked_people (
        id INTEGER PRIMARY KEY, name TEXT, outcome TEXT
    )''')
    init_score_tables(conn)
    result = analyze_weight_effectiveness(conn)
    assert result['_meta']['total_outcomes'] == 0
    assert result['_meta']['sufficient_data'] is False
    for dim in DIMENSIONS:
        assert result[dim]['suggested_weight'] == WEIGHTS[dim]

def test_effectiveness_insufficient_data():
    conn = _make_conviction_db(num_positive=5, num_negative=3)
    result = analyze_weight_effectiveness(conn)
    assert result['_meta']['total_outcomes'] == 8
    assert result['_meta']['sufficient_data'] is False
    # Should fall back to current weights
    for dim in DIMENSIONS:
        assert result[dim]['suggested_weight'] == WEIGHTS[dim]

def test_effectiveness_sufficient_data():
    conn = _make_conviction_db(num_positive=12, num_negative=10)
    result = analyze_weight_effectiveness(conn)
    assert result['_meta']['total_outcomes'] == 22
    assert result['_meta']['sufficient_data'] is True
    # Suggested weights should sum to ~1.0
    total_suggested = sum(result[dim]['suggested_weight'] for dim in DIMENSIONS)
    assert abs(total_suggested - 1.0) < 0.01

def test_effectiveness_dimensions_present():
    conn = _make_conviction_db(num_positive=12, num_negative=10)
    result = analyze_weight_effectiveness(conn)
    for dim in DIMENSIONS:
        d = result[dim]
        assert 'weight_current' in d
        assert 'mean_positive' in d
        assert 'mean_negative' in d
        assert 'effectiveness' in d
        assert d['mean_positive'] > d['mean_negative']  # positive should score higher

def test_effectiveness_timing_strongest():
    """Timing has biggest gap (80 vs 20), so should have highest effectiveness."""
    conn = _make_conviction_db(num_positive=12, num_negative=10)
    result = analyze_weight_effectiveness(conn)
    timing_eff = result['timing']['effectiveness']
    pedigree_eff = result['pedigree']['effectiveness']
    assert timing_eff > pedigree_eff


# ---------------------------------------------------------------------------
# get_precision_by_tier()
# ---------------------------------------------------------------------------

def test_precision_empty():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE tracked_people (id INTEGER PRIMARY KEY, name TEXT, outcome TEXT)')
    init_score_tables(conn)
    assert get_precision_by_tier(conn) == {}

def test_precision_by_tier_basic():
    conn = _make_conviction_db(num_positive=10, num_negative=10)
    result = get_precision_by_tier(conn)
    # Positive = HIGH, Negative = LOW based on our fixture
    assert 'HIGH' in result
    assert result['HIGH']['precision'] == 1.0  # all HIGH are positive
    assert 'LOW' in result
    assert result['LOW']['precision'] == 0.0  # all LOW are negative

def test_precision_counts():
    conn = _make_conviction_db(num_positive=10, num_negative=10)
    result = get_precision_by_tier(conn)
    assert result['HIGH']['total'] == 10
    assert result['LOW']['total'] == 10


# ---------------------------------------------------------------------------
# apply_thesis_matching()
# ---------------------------------------------------------------------------

SAMPLE_THESIS = {
    'thesis_areas': [
        {'name': 'AI Infrastructure', 'keywords': ['infrastructure', 'MLOps', 'model serving', 'GPU', 'inference'], 'weight_boost': 1.2},
        {'name': 'Developer Tools', 'keywords': ['developer', 'devtools', 'API', 'SDK', 'platform'], 'weight_boost': 1.15},
    ],
    'anti_thesis': [
        {'keywords': ['consumer', 'social media', 'gaming', 'e-commerce'], 'weight_penalty': 0.7},
    ],
}

def test_thesis_no_match():
    score, match = apply_thesis_matching(70, "CEO at HealthTech startup", SAMPLE_THESIS)
    assert score == 70
    assert match is None

def test_thesis_positive_match():
    score, match = apply_thesis_matching(70, "Building ML infrastructure and model serving platform", SAMPLE_THESIS)
    assert match == 'AI Infrastructure'
    assert score == 84  # 70 * 1.2

def test_thesis_anti_match():
    score, match = apply_thesis_matching(70, "Building consumer social media app", SAMPLE_THESIS)
    assert 'Anti-thesis' in match
    assert score == 49  # 70 * 0.7

def test_thesis_requires_two_keywords():
    """Single keyword match should NOT trigger boost."""
    score, match = apply_thesis_matching(70, "Working on infrastructure", SAMPLE_THESIS)
    assert match is None
    assert score == 70

def test_thesis_best_boost_wins():
    """When multiple thesis areas match, highest boost wins."""
    score, match = apply_thesis_matching(70, "Building developer API infrastructure for MLOps model serving", SAMPLE_THESIS)
    assert match == 'AI Infrastructure'  # 1.2 > 1.15
    assert score == 84

def test_thesis_empty_profile():
    score, match = apply_thesis_matching(70, "", SAMPLE_THESIS)
    assert score == 70
    assert match is None

def test_thesis_none_config():
    score, match = apply_thesis_matching(70, "Some profile text", None)
    assert score == 70
    assert match is None

def test_thesis_score_capped():
    """Score should not exceed 100."""
    score, match = apply_thesis_matching(90, "Building ML infrastructure and model serving platform", SAMPLE_THESIS)
    assert score == 100  # 90 * 1.2 = 108 -> capped at 100

def test_thesis_anti_no_positive():
    """Anti-thesis only applies when no positive match."""
    score, match = apply_thesis_matching(70, "Building consumer social media MLOps infrastructure platform", SAMPLE_THESIS)
    # Has both AI Infra (infra + MLOps) and anti-thesis (consumer + social media) matches
    # Positive match takes priority
    assert match == 'AI Infrastructure'
    assert score == 84


# ---------------------------------------------------------------------------
# get_calibration_report()
# ---------------------------------------------------------------------------

def test_calibration_report_structure():
    conn = _make_conviction_db(num_positive=12, num_negative=10)
    report = get_calibration_report(conn)
    assert 'dimensions' in report
    assert 'precision_by_tier' in report
    assert 'total_outcomes' in report
    assert 'sufficient_data' in report
    assert 'current_weights' in report
    assert report['total_outcomes'] == 22
    assert report['sufficient_data'] is True
    for dim in DIMENSIONS:
        assert dim in report['dimensions']

def test_calibration_report_empty():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE tracked_people (id INTEGER PRIMARY KEY, name TEXT, outcome TEXT)')
    init_score_tables(conn)
    report = get_calibration_report(conn)
    assert report['total_outcomes'] == 0
    assert report['sufficient_data'] is False
