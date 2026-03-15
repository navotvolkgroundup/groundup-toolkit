"""Shared fixtures for founder-scout tests."""

import sys
import os
import sqlite3
import pytest

# Ensure the founder-scout package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture
def db():
    """In-memory SQLite database with all tables initialized."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row

    # Import and init all tables
    from modules.going_dark import init_activity_tables
    from modules.registrar import init_registrar_tables
    from modules.retention_clock import init_retention_tables
    from modules.domain_monitor import init_domain_tables
    from modules.event_tracker import init_event_tables
    from modules.scoring import init_score_tables

    init_activity_tables(conn)
    init_registrar_tables(conn)
    init_retention_tables(conn)
    init_domain_tables(conn)
    init_event_tables(conn)
    init_score_tables(conn)

    # Create tracked_people table (referenced by scoring)
    conn.execute('''CREATE TABLE IF NOT EXISTS tracked_people (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        notes TEXT
    )''')
    conn.commit()

    yield conn
    conn.close()
