"""
Going Dark Detection — Identifies when LinkedIn-tracked founders go quiet.

A sudden drop in LinkedIn activity can signal that someone is heads-down building
a new company. This module captures activity snapshots over time, calculates a
rolling baseline, and flags when activity drops below 30% of baseline for 2+
consecutive weeks.

Combines with employment status for tiering:
  - Recently left role + going dark = HIGH
  - Still lists corporate role + going dark = MEDIUM
"""

import re
import json
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

def init_activity_tables(conn):
    """Create activity_snapshots table."""
    conn.execute('''CREATE TABLE IF NOT EXISTS activity_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER REFERENCES tracked_people(id),
        snapshot_date TEXT NOT NULL,
        posts_count_30d INTEGER DEFAULT 0,
        engagements_count_30d INTEGER DEFAULT 0,
        last_post_date TEXT,
        last_engagement_date TEXT,
        profile_updated INTEGER DEFAULT 0
    )''')
    conn.commit()


# ---------------------------------------------------------------------------
# Activity extraction from ARIA snapshot text
# ---------------------------------------------------------------------------

def _parse_relative_date(text):
    """Convert relative date strings like '3 days ago', '2 weeks ago' to ISO date.

    Returns ISO date string or None if unparsable.
    """
    text = text.lower().strip()
    now = datetime.now()

    m = re.match(r'(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago', text)
    if not m:
        return None

    count = int(m.group(1))
    unit = m.group(2)

    if unit in ('second', 'minute', 'hour'):
        delta = timedelta(hours=count if unit == 'hour' else 0,
                          minutes=count if unit == 'minute' else 0,
                          seconds=count if unit == 'second' else 0)
    elif unit == 'day':
        delta = timedelta(days=count)
    elif unit == 'week':
        delta = timedelta(weeks=count)
    elif unit == 'month':
        delta = timedelta(days=count * 30)
    elif unit == 'year':
        delta = timedelta(days=count * 365)
    else:
        return None

    return (now - delta).strftime('%Y-%m-%d')


