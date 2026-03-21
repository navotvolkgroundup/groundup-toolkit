"""
Multi-factor scoring model for Founder Scout.

Replaces the simple tier system (high/medium/low) with a quantitative composite
score across five dimensions: timing, pedigree, activity, network, and intent.
Each dimension scores 0-100; a weighted composite maps to a classification
(CRITICAL / HIGH / MEDIUM / LOW / WATCHING).
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone


# --- Weights ---

WEIGHTS = {
    'timing':   0.25,
    'pedigree': 0.20,
    'activity': 0.25,
    'network':  0.15,
    'intent':   0.15,
}

# --- Classification thresholds ---

CLASSIFICATION_THRESHOLDS = [
    (85, 'CRITICAL'),
    (65, 'HIGH'),
    (40, 'MEDIUM'),
    (20, 'LOW'),
    (0,  'WATCHING'),
]


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_score_tables(conn):
    """Create person_scores table."""
    conn.execute('''CREATE TABLE IF NOT EXISTS person_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER REFERENCES tracked_people(id),
        timing_score INTEGER DEFAULT 0,
        pedigree_score INTEGER DEFAULT 0,
        activity_score INTEGER DEFAULT 0,
        network_score INTEGER DEFAULT 0,
        intent_score INTEGER DEFAULT 0,
        composite_score INTEGER DEFAULT 0,
        classification TEXT DEFAULT 'WATCHING',
        score_breakdown TEXT,
        calculated_at TEXT NOT NULL
    )''')
    conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def classify(composite_score):
    """Return classification string from score."""
    for threshold, label in CLASSIFICATION_THRESHOLDS:
        if composite_score >= threshold:
            return label
    return 'WATCHING'


def _signal_types(signals):
    """Extract set of signal_type strings from a list of signal dicts."""
    return {str(s.get('signal_type', s.get('type', '')) or '').lower() for s in signals}


def _has_signal(signals, *keywords):
    """Check if any signal's type or description contains one of the keywords."""
    for s in signals:
        text = ' '.join([
            str(s.get('signal_type', s.get('type', '')) or ''),
            str(s.get('description', '') or ''),
        ]).lower()
        for kw in keywords:
            if kw.lower() in text:
                return True
    return False


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def calculate_timing_score(person_data, signals):
    """Returns (score, explanation_string).

    Scoring:
        Retention clock IMMINENT or EXPIRED  -> 90
        Recently left company (< 3 months)   -> 80
        Changed to vague title               -> 70
        At estimated vesting boundary         -> 50
        No timing signal                     -> 10
    """
    score = 10
    explanation = 'No timing signal detected'

    types = _signal_types(signals)

    # Retention clock
    if _has_signal(signals, 'retention_expired', 'retention expired'):
        score, explanation = 90, 'Retention clock EXPIRED'
    elif _has_signal(signals, 'retention_imminent', 'retention imminent'):
        score, explanation = 90, 'Retention clock IMMINENT'

    # Recently left company
    elif _has_signal(signals, 'left_company', 'left company', 'departed'):
        # Check recency via signal date if available
        score, explanation = 80, 'Recently left company'

    # Vague title change
    elif _has_signal(signals, 'vague_title', 'exploring', 'stealth', 'next chapter'):
        score, explanation = 70, 'Changed to vague title (exploring/stealth)'

    # Vesting boundary
    elif _has_signal(signals, 'vesting_boundary', 'vesting cliff', 'cliff'):
        score, explanation = 50, 'At estimated vesting boundary'

    # Also check person_data notes for timing hints
    notes = (person_data.get('notes') or '').lower()
    if score == 10 and notes:
        if any(kw in notes for kw in ['leaving', 'left', 'departed', 'last day']):
            score, explanation = 80, 'Recently left company (from notes)'
        elif any(kw in notes for kw in ['exploring', 'stealth', 'next chapter']):
            score, explanation = 70, 'Vague title detected in notes'

    return score, explanation


