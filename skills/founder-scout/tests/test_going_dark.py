"""Tests for modules/going_dark.py — LinkedIn activity drop detection."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.going_dark import (
    _parse_relative_date, extract_activity_metrics,
    detect_going_dark, save_activity_snapshot,
)
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# _parse_relative_date()
# ---------------------------------------------------------------------------

def test_parse_days_ago():
    result = _parse_relative_date('3 days ago')
    expected = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    assert result == expected

def test_parse_weeks_ago():
    result = _parse_relative_date('2 weeks ago')
    expected = (datetime.now() - timedelta(weeks=2)).strftime('%Y-%m-%d')
    assert result == expected

def test_parse_months_ago():
    result = _parse_relative_date('1 month ago')
    expected = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    assert result == expected

def test_parse_unparseable():
    assert _parse_relative_date('yesterday') is None
    assert _parse_relative_date('just now') is None
    assert _parse_relative_date('') is None


# ---------------------------------------------------------------------------
# extract_activity_metrics()
# ---------------------------------------------------------------------------

def test_extract_posts():
    text = 'StaticText "42 posts"\nStaticText "Posted 3 days ago"'
    metrics = extract_activity_metrics(text)
    assert metrics['posts_count_30d'] == 42
    assert metrics['last_post_date'] is not None

def test_extract_engagements():
    text = 'StaticText "15 comments"\nStaticText "8 reactions"'
    metrics = extract_activity_metrics(text)
    assert metrics['engagements_count_30d'] == 23

def test_extract_empty():
    metrics = extract_activity_metrics('')
    assert metrics['posts_count_30d'] == 0
    assert metrics['engagements_count_30d'] == 0

def test_extract_none():
    metrics = extract_activity_metrics(None)
    assert metrics['posts_count_30d'] == 0

def test_extract_profile_updated():
    text = 'Updated their profile photo on March 2026'
    metrics = extract_activity_metrics(text)
    assert metrics['profile_updated'] == 1

def test_extract_articles_added_to_posts():
    text = 'StaticText "10 posts"\nStaticText "5 articles"'
    metrics = extract_activity_metrics(text)
    assert metrics['posts_count_30d'] == 15


# ---------------------------------------------------------------------------
# detect_going_dark() — requires DB fixtures
# ---------------------------------------------------------------------------

def test_detect_going_dark_insufficient_data(db):
    """Need at least 3 snapshots to detect."""
    db.execute("INSERT INTO tracked_people (name) VALUES ('Test Person')")
    person_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    # Only 2 snapshots
    for i in range(2):
        date = (datetime.now() - timedelta(days=30*i)).strftime('%Y-%m-%d')
        db.execute(
            "INSERT INTO activity_snapshots (person_id, snapshot_date, posts_count_30d) VALUES (?, ?, ?)",
            (person_id, date, 10),
        )
    db.commit()

    result = detect_going_dark(db, person_id)
    assert result is None

def test_detect_going_dark_active_person(db):
    """Consistently active person should not trigger."""
    db.execute("INSERT INTO tracked_people (name) VALUES ('Active Person')")
    person_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    for i in range(5):
        date = (datetime.now() - timedelta(days=14*i)).strftime('%Y-%m-%d')
        db.execute(
            "INSERT INTO activity_snapshots (person_id, snapshot_date, posts_count_30d) VALUES (?, ?, ?)",
            (person_id, date, 10),
        )
    db.commit()

    result = detect_going_dark(db, person_id)
    assert result is None

def test_detect_going_dark_drops_to_zero(db):
    """Active person suddenly going silent should trigger."""
    db.execute("INSERT INTO tracked_people (name) VALUES ('Gone Dark')")
    person_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    # Old snapshots: active (high posts)
    for i in range(3, 6):
        date = (datetime.now() - timedelta(days=14*i)).strftime('%Y-%m-%d')
        db.execute(
            "INSERT INTO activity_snapshots (person_id, snapshot_date, posts_count_30d) VALUES (?, ?, ?)",
            (person_id, date, 15),
        )

    # Recent snapshots: silent
    for i in range(2):
        date = (datetime.now() - timedelta(days=14*i)).strftime('%Y-%m-%d')
        db.execute(
            "INSERT INTO activity_snapshots (person_id, snapshot_date, posts_count_30d) VALUES (?, ?, ?)",
            (person_id, date, 0),
        )
    db.commit()

    result = detect_going_dark(db, person_id, current_employment_status='left_role')
    assert result is not None
    assert result['signal_type'] == 'going_dark'
    assert result['tier'] == 'high'