def extract_activity_metrics(profile_text):
    """Parse LinkedIn profile/activity ARIA snapshot text for activity metrics.

    The input comes from an ARIA accessibility tree dump, with lines like:
        StaticText "42 posts"
        StaticText "Posted 3 days ago"
        ## Activity
        StaticText "12 comments"

    Returns dict with keys:
        posts_count_30d, engagements_count_30d, last_post_date,
        last_engagement_date, profile_updated
    """
    if not profile_text:
        return {
            'posts_count_30d': 0,
            'engagements_count_30d': 0,
            'last_post_date': None,
            'last_engagement_date': None,
            'profile_updated': 0,
        }

    text = profile_text
    posts_count = 0
    engagements_count = 0
    last_post_date = None
    last_engagement_date = None
    profile_updated = 0

    # --- Post counts ---
    # "42 posts" or "42 Posts" in various ARIA formats
    for m in re.finditer(r'(\d+)\s+[Pp]osts?', text):
        count = int(m.group(1))
        posts_count = max(posts_count, count)

    # "X articles" also count as posts
    for m in re.finditer(r'(\d+)\s+[Aa]rticles?', text):
        count = int(m.group(1))
        posts_count = max(posts_count, posts_count + count)

    # --- Engagement counts ---
    # Comments, reactions, likes
    for m in re.finditer(r'(\d+)\s+[Cc]omments?', text):
        engagements_count += int(m.group(1))
    for m in re.finditer(r'(\d+)\s+[Rr]eactions?', text):
        engagements_count += int(m.group(1))
    for m in re.finditer(r'(\d+)\s+[Ll]ikes?', text):
        engagements_count += int(m.group(1))

    # --- Last post date ---
    # "Posted X days/weeks/months ago"
    post_time_patterns = [
        r'[Pp]osted\s+(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)',
        r'[Ss]hared\s+(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)',
        r'[Pp]ublished\s+(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)',
    ]
    for pat in post_time_patterns:
        m = re.search(pat, text)
        if m:
            parsed = _parse_relative_date(m.group(1))
            if parsed and (last_post_date is None or parsed > last_post_date):
                last_post_date = parsed

    # --- Last engagement date ---
    # "Commented X days ago", "Liked X days ago", "Reacted X days ago"
    engagement_time_patterns = [
        r'[Cc]ommented\s+(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)',
        r'[Ll]iked\s+(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)',
        r'[Rr]eacted\s+(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)',
        r'[Cc]elebrated\s+(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)',
    ]
    for pat in engagement_time_patterns:
        m = re.search(pat, text)
        if m:
            parsed = _parse_relative_date(m.group(1))
            if parsed and (last_engagement_date is None or parsed > last_engagement_date):
                last_engagement_date = parsed

    # If we found a last_post_date but no last_engagement_date, use post date
    if last_post_date and not last_engagement_date:
        last_engagement_date = last_post_date

    # --- Profile updated ---
    # Detect if the profile itself changed (new headline, new photo, etc.)
    profile_update_patterns = [
        r'[Uu]pdated\s+(?:their\s+)?(?:profile|headline|photo|summary|about)',
        r'[Cc]hanged\s+(?:their\s+)?(?:profile|headline|photo|cover)',
        r'[Nn]ew\s+profile\s+(?:photo|picture|image)',
    ]
    for pat in profile_update_patterns:
        if re.search(pat, text):
            profile_updated = 1
            break

    return {
        'posts_count_30d': posts_count,
        'engagements_count_30d': engagements_count,
        'last_post_date': last_post_date,
        'last_engagement_date': last_engagement_date,
        'profile_updated': profile_updated,
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def save_activity_snapshot(conn, person_id, metrics):
    """Store a new activity snapshot for a person.

    Args:
        conn: SQLite connection.
        person_id: ID in tracked_people.
        metrics: Dict from extract_activity_metrics().
    """
    if not metrics:
        return

    now = datetime.now().strftime('%Y-%m-%d')

    # Avoid duplicate snapshots on the same day for the same person
    existing = conn.execute(
        'SELECT 1 FROM activity_snapshots WHERE person_id = ? AND snapshot_date = ?',
        (person_id, now)
    ).fetchone()
    if existing:
        # Update the existing snapshot
        conn.execute('''
            UPDATE activity_snapshots
            SET posts_count_30d = ?, engagements_count_30d = ?,
                last_post_date = ?, last_engagement_date = ?, profile_updated = ?
            WHERE person_id = ? AND snapshot_date = ?
        ''', (
            metrics.get('posts_count_30d', 0),
            metrics.get('engagements_count_30d', 0),
            metrics.get('last_post_date'),
            metrics.get('last_engagement_date'),
            metrics.get('profile_updated', 0),
            person_id, now,
        ))
    else:
        conn.execute('''
            INSERT INTO activity_snapshots
                (person_id, snapshot_date, posts_count_30d, engagements_count_30d,
                 last_post_date, last_engagement_date, profile_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            person_id, now,
            metrics.get('posts_count_30d', 0),
            metrics.get('engagements_count_30d', 0),
            metrics.get('last_post_date'),
            metrics.get('last_engagement_date'),
            metrics.get('profile_updated', 0),
        ))

    conn.commit()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_going_dark(conn, person_id, current_employment_status=None):
    """Check if a person has gone dark based on their activity history.

    Args:
        conn: SQLite connection.
        person_id: ID in tracked_people.
        current_employment_status: Optional string — 'employed', 'left_role',
            'between_roles', or None.

    Returns:
        None if no signal detected, or a dict:
        {
            signal_type: 'going_dark',
            tier: 'high' | 'medium',
            description: str,
        }
    """
    snapshots = get_activity_history(conn, person_id, days=90)

    if len(snapshots) < 3:
        # Need at least 3 data points to establish a baseline and detect a drop
        return None

    # Calculate baseline: average posts_count_30d across all snapshots
    post_counts = [s['posts_count_30d'] for s in snapshots]
    baseline = sum(post_counts) / len(post_counts)

    # Filter out always-inactive people (< 1 post/month ~ roughly < 1 in 30d average)
    if baseline < 1.0:
        return None

    # Sort snapshots by date descending (most recent first)
    sorted_snapshots = sorted(snapshots, key=lambda s: s['snapshot_date'], reverse=True)

    # Check the two most recent snapshots
    recent = sorted_snapshots[:2]
    if len(recent) < 2:
        return None

    threshold = baseline * 0.3
    recent_below_threshold = all(s['posts_count_30d'] < threshold for s in recent)

    if not recent_below_threshold:
        return None

    # Verify the two snapshots span at least ~2 weeks apart
    try:
        date_newest = datetime.strptime(recent[0]['snapshot_date'], '%Y-%m-%d')
        date_older = datetime.strptime(recent[1]['snapshot_date'], '%Y-%m-%d')
        span_days = (date_newest - date_older).days
    except (ValueError, TypeError):
        return None

    if span_days < 10:
        # Snapshots are too close together; could be a brief dip, not a sustained drop
        return None

    # Determine if person was previously very active (>2 posts/week ~ >8 posts/30d)
    was_highly_active = baseline >= 8.0
    completely_silent = all(s['posts_count_30d'] == 0 for s in recent)

    # Determine tier based on employment status
    if current_employment_status in ('left_role', 'between_roles'):
        tier = 'high'
    elif current_employment_status == 'employed':
        tier = 'medium'
    else:
        # Unknown employment status — default to medium
        tier = 'medium'

    # Build description
    avg_recent = sum(s['posts_count_30d'] for s in recent) / len(recent)
    parts = []

    if completely_silent and was_highly_active:
        parts.append(f"Previously active poster (~{baseline:.0f} posts/30d) has gone completely silent")
    elif completely_silent:
        parts.append(f"Activity dropped to zero (baseline was ~{baseline:.0f} posts/30d)")
    else:
        parts.append(
            f"Activity dropped to ~{avg_recent:.0f} posts/30d "
            f"(baseline ~{baseline:.0f}, {avg_recent/baseline*100:.0f}% of normal)"
        )

    if current_employment_status == 'left_role':
        parts.append("recently left their role")
    elif current_employment_status == 'between_roles':
        parts.append("currently between roles")
    elif current_employment_status == 'employed':
        parts.append("still lists corporate role")

    # Check last engagement date
    last_engagement = recent[0].get('last_engagement_date')
    if last_engagement:
        try:
            eng_date = datetime.strptime(last_engagement, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            days_silent = (datetime.now(timezone.utc) - eng_date).days
            if days_silent > 30:
                parts.append(f"no engagement in {days_silent} days")
        except (ValueError, TypeError):
            pass

    description = '; '.join(parts)

    return {
        'signal_type': 'going_dark',
        'tier': tier,
        'description': description,
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_activity_history(conn, person_id, days=90):
    """Get activity snapshots for a person within the given number of days.

    Args:
        conn: SQLite connection.
        person_id: ID in tracked_people.
        days: How many days of history to retrieve (default 90).

    Returns:
        List of dicts with snapshot data, ordered by snapshot_date ascending.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    cursor = conn.execute(
        '''SELECT id, person_id, snapshot_date, posts_count_30d,
                  engagements_count_30d, last_post_date,
                  last_engagement_date, profile_updated
           FROM activity_snapshots
           WHERE person_id = ? AND snapshot_date >= ?
           ORDER BY snapshot_date ASC''',
        (person_id, cutoff)
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
