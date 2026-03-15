"""Tests for modules/domain_monitor.py — domain registration detection."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.domain_monitor import (
    _normalize_name, generate_candidate_domains, scan_github_domains,
)


# ---------------------------------------------------------------------------
# _normalize_name()
# ---------------------------------------------------------------------------

def test_normalize_basic():
    assert _normalize_name('John Smith') == ('john', 'smith')

def test_normalize_middle_name():
    assert _normalize_name('John Michael Smith') == ('john', 'smith')

def test_normalize_single_name():
    assert _normalize_name('Madonna') is None

def test_normalize_none():
    assert _normalize_name(None) is None
    assert _normalize_name('') is None
    assert _normalize_name('  ') is None

def test_normalize_strips_non_alpha():
    result = _normalize_name('Dr. Jean-Pierre Dupont')
    # "dr" is 2 chars, kept. "jeanpierre" after strip. "dupont"
    assert result is not None
    assert result[1] == 'dupont'


# ---------------------------------------------------------------------------
# generate_candidate_domains()
# ---------------------------------------------------------------------------

def test_generate_domains():
    domains = generate_candidate_domains('John Smith')
    assert len(domains) > 0
    assert 'johnsmith.com' in domains
    assert 'smithjohn.com' in domains
    assert 'smith.io' in domains
    assert 'smithai.com' in domains

def test_generate_domains_empty():
    assert generate_candidate_domains('') == []
    assert generate_candidate_domains('SingleName') == []

def test_generate_domains_no_duplicates():
    domains = generate_candidate_domains('Test Person')
    assert len(domains) == len(set(domains))


# ---------------------------------------------------------------------------
# scan_github_domains()
# ---------------------------------------------------------------------------

def test_scan_homepage_domain():
    repos = [{'name': 'my-startup', 'homepage': 'https://mystartup.io', 'description': ''}]
    results = scan_github_domains(repos)
    assert len(results) == 1
    assert results[0]['domain'] == 'mystartup.io'
    assert results[0]['source_field'] == 'homepage'

def test_scan_skips_github_io():
    repos = [{'name': 'docs', 'homepage': 'https://user.github.io', 'description': ''}]
    results = scan_github_domains(repos)
    assert len(results) == 0

def test_scan_description_domain():
    repos = [{'name': 'app', 'homepage': '', 'description': 'Check out acme.ai for details'}]
    results = scan_github_domains(repos)
    assert any(r['domain'] == 'acme.ai' for r in results)

def test_scan_empty():
    assert scan_github_domains([]) == []
    assert scan_github_domains(None) == []

def test_scan_deduplicates():
    repos = [
        {'name': 'repo1', 'homepage': 'https://acme.io', 'description': ''},
        {'name': 'repo2', 'homepage': 'https://acme.io', 'description': ''},
    ]
    results = scan_github_domains(repos)
    assert len(results) == 1
