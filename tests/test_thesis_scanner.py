"""Tests for scripts/thesis_scanner.py — thesis market scanner.

Note: thesis_scanner imports lib.config at module level, which requires
config.yaml. We mock it before importing the module.
"""

import os
import sys
import json
import tempfile
from unittest.mock import MagicMock

# Mock lib.config before importing thesis_scanner
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
mock_config = MagicMock()
mock_config.brave_search_api_key = ""
mock_config.team_phones = {}
sys.modules['lib.config'] = MagicMock(config=mock_config)
sys.modules['lib.whatsapp'] = MagicMock()
sys.modules['lib.brave'] = MagicMock()

from scripts.thesis_scanner import (
    url_hash, load_seen, save_seen, format_digest,
    scan_thesis_area,
)


# ---------------------------------------------------------------------------
# url_hash
# ---------------------------------------------------------------------------

def test_url_hash_deterministic():
    h1 = url_hash("https://example.com/article")
    h2 = url_hash("https://example.com/article")
    assert h1 == h2

def test_url_hash_different():
    h1 = url_hash("https://example.com/a")
    h2 = url_hash("https://example.com/b")
    assert h1 != h2

def test_url_hash_length():
    h = url_hash("https://example.com")
    assert len(h) == 16


# ---------------------------------------------------------------------------
# load_seen / save_seen
# ---------------------------------------------------------------------------

def test_load_seen_missing_file():
    import scripts.thesis_scanner as ts
    old_path = ts.SEEN_PATH
    ts.SEEN_PATH = "/tmp/nonexistent-thesis-seen-12345.json"
    result = load_seen()
    ts.SEEN_PATH = old_path
    assert result == set()

def test_save_and_load_seen():
    import scripts.thesis_scanner as ts
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmp_path = f.name

    old_path = ts.SEEN_PATH
    ts.SEEN_PATH = tmp_path
    try:
        save_seen({'abc123', 'def456'})
        result = load_seen()
        assert 'abc123' in result
        assert 'def456' in result
    finally:
        ts.SEEN_PATH = old_path
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# format_digest
# ---------------------------------------------------------------------------

def test_format_digest_empty():
    msg = format_digest({})
    assert "No new market signals" in msg

def test_format_digest_with_results():
    results = {
        "AI Infrastructure": [
            {"title": "Startup raises $10M for ML infra", "url": "https://example.com/1"},
            {"title": "New GPU platform launches", "url": "https://example.com/2"},
        ],
        "Developer Tools": [],
    }
    msg = format_digest(results)
    assert "AI Infrastructure" in msg
    assert "2 new items" in msg
    assert "ML infra" in msg

def test_format_digest_with_scout_match():
    results = {
        "AI Infrastructure": [
            {
                "title": "Startup raises $10M",
                "url": "https://example.com/1",
                "scout_match": {"id": 1, "name": "John Doe", "linkedin_url": "https://linkedin.com/in/johndoe"},
            },
        ],
    }
    msg = format_digest(results)
    assert "John Doe" in msg

def test_format_digest_caps_per_area():
    results = {
        "AI Infrastructure": [
            {"title": f"Article {i}", "url": f"https://example.com/{i}"}
            for i in range(10)
        ],
    }
    msg = format_digest(results)
    assert "+ 6 more" in msg


# ---------------------------------------------------------------------------
# scan_thesis_area (with mocked brave_search)
# ---------------------------------------------------------------------------

def test_scan_thesis_area_dedup(monkeypatch):
    """Already-seen URLs should be filtered out."""
    fake_results = [
        {"title": "Article 1", "url": "https://example.com/1", "description": "desc1"},
        {"title": "Article 2", "url": "https://example.com/2", "description": "desc2"},
    ]
    monkeypatch.setattr("scripts.thesis_scanner.brave_search", lambda q, count=5: fake_results)

    seen = set()
    area = {"name": "AI Infra", "keywords": ["infrastructure", "MLOps", "GPU"]}

    # First scan: both new
    results1 = scan_thesis_area(area, seen)
    assert len(results1) == 2

    # Second scan: both already seen
    results2 = scan_thesis_area(area, seen)
    assert len(results2) == 0

def test_scan_thesis_area_too_few_keywords():
    area = {"name": "Test", "keywords": ["only_one"]}
    seen = set()
    results = scan_thesis_area(area, seen)
    assert results == []