def calculate_pedigree_score(person_data, idf_classification=None):
    """Returns (score, explanation_string).

    Scoring:
        Talpiot + previous founder           -> 95
        Previous successful exit (>$50M)     -> 90
        8200 + C-level/VP at growth startup  -> 80
        Elite unit + senior engineer notable -> 60
        Strong tech background only          -> 30
        No pedigree signals                  -> 10
    """
    score = 10
    explanation = 'No pedigree signals'

    notes = (person_data.get('notes') or '').lower()
    name = (person_data.get('name') or '').lower()

    has_talpiot = 'talpiot' in notes
    has_8200 = '8200' in notes
    has_elite_unit = has_talpiot or has_8200 or any(
        kw in notes for kw in ['unit 81', 'matzov', 'mamram', 'ofek']
    )
    has_exit = any(kw in notes for kw in ['exit', 'acquired', 'ipo', 'sold company'])
    has_founder = any(kw in notes for kw in ['founder', 'co-founder', 'cofounder'])
    has_clevel = any(kw in notes for kw in ['ceo', 'cto', 'coo', 'vp ', 'vp,', 'chief'])
    has_senior = any(kw in notes for kw in ['senior', 'staff', 'principal', 'lead engineer', 'architect'])
    has_strong_tech = has_senior or any(kw in notes for kw in ['google', 'meta', 'apple', 'amazon', 'microsoft', 'nvidia'])

    # IDF classification from external data source
    if idf_classification:
        idf_lower = idf_classification.lower()
        if 'talpiot' in idf_lower:
            has_talpiot = True
        if '8200' in idf_lower:
            has_8200 = True

    # Apply scoring hierarchy
    if has_talpiot and has_founder:
        score, explanation = 95, 'Talpiot + previous founder'
    elif has_exit:
        score, explanation = 90, 'Previous successful exit'
    elif has_8200 and has_clevel:
        score, explanation = 80, '8200 + C-level/VP at growth-stage startup'
    elif has_elite_unit and has_senior:
        score, explanation = 60, 'Elite unit + senior engineer at notable company'
    elif has_strong_tech:
        score, explanation = 30, 'Strong tech background without unit/founder signals'

    return score, explanation


def calculate_activity_score(signals, github_signals=None, going_dark=False, advisory_count=0):
    """Returns (score, explanation_string).

    Scoring:
        New company registered                      -> 95
        GitHub: new org + landing page + domain      -> 90
        Domain registration matching name            -> 80
        Going dark after period of activity          -> 60
        Advisory role accumulation                   -> 50
        Content shift to startup topics              -> 30
        No unusual activity                          -> 5
    """
    score = 5
    explanation = 'No unusual activity'

    gh = github_signals or []

    # Company registration
    if _has_signal(signals, 'company_registered', 'company registration', 'new company'):
        score, explanation = 95, 'New company registered'

    # GitHub: new org + landing page + domain
    elif (
        _has_signal(gh, 'new_org', 'new org') and
        _has_signal(gh, 'landing_page', 'landing page', 'product') and
        _has_signal(gh, 'custom_domain', 'domain')
    ):
        score, explanation = 90, 'GitHub: new org + landing page + custom domain'

    # Domain registration
    elif _has_signal(signals, 'domain_registration', 'domain registered', 'new domain'):
        score, explanation = 80, 'Domain registration matching name'

    # Going dark
    elif going_dark:
        score, explanation = 60, 'Going dark after period of activity'

    # Advisory accumulation
    elif advisory_count >= 3:
        score, explanation = 50, f'Advisory role accumulation ({advisory_count} roles)'

    # Content shift
    elif _has_signal(signals, 'content_shift', 'startup topics', 'startup content'):
        score, explanation = 30, 'Content shift to startup topics'

    # Still check github signals for individual contributions
    elif _has_signal(gh, 'new_org', 'new org'):
        score, explanation = 70, 'New GitHub organization created'
    elif _has_signal(gh, 'landing_page', 'landing page', 'product'):
        score, explanation = 60, 'Product-looking repo on GitHub'
    elif _has_signal(gh, 'activity_spike', 'spike'):
        score, explanation = 40, 'GitHub activity spike detected'

    return score, explanation


def calculate_network_score(connection_signals=None):
    """Returns (score, explanation_string).

    Scoring:
        Team formation pattern detected              -> 95
        Startup lawyer + other watchlist member       -> 90
        New VC/angel connections spike                -> 60
        Connected with other watchlist members        -> 40
        No network signals                           -> 5
    """
    score = 5
    explanation = 'No network signals'
    sigs = connection_signals or []

    if _has_signal(sigs, 'team_formation', 'team forming', 'co-founder pair'):
        score, explanation = 95, 'Team formation pattern detected'
    elif (
        _has_signal(sigs, 'startup_lawyer', 'lawyer') and
        _has_signal(sigs, 'watchlist_member', 'watchlist')
    ):
        score, explanation = 90, 'Connected with startup lawyer + watchlist member'
    elif _has_signal(sigs, 'vc_spike', 'vc connections', 'angel connections', 'investor'):
        score, explanation = 60, 'New VC/angel connections spike'
    elif _has_signal(sigs, 'watchlist_member', 'watchlist'):
        score, explanation = 40, 'Connected with other watchlist members'

    return score, explanation


