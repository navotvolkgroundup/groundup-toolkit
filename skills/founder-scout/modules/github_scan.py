"""GitHub activity scanning — detect new repos, orgs, and activity spikes."""

import os
import re
import logging
import requests
from datetime import datetime, timedelta

log = logging.getLogger("founder-scout")

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')  # Optional, for higher rate limits


def _github_headers():
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'GroundUp-FounderScout'}
    if GITHUB_TOKEN:
        headers['Authorization'] = f'Bearer {GITHUB_TOKEN}'
    return headers


def github_username_from_url(url):
    """Extract GitHub username from a URL like https://github.com/username."""
    if not url:
        return None
    m = re.match(r'https?://github\.com/([A-Za-z0-9_-]+)/?$', url.strip())
    return m.group(1) if m else None


def github_fetch_events(username, max_pages=2):
    """Fetch recent public events for a GitHub user."""
    events = []
    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(
                f"{GITHUB_API_BASE}/users/{username}/events/public?per_page=100&page={page}",
                headers=_github_headers(), timeout=10
            )
            if resp.status_code == 404:
                log.warning("GitHub user %s: not found", username)
                return []
            if resp.status_code == 403:
                log.warning("GitHub API rate limited")
                return events
            if resp.status_code != 200:
                log.error("GitHub API error: %d", resp.status_code)
                return events
            page_events = resp.json()
            if not page_events:
                break
            events.extend(page_events)
        except Exception as e:
            log.error("GitHub fetch error: %s", e)
            break
    return events


def github_fetch_repos(username, sort='created', per_page=10):
    """Fetch recent repos for a GitHub user, sorted by creation date."""
    try:
        resp = requests.get(
            f"{GITHUB_API_BASE}/users/{username}/repos?sort={sort}&direction=desc&per_page={per_page}&type=owner",
            headers=_github_headers(), timeout=10
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def github_fetch_orgs(username):
    """Fetch public organizations for a GitHub user."""
    try:
        resp = requests.get(
            f"{GITHUB_API_BASE}/users/{username}/orgs",
            headers=_github_headers(), timeout=10
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def analyze_github_activity(username, person_name, last_scanned=None):
    """
    Analyze a GitHub user's recent activity for startup signals.

    Returns list of signals: [{"type": "...", "tier": "high|medium|low", "description": "...", "url": "..."}]
    """
    signals = []
    cutoff = datetime.fromisoformat(last_scanned) if last_scanned else datetime.now() - timedelta(days=30)

    # 1. Check for new repos (strongest signal)
    repos = github_fetch_repos(username, sort='created', per_page=20)
    new_repos = []
    for repo in repos:
        created = datetime.fromisoformat(repo['created_at'].replace('Z', '+00:00')).replace(tzinfo=None)
        if created > cutoff and not repo.get('fork'):
            new_repos.append(repo)

    for repo in new_repos:
        name = repo['name']
        desc = repo.get('description') or ''
        lang = repo.get('language') or ''
        stars = repo.get('stargazers_count', 0)
        has_pages = repo.get('has_pages', False)
        homepage = repo.get('homepage') or ''
        repo_url = repo['html_url']

        # Score the repo — is this a product/startup or just a personal project?
        is_product = False
        product_hints = ['landing', 'website', 'app', 'platform', 'api', 'sdk', 'saas', 'demo']
        if any(h in name.lower() or h in desc.lower() for h in product_hints):
            is_product = True
        if has_pages or (homepage and 'github.io' not in homepage):
            is_product = True
        if stars >= 5:
            is_product = True

        # High tier: product-looking repo with description or custom domain
        if is_product and (desc or homepage):
            tier = 'high'
            description = f"New repo '{name}'"
            if desc:
                description += f": {desc[:100]}"
            if homepage:
                description += f" ({homepage})"
            signals.append({'type': 'github_new_repo', 'tier': tier, 'description': description, 'url': repo_url})
        elif desc or lang:
            tier = 'medium'
            description = f"New repo '{name}'"
            if desc:
                description += f": {desc[:100]}"
            elif lang:
                description += f" ({lang})"
            signals.append({'type': 'github_new_repo', 'tier': tier, 'description': description, 'url': repo_url})
        else:
            # Bare repo, low signal
            signals.append({'type': 'github_new_repo', 'tier': 'low', 'description': f"New repo '{name}'", 'url': repo_url})

    # 2. Check for new organizations (strong signal — might be a new company)
    orgs = github_fetch_orgs(username)
    for org in orgs:
        org_url = f"https://github.com/{org['login']}"
        # We can't easily tell when they joined, so check org creation date
        try:
            org_resp = requests.get(
                f"{GITHUB_API_BASE}/orgs/{org['login']}",
                headers=_github_headers(), timeout=10
            )
            if org_resp.status_code == 200:
                org_data = org_resp.json()
                created = datetime.fromisoformat(org_data['created_at'].replace('Z', '+00:00')).replace(tzinfo=None)
                if created > cutoff:
                    desc = org_data.get('description') or org_data.get('name', org['login'])
                    signals.append({
                        'type': 'github_new_org',
                        'tier': 'high',
                        'description': f"New GitHub org '{org['login']}': {desc[:100]}",
                        'url': org_url,
                    })
        except Exception:
            pass

    # 3. Detect activity spikes from events
    events = github_fetch_events(username, max_pages=1)
    recent_events = [
        e for e in events
        if datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')).replace(tzinfo=None) > cutoff
    ]

    if len(recent_events) >= 30:
        # Activity spike — 30+ events since last scan
        event_types = {}
        for e in recent_events:
            event_types[e['type']] = event_types.get(e['type'], 0) + 1
        top_types = sorted(event_types.items(), key=lambda x: -x[1])[:3]
        summary = ', '.join(f"{count} {t.replace('Event','')}" for t, count in top_types)
        signals.append({
            'type': 'github_activity_spike',
            'tier': 'medium',
            'description': f"GitHub activity spike: {len(recent_events)} events ({summary})",
            'url': f"https://github.com/{username}",
        })

    return signals
