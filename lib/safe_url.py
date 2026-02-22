"""
Centralized SSRF protection for URL fetching.

Provides domain allowlist validation with DNS rebinding protection
and multi-hop redirect following. Used by deal-analyzer, deck-analyzer,
and email-to-deal-automation.
"""
import ipaddress
import socket
from urllib.parse import urlparse

# Allowed URL domains for deck/document fetching
ALLOWED_DECK_DOMAINS = {
    'docsend.com', 'docs.google.com', 'drive.google.com',
    'www.dropbox.com', 'dropbox.com', 'papermark.com', 'www.papermark.com',
    'pitch.com', 'www.pitch.com', 'slides.com', 'www.slides.com',
    'canva.com', 'www.canva.com',
}

MAX_REDIRECTS = 5


def is_safe_url(url, allowed_domains=None):
    """Validate URL against allowed domains to prevent SSRF.

    Checks:
      1. Scheme is http or https
      2. Hostname matches an allowed domain (exact or subdomain)
      3. All resolved IPs are public (not private/loopback/reserved/link-local)
    """
    if allowed_domains is None:
        allowed_domains = ALLOWED_DECK_DOMAINS
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname or ''
        if not hostname:
            return False

        if not any(hostname == d or hostname.endswith('.' + d) for d in allowed_domains):
            return False

        # Resolve hostname and verify all IPs are public (prevents DNS rebinding)
        try:
            addrinfos = socket.getaddrinfo(hostname, None)
            for family, _, _, _, sockaddr in addrinfos:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                    return False
        except (socket.gaierror, ValueError):
            return False

        return True
    except Exception:
        return False


def safe_request(url, session=None, allowed_domains=None, **kwargs):
    """Fetch a URL with SSRF protection and safe redirect following.

    Validates each redirect hop against the domain allowlist.
    Returns the final requests.Response or None on security failure.
    """
    import requests as _requests
    if session is None:
        session = _requests

    kwargs.setdefault('timeout', 30)
    kwargs['allow_redirects'] = False

    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        if not is_safe_url(current_url, allowed_domains):
            import sys
            print(f"  Security: blocked request to disallowed URL: {current_url}", file=sys.stderr)
            return None

        response = session.get(current_url, **kwargs)

        if response.status_code not in (301, 302, 303, 307, 308):
            return response

        redirect_url = response.headers.get('Location', '')
        if not redirect_url:
            return response
        current_url = redirect_url

    import sys
    print(f"  Security: too many redirects for URL: {url}", file=sys.stderr)
    return None