def calculate_intent_score(signals, company_registered=False):
    """Returns (score, explanation_string).

    Scoring:
        Company registration                         -> 100
        Multiple concurrent signals (3+)             -> 80
        Stealth mode + another signal                -> 70
        Single strong signal                         -> 50
        Single weak signal                           -> 20
        No intent signals                            -> 5
    """
    score = 5
    explanation = 'No intent signals'

    if company_registered or _has_signal(signals, 'company_registered', 'company registration'):
        return 100, 'Company registered'

    # Count distinct intent-relevant signal types
    intent_keywords = [
        'stealth', 'exploring', 'left_company', 'departed', 'new_repo',
        'new_org', 'domain', 'landing_page', 'product', 'activity_spike',
        'vague_title', 'team_formation', 'vc_spike', 'lawyer',
    ]
    matched_types = set()
    for s in signals:
        text = ' '.join([
            str(s.get('signal_type', s.get('type', '')) or ''),
            str(s.get('description', '') or ''),
        ]).lower()
        for kw in intent_keywords:
            if kw in text:
                matched_types.add(kw)

    strong_keywords = {'stealth', 'new_org', 'landing_page', 'product', 'domain', 'team_formation'}
    strong_matches = matched_types & strong_keywords
    has_stealth = 'stealth' in matched_types

    if len(matched_types) >= 3:
        score, explanation = 80, f'Multiple concurrent signals ({len(matched_types)} distinct types)'
    elif has_stealth and len(matched_types) >= 2:
        score, explanation = 70, 'Stealth mode + additional signal'
    elif strong_matches:
        score, explanation = 50, f'Single strong signal: {", ".join(sorted(strong_matches))}'
    elif matched_types:
        score, explanation = 20, f'Single weak signal: {", ".join(sorted(matched_types))}'

    return score, explanation


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

