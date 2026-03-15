"""Integration tests for Founder Scout — signal → outcome → stats pipeline.

Uses an in-memory SQLite database with the real ScoutDatabase class.
External services (Claude, Brave, LinkedIn) are not called.
"""

import os
import sys
import sqlite3
import tempfile
import unittest

# Ensure repo root on path
REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
SCOUT_DIR = os.path.join(REPO_ROOT, 'skills', 'founder-scout')
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCOUT_DIR)

from scout import ScoutDatabase  # noqa: E402


class TestScoutDatabaseLifecycle(unittest.TestCase):
    """Test the full person → signal → outcome → stats lifecycle."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.db = ScoutDatabase(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_add_person_and_retrieve(self):
        pid = self.db.add_person('Jane Doe', 'https://linkedin.com/in/janedoe', source='test')
        self.assertIsNotNone(pid)
        person = self.db.get_person_by_name('Jane Doe')
        self.assertIsNotNone(person)
        self.assertEqual(person[1], 'Jane Doe')

    def test_add_person_dedup_by_linkedin(self):
        url = 'https://linkedin.com/in/janedoe'
        pid1 = self.db.add_person('Jane Doe', url)
        pid2 = self.db.add_person('Jane Doe', url)  # same URL → INSERT OR IGNORE
        self.assertEqual(pid1, pid2)

    def test_mark_outcome_valid(self):
        pid = self.db.add_person('Alice', 'https://linkedin.com/in/alice')
        self.db.mark_outcome(pid, 'met')
        with self.db._conn() as conn:
            row = conn.execute(
                'SELECT outcome, outcome_at FROM tracked_people WHERE id = ?', (pid,)
            ).fetchone()
        self.assertEqual(row[0], 'met')
        self.assertIsNotNone(row[1])

    def test_mark_outcome_invalid(self):
        pid = self.db.add_person('Bob', 'https://linkedin.com/in/bob')
        with self.assertRaises(ValueError):
            self.db.mark_outcome(pid, 'unknown')

    def test_mark_outcome_overwrite(self):
        pid = self.db.add_person('Carol', 'https://linkedin.com/in/carol')
        self.db.mark_outcome(pid, 'met')
        self.db.mark_outcome(pid, 'invested')
        with self.db._conn() as conn:
            row = conn.execute(
                'SELECT outcome FROM tracked_people WHERE id = ?', (pid,)
            ).fetchone()
        self.assertEqual(row[0], 'invested')

    def test_outcome_stats_empty(self):
        stats = self.db.get_outcome_stats()
        self.assertEqual(stats, {})

    def test_outcome_stats_with_data(self):
        """Add people with different tiers and outcomes, verify precision."""
        # Add 3 people and set their classification + outcome
        with self.db._conn() as conn:
            for name, tier, outcome in [
                ('A', 'HIGH_PRIORITY', 'invested'),
                ('B', 'HIGH_PRIORITY', 'met'),
                ('C', 'HIGH_PRIORITY', 'noise'),
                ('D', 'WATCHING', 'passed'),
                ('E', 'WATCHING', 'noise'),
            ]:
                conn.execute(
                    '''INSERT INTO tracked_people
                       (name, source, added_at, score_classification, outcome, outcome_at)
                       VALUES (?, 'test', datetime('now'), ?, ?, datetime('now'))''',
                    (name, tier, outcome)
                )
            conn.commit()

        stats = self.db.get_outcome_stats()
        self.assertIn('HIGH_PRIORITY', stats)
        self.assertIn('WATCHING', stats)

        hp = stats['HIGH_PRIORITY']
        self.assertEqual(hp['total'], 3)
        self.assertEqual(hp['invested'], 1)
        self.assertEqual(hp['met'], 1)
        self.assertEqual(hp['noise'], 1)
        # precision = (met + invested) / total = 2/3
        self.assertAlmostEqual(hp['precision'], 0.67, places=2)

        w = stats['WATCHING']
        self.assertEqual(w['total'], 2)
        self.assertEqual(w['precision'], 0.0)

    def test_signal_history(self):
        pid = self.db.add_person('Eve', 'https://linkedin.com/in/eve')
        with self.db._conn() as conn:
            conn.execute(
                '''INSERT INTO signal_history
                   (person_id, signal_type, signal_tier, description, detected_at)
                   VALUES (?, 'role_change', 'HIGH', 'Became CTO', datetime('now'))''',
                (pid,)
            )
            conn.commit()
            rows = conn.execute(
                'SELECT signal_type, signal_tier FROM signal_history WHERE person_id = ?', (pid,)
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'role_change')

    def test_profile_sent_tracking(self):
        url = 'https://linkedin.com/in/frank'
        self.assertFalse(self.db.is_profile_sent(url))
        self.db.mark_profiles_sent([{'linkedin_url': url, 'name': 'Frank'}])
        self.assertTrue(self.db.is_profile_sent(url))

    def test_scan_log(self):
        with self.db._conn() as conn:
            conn.execute(
                '''INSERT INTO scan_log (scan_type, started_at, completed_at, queries_run, people_found, signals_detected)
                   VALUES ('daily', datetime('now'), datetime('now'), 5, 3, 2)'''
            )
            conn.commit()
            row = conn.execute('SELECT queries_run, people_found FROM scan_log').fetchone()
        self.assertEqual(row[0], 5)
        self.assertEqual(row[1], 3)


class TestDatabaseMigrations(unittest.TestCase):
    """Test that DB migrations run cleanly on fresh and existing databases."""

    def test_fresh_db_has_all_columns(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        try:
            db = ScoutDatabase(tmp.name)
            with db._conn() as conn:
                cols = [row[1] for row in conn.execute('PRAGMA table_info(tracked_people)').fetchall()]
            for expected in ['outcome', 'outcome_at', 'composite_score', 'score_classification',
                             'hubspot_contact_id', 'approached', 'headline']:
                self.assertIn(expected, cols, f'Missing column: {expected}')
        finally:
            os.unlink(tmp.name)

    def test_double_init_is_idempotent(self):
        """Running _init_db twice should not error."""
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        try:
            db = ScoutDatabase(tmp.name)
            db._init_db()  # second init
            pid = db.add_person('Test', 'https://linkedin.com/in/test')
            self.assertIsNotNone(pid)
        finally:
            os.unlink(tmp.name)


if __name__ == '__main__':
    unittest.main()
