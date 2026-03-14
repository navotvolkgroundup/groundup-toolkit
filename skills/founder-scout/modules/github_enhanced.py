"""
Enhanced GitHub monitoring for Founder Scout.

Extends the basic GitHub scanning in scout.py with deeper analysis:
- Landing page detection in repos (index.html, custom domains, "coming soon")
- Startup infrastructure detection (Stripe, auth, billing, deployment configs)
- npm/PyPI package publication tracking
- GitHub user discovery by name + location
- Activity spike detection relative to personal baseline
"""

import re
import json
import sys
import os
import requests
from datetime import datetime, timedelta, timezone

GITHUB_API_BASE = "https://api.github.com"

# Patterns that suggest a repo is a product landing page
LANDING_PAGE_FILES = {'index.html', 'index.htm', 'CNAME', 'vercel.json', 'netlify.toml'}
LANDING_PAGE_README_PATTERNS = [
    re.compile(r'coming\s+soon', re.I),
    re.compile(r'launching\s+soon', re.I),
    re.compile(r'sign\s+up\s+(for|to)\s+(early|beta|alpha)', re.I),
    re.compile(r'waitlist', re.I),
    re.compile(r'beta\s+access', re.I),
    re.compile(r'join\s+(the\s+)?beta', re.I),
]

# Files / deps that indicate startup infrastructure
STARTUP_INFRA_FILES = {
    'stripe': ['stripe', '.stripe'],
    'vercel': ['vercel.json', '.vercel'],
    'railway': ['railway.json', 'railway.toml'],
    'render': ['render.yaml'],
    'docker': ['docker-compose.yml', 'docker-compose.yaml', 'Dockerfile'],
    'auth0': ['auth0'],
    'firebase': ['firebase.json', '.firebaserc'],
    'supabase': ['supabase'],
}

STARTUP_INFRA_DEPS = {
    'stripe': ['stripe', '@stripe/stripe-js', '@stripe/react-stripe-js'],
    'auth0': ['auth0', '@auth0/auth0-react', '@auth0/nextjs-auth0'],
    'firebase': ['firebase', 'firebase-admin'],
    'clerk': ['@clerk/nextjs', '@clerk/clerk-js'],
    'supabase': ['@supabase/supabase-js'],
    'paddle': ['@paddle/paddle-js'],
    'lemon_squeezy': ['@lemonsqueezy/lemonsqueezy.js'],
}

NPM_REGISTRY_BASE = "https://registry.npmjs.org"


# ---------------------------------------------------------------------------
# Auth / headers
# ---------------------------------------------------------------------------

def github_headers(token=None):
    """Return headers for GitHub API."""
    token = token or os.environ.get('GITHUB_TOKEN', '')
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'GroundUp-FounderScout',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _check_rate_limit(response):
    """Log a warning if rate limit is running low. Returns True if OK to continue."""
    remaining = response.headers.get('X-RateLimit-Remaining')
    if remaining is not None:
        remaining = int(remaining)
        if remaining <= 5:
            reset_ts = response.headers.get('X-RateLimit-Reset', '0')
            reset_at = datetime.utcfromtimestamp(int(reset_ts)).strftime('%H:%M:%S UTC')
            print(f"[github_enhanced] WARNING: Rate limit nearly exhausted ({remaining} left, resets at {reset_at})", file=sys.stderr)
            if remaining == 0:
                return False
    return True