def calculate_composite_score(
    person_data,
    signals,
    idf_data=None,
    github_signals=None,
    going_dark=False,
    advisory_count=0,
    connection_signals=None,
    company_registered=False,
):
    """Calculate all dimensions and return full score dict.

    Returns:
        {
            timing_score, pedigree_score, activity_score, network_score, intent_score,
            composite_score, classification,
            breakdown: {timing_explanation, pedigree_explanation, activity_explanation,
                        network_explanation, intent_explanation}
        }
    """
    all_signals = list(signals) + list(github_signals or []) + list(connection_signals or [])

    timing_score, timing_expl = calculate_timing_score(person_data, signals)
    idf_unit = idf_data.get('unit') if isinstance(idf_data, dict) else idf_data
    pedigree_score, pedigree_expl = calculate_pedigree_score(person_data, idf_unit)
    activity_score, activity_expl = calculate_activity_score(
        signals, github_signals=github_signals,
        going_dark=going_dark, advisory_count=advisory_count,
    )
    network_score, network_expl = calculate_network_score(connection_signals)
    intent_score, intent_expl = calculate_intent_score(all_signals, company_registered=company_registered)

    composite = round(
        timing_score * WEIGHTS['timing']
        + pedigree_score * WEIGHTS['pedigree']
        + activity_score * WEIGHTS['activity']
        + network_score * WEIGHTS['network']
        + intent_score * WEIGHTS['intent']
    )

    return {
        'timing_score': timing_score,
        'pedigree_score': pedigree_score,
        'activity_score': activity_score,
        'network_score': network_score,
        'intent_score': intent_score,
        'composite_score': composite,
        'classification': classify(composite),
        'breakdown': {
            'timing_explanation': timing_expl,
            'pedigree_explanation': pedigree_expl,
            'activity_explanation': activity_expl,
            'network_explanation': network_expl,
            'intent_explanation': intent_expl,
        },
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_score(conn, person_id, score_data):
    """Save score to person_scores table."""
    conn.execute(
        '''INSERT INTO person_scores
           (person_id, timing_score, pedigree_score, activity_score, network_score,
            intent_score, composite_score, classification, score_breakdown, calculated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            person_id,
            score_data['timing_score'],
            score_data['pedigree_score'],
            score_data['activity_score'],
            score_data['network_score'],
            score_data['intent_score'],
            score_data['composite_score'],
            score_data['classification'],
            json.dumps(score_data['breakdown']),
            datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        ),
    )
    conn.commit()


def get_latest_score(conn, person_id):
    """Get most recent score for a person."""
    row = conn.execute(
        '''SELECT timing_score, pedigree_score, activity_score, network_score,
                  intent_score, composite_score, classification, score_breakdown,
                  calculated_at
           FROM person_scores
           WHERE person_id = ?
           ORDER BY calculated_at DESC
           LIMIT 1''',
        (person_id,),
    ).fetchone()
    if not row:
        return None
    return {
        'timing_score': row[0],
        'pedigree_score': row[1],
        'activity_score': row[2],
        'network_score': row[3],
        'intent_score': row[4],
        'composite_score': row[5],
        'classification': row[6],
        'breakdown': json.loads(row[7]) if row[7] else {},
        'calculated_at': row[8],
    }


def get_score_changes(conn, days=7):
    """Get people whose classification changed in the last N days.

    Returns list of dicts with person_id, name, old_classification, new_classification,
    old_composite, new_composite.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Get latest two scores per person where the most recent is within the window
    rows = conn.execute('''
        WITH ranked AS (
            SELECT ps.person_id, ps.composite_score, ps.classification, ps.calculated_at,
                   ROW_NUMBER() OVER (PARTITION BY ps.person_id ORDER BY ps.calculated_at DESC) AS rn
            FROM person_scores ps
        )
        SELECT
            curr.person_id,
            tp.name,
            prev.classification AS old_classification,
            curr.classification AS new_classification,
            prev.composite_score AS old_composite,
            curr.composite_score AS new_composite
        FROM ranked curr
        JOIN ranked prev ON curr.person_id = prev.person_id AND prev.rn = 2
        JOIN tracked_people tp ON tp.id = curr.person_id
        WHERE curr.rn = 1
          AND curr.calculated_at >= ?
          AND curr.classification != prev.classification
        ORDER BY curr.composite_score DESC
    ''', (cutoff,)).fetchall()

    return [
        {
            'person_id': r[0],
            'name': r[1],
            'old_classification': r[2],
            'new_classification': r[3],
            'old_composite': r[4],
            'new_composite': r[5],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Conviction Engine: Outcome Correlation & Weight Calibration
# ---------------------------------------------------------------------------

DIMENSIONS = ['timing', 'pedigree', 'activity', 'network', 'intent']
MIN_OUTCOMES_FOR_CALIBRATION = 20


def analyze_weight_effectiveness(conn):
    """Analyze which scoring dimensions best predict positive outcomes.

    For each dimension, computes mean score for positive outcomes (met/invested)
    vs negative (passed/noise), then calculates an effectiveness ratio.

    Requires MIN_OUTCOMES_FOR_CALIBRATION outcomes to produce suggestions.

    Returns:
        {
            dimension: {
                weight_current: float,
                mean_positive: float,
                mean_negative: float,
                effectiveness: float,  # positive_mean / negative_mean (higher = better predictor)
                suggested_weight: float,
            },
            ...
            _meta: {total_outcomes, sufficient_data: bool}
        }
    """
    rows = conn.execute('''
        SELECT ps.timing_score, ps.pedigree_score, ps.activity_score,
               ps.network_score, ps.intent_score, tp.outcome
        FROM person_scores ps
        JOIN tracked_people tp ON tp.id = ps.person_id
        WHERE tp.outcome IS NOT NULL
          AND ps.id IN (
              SELECT MAX(id) FROM person_scores GROUP BY person_id
          )
    ''').fetchall()

    total = len(rows)
    result = {}

    if total == 0:
        for dim in DIMENSIONS:
            result[dim] = {
                'weight_current': WEIGHTS[dim],
                'mean_positive': 0, 'mean_negative': 0,
                'effectiveness': 0, 'suggested_weight': WEIGHTS[dim],
            }
        result['_meta'] = {'total_outcomes': 0, 'sufficient_data': False}
        return result

    # Split into positive and negative outcomes
    positive = [r for r in rows if r[5] in ('met', 'invested')]
    negative = [r for r in rows if r[5] in ('passed', 'noise')]

    dim_indices = {'timing': 0, 'pedigree': 1, 'activity': 2, 'network': 3, 'intent': 4}
    effectiveness_scores = {}

    for dim, idx in dim_indices.items():
        pos_mean = sum(r[idx] for r in positive) / len(positive) if positive else 0
        neg_mean = sum(r[idx] for r in negative) / len(negative) if negative else 0

        # Effectiveness: how much does this dimension differentiate positive from negative?
        if neg_mean > 0:
            effectiveness = round(pos_mean / neg_mean, 3)
        elif pos_mean > 0:
            effectiveness = 2.0  # positive signal with no negative baseline
        else:
            effectiveness = 1.0  # no signal

        effectiveness_scores[dim] = effectiveness
        result[dim] = {
            'weight_current': WEIGHTS[dim],
            'mean_positive': round(pos_mean, 1),
            'mean_negative': round(neg_mean, 1),
            'effectiveness': effectiveness,
            'suggested_weight': 0,  # computed below
        }

    # Normalize effectiveness into suggested weights (must sum to 1.0)
    sufficient = total >= MIN_OUTCOMES_FOR_CALIBRATION
    total_effectiveness = sum(effectiveness_scores.values())

    if total_effectiveness > 0 and sufficient:
        for dim in DIMENSIONS:
            result[dim]['suggested_weight'] = round(
                effectiveness_scores[dim] / total_effectiveness, 3
            )
    else:
        # Not enough data — suggest current weights
        for dim in DIMENSIONS:
            result[dim]['suggested_weight'] = WEIGHTS[dim]

    result['_meta'] = {'total_outcomes': total, 'sufficient_data': sufficient}
    return result


def get_precision_by_tier(conn):
    """Get precision stats per classification tier.

    Returns:
        {tier: {total, positive, precision}} for each tier with outcomes.
    """
    rows = conn.execute('''
        SELECT ps.classification, tp.outcome, COUNT(*) as cnt
        FROM person_scores ps
        JOIN tracked_people tp ON tp.id = ps.person_id
        WHERE tp.outcome IS NOT NULL
          AND ps.id IN (
              SELECT MAX(id) FROM person_scores GROUP BY person_id
          )
        GROUP BY ps.classification, tp.outcome
    ''').fetchall()

    tiers = {}
    for classification, outcome, count in rows:
        if classification not in tiers:
            tiers[classification] = {'total': 0, 'positive': 0}
        tiers[classification]['total'] += count
        if outcome in ('met', 'invested'):
            tiers[classification]['positive'] += count

    for stats in tiers.values():
        stats['precision'] = round(stats['positive'] / stats['total'], 2) if stats['total'] > 0 else 0

    return tiers


def apply_thesis_matching(composite_score, profile_text, thesis_config):
    """Apply thesis area matching as a multiplier on composite score.

    Args:
        composite_score: raw composite score (0-100)
        profile_text: person's LinkedIn profile text / headline
        thesis_config: dict loaded from thesis.yaml with 'thesis_areas' and 'anti_thesis'

    Returns:
        (adjusted_score, thesis_match): tuple of adjusted score and matched thesis name or None
    """
    if not thesis_config or not profile_text:
        return composite_score, None

    text_lower = profile_text.lower()
    best_match = None
    best_boost = 1.0

    # Check thesis areas
    for area in thesis_config.get('thesis_areas', []):
        keywords = area.get('keywords', [])
        matches = sum(1 for kw in keywords if kw.lower() in text_lower)
        if matches >= 2:  # require 2+ keyword matches
            boost = area.get('weight_boost', 1.0)
            if boost > best_boost:
                best_boost = boost
                best_match = area.get('name', 'Unknown')

    # Check anti-thesis (only if no positive match)
    if not best_match:
        for anti in thesis_config.get('anti_thesis', []):
            keywords = anti.get('keywords', [])
            matches = sum(1 for kw in keywords if kw.lower() in text_lower)
            if matches >= 2:
                penalty = anti.get('weight_penalty', 1.0)
                best_boost = penalty
                best_match = f"Anti-thesis ({', '.join(keywords[:2])})"
                break

    adjusted = min(100, max(0, round(composite_score * best_boost)))
    return adjusted, best_match


def get_calibration_report(conn):
    """Generate a full calibration report combining all conviction engine data.

    Returns JSON-serializable dict for CLI and dashboard consumption.
    """
    effectiveness = analyze_weight_effectiveness(conn)
    precision = get_precision_by_tier(conn)

    meta = effectiveness.pop('_meta', {})
    dimensions = {}
    for dim in DIMENSIONS:
        d = effectiveness.get(dim, {})
        dimensions[dim] = {
            'current_weight': d.get('weight_current', WEIGHTS.get(dim, 0)),
            'suggested_weight': d.get('suggested_weight', WEIGHTS.get(dim, 0)),
            'effectiveness': d.get('effectiveness', 0),
            'mean_positive': d.get('mean_positive', 0),
            'mean_negative': d.get('mean_negative', 0),
        }

    return {
        'dimensions': dimensions,
        'precision_by_tier': precision,
        'total_outcomes': meta.get('total_outcomes', 0),
        'sufficient_data': meta.get('sufficient_data', False),
        'current_weights': dict(WEIGHTS),
    }