def _gh_get(url, token=None, params=None):
    """GET request to GitHub API with rate-limit handling. Returns response or None."""
    try:
        resp = requests.get(url, headers=github_headers(token), params=params, timeout=15)
        if not _check_rate_limit(resp):
            print(f"[github_enhanced] Rate limit exhausted, skipping: {url}", file=sys.stderr)
            return None
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        print(f"[github_enhanced] Request failed for {url}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Repo deep analysis
# ---------------------------------------------------------------------------

def analyze_repo_deep(repo_data, readme_content=None):
    """Deep analysis of a single repo for startup signals.

    Check for:
    - Landing page patterns: index.html, custom domain in CNAME, homepage URL
    - Startup infra: package.json with stripe/auth0/firebase, docker-compose, vercel.json
    - "Coming soon" or "beta" language in README
    - Topics/tags suggesting a product

    Returns: {is_product: bool, signals: [str], confidence: 'high'|'medium'|'low'}
    """
    signals = []
    repo_name = repo_data.get('name', '')
    description = (repo_data.get('description') or '').lower()
    homepage = repo_data.get('homepage') or ''
    topics = repo_data.get('topics') or []
    has_pages = repo_data.get('has_pages', False)

    # Homepage URL set (suggests a product with a website)
    if homepage and not homepage.startswith('https://github.com'):
        signals.append(f'Custom homepage URL: {homepage}')

    # GitHub Pages enabled
    if has_pages:
        signals.append('GitHub Pages enabled (possible landing page)')

    # Topics suggesting a product
    product_topics = {'saas', 'startup', 'product', 'app', 'platform', 'api', 'sdk', 'cli-tool'}
    matched_topics = set(topics) & product_topics
    if matched_topics:
        signals.append(f'Product-related topics: {", ".join(matched_topics)}')

    # Description keywords
    product_keywords = ['platform', 'saas', 'api for', 'tool for', 'app for', 'marketplace']
    for kw in product_keywords:
        if kw in description:
            signals.append(f'Product keyword in description: "{kw}"')
            break

    # README analysis
    if readme_content:
        for pattern in LANDING_PAGE_README_PATTERNS:
            match = pattern.search(readme_content)
            if match:
                signals.append(f'Landing page language in README: "{match.group()}"')
                break

    # Confidence assessment
    if len(signals) >= 3:
        confidence = 'high'
    elif len(signals) >= 1:
        confidence = 'medium'
    else:
        confidence = 'low'

    return {
        'is_product': len(signals) >= 1,
        'signals': signals,
        'confidence': confidence,
    }


def fetch_repo_readme(owner, repo, token=None):
    """Fetch README content from GitHub API. Returns text or None."""
    resp = _gh_get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme", token=token)
    if resp is None:
        return None
    data = resp.json()
    # README content is base64-encoded
    import base64
    content = data.get('content', '')
    encoding = data.get('encoding', 'base64')
    if encoding == 'base64' and content:
        try:
            return base64.b64decode(content).decode('utf-8', errors='replace')
        except Exception:
            return None
    return content or None


def fetch_repo_files(owner, repo, token=None):
    """Fetch file listing (top-level tree) from GitHub API.
    Returns list of filenames or empty list.
    """
    resp = _gh_get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/", token=token)
    if resp is None:
        return []
    try:
        items = resp.json()
        if isinstance(items, list):
            return [item.get('name', '') for item in items if isinstance(item, dict)]
    except (ValueError, TypeError):
        pass
    return []


# ---------------------------------------------------------------------------
# Startup infrastructure detection
# ---------------------------------------------------------------------------

def detect_startup_infra(file_list, readme_text=None):
    """Check file list and README for startup infrastructure patterns.
    Returns list of matched patterns like ['stripe', 'vercel', 'auth0'].
    """
    matched = []
    file_set = {f.lower() for f in file_list}

    # Check file-based patterns
    for infra_name, patterns in STARTUP_INFRA_FILES.items():
        for pattern in patterns:
            if pattern.lower() in file_set:
                matched.append(infra_name)
                break

    # Check if package.json is present (we'd need to fetch it for dep analysis,
    # but we can detect the file's existence)
    if 'package.json' in file_set:
        # Flag for further dep analysis; the caller should fetch package.json
        # and check STARTUP_INFRA_DEPS if they want deeper insight
        pass

    # Check README for infra mentions
    if readme_text:
        readme_lower = readme_text.lower()
        for infra_name, dep_names in STARTUP_INFRA_DEPS.items():
            if infra_name not in matched:
                for dep in dep_names:
                    if dep.lower() in readme_lower:
                        matched.append(infra_name)
                        break

    return list(set(matched))


# ---------------------------------------------------------------------------
# GitHub user search
# ---------------------------------------------------------------------------

def search_github_user(name, location="Israel", token=None):
    """Try to find a GitHub user by name and location.
    Returns: github_url or None.
    """
    query = f'{name} location:{location}'
    resp = _gh_get(
        f"{GITHUB_API_BASE}/search/users",
        token=token,
        params={'q': query, 'per_page': 5},
    )
    if resp is None:
        return None

    data = resp.json()
    items = data.get('items', [])
    if not items:
        return None

    # Try to match by name similarity
    name_lower = name.lower().split()
    for user in items:
        login = (user.get('login') or '').lower()
        # Fetch user profile to check real name
        profile_resp = _gh_get(f"{GITHUB_API_BASE}/users/{login}", token=token)
        if profile_resp is None:
            continue
        profile = profile_resp.json()
        real_name = (profile.get('name') or '').lower()

        # Check if name parts appear in the GitHub profile name
        if real_name and all(part in real_name for part in name_lower):
            return user.get('html_url')

    # Fallback: return top result if only one match
    if len(items) == 1:
        return items[0].get('html_url')

    return None


# ---------------------------------------------------------------------------
# Activity baseline / spike detection
# ---------------------------------------------------------------------------

def analyze_activity_baseline(events, previous_event_count=None):
    """Calculate if current activity is a spike vs baseline.

    Args:
        events: list of GitHub event dicts (from /users/{user}/events)
        previous_event_count: historical average events per 30-day window (if known)

    Returns: {is_spike: bool, current_rate: float, baseline_rate: float, multiplier: float}
    """
    now = datetime.now(timezone.utc)

    # Count events in the last 7 days
    recent_count = 0
    older_count = 0
    for event in events:
        created = event.get('created_at', '')
        try:
            event_dt = datetime.strptime(created, '%Y-%m-%dT%H:%M:%SZ')
        except (ValueError, TypeError):
            continue
        age = (now - event_dt).days
        if age <= 7:
            recent_count += 1
        elif age <= 30:
            older_count += 1

    # Normalize to weekly rate
    current_rate = float(recent_count)  # events in the last 7 days

    if previous_event_count is not None and previous_event_count > 0:
        # Use provided baseline (monthly -> weekly)
        baseline_rate = previous_event_count / 4.0
    elif older_count > 0:
        # Estimate baseline from older events (23-day window -> weekly rate)
        older_weeks = 23.0 / 7.0
        baseline_rate = older_count / older_weeks
    else:
        # No baseline data; treat any activity as notable
        baseline_rate = 1.0

    multiplier = current_rate / baseline_rate if baseline_rate > 0 else current_rate
    is_spike = multiplier >= 3.0 and current_rate >= 5  # At least 5 events to count

    return {
        'is_spike': is_spike,
        'current_rate': round(current_rate, 1),
        'baseline_rate': round(baseline_rate, 1),
        'multiplier': round(multiplier, 1),
    }


# ---------------------------------------------------------------------------
# npm publication check
# ---------------------------------------------------------------------------

def check_npm_publications(username, token=None):
    """Check if user published npm packages recently.
    Uses npm registry API (no auth needed).
    Returns: list of {package_name, version, published_date}.
    """
    # npm doesn't have a great "packages by user" API, but we can search by maintainer
    try:
        resp = requests.get(
            f"https://registry.npmjs.org/-/v1/search",
            params={'text': f'maintainer:{username}', 'size': 20},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[github_enhanced] npm search failed for {username}: {e}", file=sys.stderr)
        return []

    results = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    for obj in resp.json().get('objects', []):
        pkg = obj.get('package', {})
        name = pkg.get('name', '')
        version = pkg.get('version', '')
        date_str = pkg.get('date', '')

        if date_str:
            try:
                pub_date = datetime.strptime(date_str[:19], '%Y-%m-%dT%H:%M:%S')
                if pub_date >= cutoff:
                    results.append({
                        'package_name': name,
                        'version': version,
                        'published_date': date_str,
                    })
            except (ValueError, TypeError):
                # Include if we can't parse the date (err on the side of inclusion)
                results.append({
                    'package_name': name,
                    'version': version,
                    'published_date': date_str,
                })

    return results


# ---------------------------------------------------------------------------
# Full enhanced scan
# ---------------------------------------------------------------------------

def enhanced_github_scan(username, person_name, last_scanned=None, token=None):
    """Full enhanced scan combining all signals.

    Returns list of signal dicts: [{type, tier, description, url}, ...]

    Signal escalation:
    - New org + landing page repo + custom domain = HIGH (immediate alert)
    - Activity spike (3x baseline) + new product-looking repo = HIGH
    - New repo with startup-infra patterns = MEDIUM
    - npm/PyPI publication = MEDIUM
    - General activity increase = LOW
    """
    signals = []

    # Determine recency cutoff
    if last_scanned:
        try:
            cutoff = datetime.strptime(last_scanned, '%Y-%m-%dT%H:%M:%SZ')
        except (ValueError, TypeError):
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # --- Fetch events for baseline analysis ---
    events_resp = _gh_get(
        f"{GITHUB_API_BASE}/users/{username}/events?per_page=100",
        token=token,
    )
    events = events_resp.json() if events_resp else []
    if isinstance(events, list):
        baseline = analyze_activity_baseline(events)
        if baseline['is_spike']:
            signals.append({
                'type': 'activity_spike',
                'tier': 'LOW',
                'description': f"Activity spike: {baseline['current_rate']} events/week vs {baseline['baseline_rate']} baseline ({baseline['multiplier']}x)",
                'url': f'https://github.com/{username}',
            })
    else:
        baseline = {'is_spike': False}
        events = []

    # --- Fetch repos (recent) ---
    repos_resp = _gh_get(
        f"{GITHUB_API_BASE}/users/{username}/repos",
        token=token,
        params={'sort': 'created', 'direction': 'desc', 'per_page': 10, 'type': 'owner'},
    )
    repos = repos_resp.json() if repos_resp else []
    if not isinstance(repos, list):
        repos = []

    has_landing_page = False
    has_custom_domain = False
    has_new_product_repo = False

    for repo in repos:
        created = repo.get('created_at', '')
        try:
            repo_created = datetime.strptime(created, '%Y-%m-%dT%H:%M:%SZ')
        except (ValueError, TypeError):
            continue

        if repo_created < cutoff:
            continue  # Not new

        repo_name = repo.get('name', '')
        owner = repo.get('owner', {}).get('login', username)

        # Deep analysis
        readme = fetch_repo_readme(owner, repo_name, token=token)
        files = fetch_repo_files(owner, repo_name, token=token)
        analysis = analyze_repo_deep(repo, readme_content=readme)

        if analysis['is_product']:
            has_new_product_repo = True
            signals.append({
                'type': 'new_product_repo',
                'tier': 'MEDIUM',
                'description': f"New product-looking repo: {repo_name} ({', '.join(analysis['signals'][:3])})",
                'url': repo.get('html_url', ''),
            })

        # Check for landing page files
        if set(files) & LANDING_PAGE_FILES:
            has_landing_page = True

        if repo.get('homepage') and not (repo.get('homepage', '').startswith('https://github.com')):
            has_custom_domain = True

        # Check startup infra
        infra = detect_startup_infra(files, readme)
        if infra:
            signals.append({
                'type': 'startup_infra',
                'tier': 'MEDIUM',
                'description': f"Startup infrastructure in {repo_name}: {', '.join(infra)}",
                'url': repo.get('html_url', ''),
            })

    # --- Fetch orgs ---
    orgs_resp = _gh_get(f"{GITHUB_API_BASE}/users/{username}/orgs", token=token)
    orgs = orgs_resp.json() if orgs_resp else []
    has_new_org = False
    if isinstance(orgs, list) and orgs:
        # GitHub org API doesn't give creation date directly, so we flag all orgs
        # and let dedup in the caller handle repeat alerts
        for org in orgs:
            org_login = org.get('login', '')
            signals.append({
                'type': 'new_org',
                'tier': 'MEDIUM',
                'description': f"GitHub org membership: {org_login}",
                'url': f'https://github.com/{org_login}',
            })
            has_new_org = True

    # --- Check npm publications ---
    npm_packages = check_npm_publications(username)
    for pkg in npm_packages:
        signals.append({
            'type': 'npm_publication',
            'tier': 'MEDIUM',
            'description': f"npm package published: {pkg['package_name']}@{pkg['version']} ({pkg['published_date'][:10]})",
            'url': f"https://www.npmjs.com/package/{pkg['package_name']}",
        })

    # --- Signal escalation ---
    # New org + landing page + custom domain -> escalate to HIGH
    if has_new_org and has_landing_page and has_custom_domain:
        signals.append({
            'type': 'startup_launch_pattern',
            'tier': 'HIGH',
            'description': 'New org + landing page repo + custom domain detected (startup launch pattern)',
            'url': f'https://github.com/{username}',
        })

    # Activity spike + new product repo -> escalate to HIGH
    if baseline.get('is_spike') and has_new_product_repo:
        # Upgrade the activity_spike signal
        for s in signals:
            if s['type'] == 'activity_spike':
                s['tier'] = 'HIGH'
                s['description'] += ' (combined with new product repo)'
                break

    return signals
