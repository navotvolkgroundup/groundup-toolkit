"""
gws — Shared helper for Google Workspace operations via gws-auth CLI.

Drop-in replacement for gog CLI wrappers used across GroundUp toolkit scripts.
All functions shell out to `gws-auth` and return parsed JSON.

Usage:
    from lib.gws import gws_gmail_send, gws_gmail_search, gws_gmail_thread_get, ...
"""

import os
import sys
import json
import subprocess
import tempfile
import base64
import re

# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_gws(resource, params=None, body=None, timeout=30):
    """Run a gws-auth command and return parsed JSON (or None on error).

    Args:
        resource: The gws-auth resource path, e.g. "gmail users threads list"
        params: Dict of query/path parameters (passed via --params)
        body: Dict of request body (passed via --json)
        timeout: Command timeout in seconds
    """
    # Security: use list-based subprocess to prevent shell injection
    cmd = ['gws-auth'] + resource.split()
    if params:
        cmd += ['--params', json.dumps(params)]
    if body:
        cmd += ['--json', json.dumps(body)]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                print(f"  gws-auth error: {stderr[:300]}", file=sys.stderr)
            return None

        stdout = result.stdout.strip()
        if not stdout:
            return {}
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        print(f"  gws-auth JSON parse error: {e}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"  gws-auth timeout ({timeout}s): {resource}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  gws-auth exception: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Label ID resolution (Gmail custom labels need IDs, not names)
# ---------------------------------------------------------------------------

_label_cache = {}  # name -> id


def _ensure_label_cache():
    """Fetch Gmail labels once and cache name→ID mapping."""
    global _label_cache
    if _label_cache:
        return
    result = run_gws("gmail users labels list", params={"userId": "me"})
    if result and "labels" in result:
        for label in result["labels"]:
            _label_cache[label["name"]] = label["id"]


def resolve_label_id(name):
    """Resolve a Gmail label name to its ID. System labels (INBOX, UNREAD, etc.) map to themselves."""
    # System labels have matching name/id
    system_labels = {"INBOX", "UNREAD", "SPAM", "TRASH", "SENT", "DRAFT",
                     "STARRED", "IMPORTANT", "CATEGORY_PERSONAL",
                     "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS",
                     "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
    if name in system_labels:
        return name
    _ensure_label_cache()
    return _label_cache.get(name, name)


def resolve_label_ids(names):
    """Resolve a list of label names to IDs."""
    return [resolve_label_id(n) for n in names]


# ---------------------------------------------------------------------------
# Gmail operations
# ---------------------------------------------------------------------------

def gws_gmail_search(query, max_results=50):
    """Search Gmail threads. Returns list of thread dicts with {id, snippet, historyId}.

    Equivalent to: gog gmail search "query" --limit N --json
    """
    result = run_gws("gmail users threads list", params={
        "userId": "me",
        "q": query,
        "maxResults": max_results,
    })
    if result is None:
        return []
    return result.get("threads") or []


def gws_gmail_thread_get(thread_id, fmt=None):
    """Get a Gmail thread by ID. Returns thread dict with messages[].

    Equivalent to: gog gmail thread get "threadId" --json
    fmt: "full", "metadata", "minimal" (default: API default which is "full")
    """
    params = {"userId": "me", "id": thread_id}
    if fmt:
        params["format"] = fmt
    return run_gws("gmail users threads get", params=params)


def gws_gmail_modify(thread_id, add_labels=None, remove_labels=None):
    """Modify Gmail thread labels.

    Equivalent to: gog gmail thread modify "threadId" --add "Label" --remove "UNREAD" --force
    Label names are automatically resolved to IDs.
    """
    body = {}
    if add_labels:
        body["addLabelIds"] = resolve_label_ids(add_labels)
    if remove_labels:
        body["removeLabelIds"] = resolve_label_ids(remove_labels)

    return run_gws(
        "gmail users threads modify",
        params={"userId": "me", "id": thread_id},
        body=body,
    )


def gws_gmail_send(to, subject, body_text, thread_id=None, bcc=None):
    """Send an email via gws-auth.

    For simple sends (no thread_id, no bcc): uses gws-auth gmail +send helper.
    For replies or BCC: builds RFC 2822 message and sends via raw API.

    Equivalent to: gog gmail send --to X --subject Y --body Z [--thread-id T]
    """
    if not thread_id and not bcc:
        return _gws_send_simple(to, subject, body_text)
    else:
        return _gws_send_raw(to, subject, body_text, thread_id=thread_id, bcc=bcc)


def _gws_send_simple(to, subject, body_text):
    """Send email using gws-auth gmail +send helper.

    Note: +send only supports --to, --subject, --body (no --body-file).
    For bodies > 100KB, falls back to raw RFC 2822 API.
    """
    # For very large bodies, go straight to raw API
    if len(body_text) > 100000:
        return _gws_send_raw(to, subject, body_text)

    # Write body to temp file, then pass via --body arg
    fd, body_file = tempfile.mkstemp(suffix='.txt', prefix='gws-send-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(body_text)

        # Security: use list-based subprocess to prevent shell injection
        with open(body_file, 'r') as bf:
            body_content = bf.read()
        cmd = ['gws-auth', 'gmail', '+send', '--to', to, '--subject', subject, '--body', body_content]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            # Fallback to raw RFC 2822 API
            return _gws_send_raw(to, subject, body_text)

        return True
    except Exception as e:
        print(f"  gws email send error: {e}", file=sys.stderr)
        return False
    finally:
        try:
            os.unlink(body_file)
        except OSError:
            pass


def _gws_send_raw(to, subject, body_text, thread_id=None, bcc=None):
    """Send email via raw RFC 2822 message."""
    headers = [
        f"To: {to}",
        f"Subject: {subject}",
        "Content-Type: text/plain; charset=UTF-8",
    ]
    if bcc:
        if isinstance(bcc, list):
            bcc = ", ".join(bcc)
        headers.append(f"Bcc: {bcc}")

    raw_message = "\r\n".join(headers) + "\r\n\r\n" + body_text
    raw_b64 = base64.urlsafe_b64encode(raw_message.encode("utf-8")).decode("ascii")

    send_body = {"raw": raw_b64}
    if thread_id:
        send_body["threadId"] = thread_id

    result = run_gws(
        "gmail users messages send",
        params={"userId": "me"},
        body=send_body,
    )
    return result is not None


def gws_gmail_send_bodyfile(to, subject, body_file):
    """Send email using a file for the body content.

    Equivalent to: gog gmail send --to X --subject Y --body-file F
    """
    try:
        with open(body_file, 'r') as f:
            body_text = f.read()
        return gws_gmail_send(to, subject, body_text)
    except Exception as e:
        print(f"  Failed to read body file {body_file}: {e}", file=sys.stderr)
        return False


def gws_gmail_attachment_download(message_id, attachment_id, out_path):
    """Download a Gmail attachment and save to file.

    Uses gws-auth --output flag to write directly to disk,
    avoiding stdout maxBuffer issues with large attachments.
    """
    cmd = [
        'gws-auth', 'gmail', 'users', 'messages', 'attachments', 'get',
        '--params', json.dumps({
            "userId": "me",
            "messageId": message_id,
            "id": attachment_id,
        }),
        '--output', out_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(f"  gws-auth attachment download error: {stderr[:300]}", file=sys.stderr)
            return False
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except subprocess.TimeoutExpired:
        print(f"  Attachment download timeout (60s)", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  Attachment download error: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Calendar operations
# ---------------------------------------------------------------------------

def gws_calendar_events(calendar_id, time_min, time_max, max_results=250):
    """List calendar events in a time range. Returns list of event dicts.

    Equivalent to: gog calendar events email --from start --to end --max N --json
    """
    result = run_gws("calendar events list", params={
        "calendarId": calendar_id,
        "timeMin": time_min,
        "timeMax": time_max,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    })
    if result is None:
        return []
    return result.get("items") or []


# ---------------------------------------------------------------------------
# Drive operations
# ---------------------------------------------------------------------------

def gws_drive_search(query, page_size=50):
    """Search Google Drive files. Returns list of file dicts.

    Equivalent to: gog drive search "query" --max N --json
    """
    result = run_gws("drive files list", params={
        "q": query,
        "pageSize": page_size,
        "fields": "files(id,name,mimeType,createdTime,modifiedTime)",
    })
    if result is None:
        return []
    return result.get("files") or []


def gws_drive_download(file_id, out_path, mime_type=None):
    """Download a file from Google Drive.

    For Google Docs/Sheets/etc, exports as the specified mime type.
    For regular files, downloads directly.

    Equivalent to: gog drive download fileId --out path
    """
    # For native Google formats, use export
    google_mimes = {
        'application/vnd.google-apps.document',
        'application/vnd.google-apps.spreadsheet',
        'application/vnd.google-apps.presentation',
    }

    if mime_type and mime_type in google_mimes:
        export_mime = 'text/plain'  # Default export format
        result = run_gws("drive files export", params={
            "fileId": file_id,
            "mimeType": export_mime,
        })
        if result is None:
            return False
        try:
            with open(out_path, 'w') as f:
                if isinstance(result, dict):
                    json.dump(result, f)
                else:
                    f.write(str(result))
            return True
        except Exception as e:
            print(f"  Drive export error: {e}", file=sys.stderr)
            return False
    else:
        # Direct download — use the access token with requests for binary files
        token = get_google_access_token()
        if not token:
            return False
        try:
            import requests
            resp = requests.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            )
            if resp.status_code == 200:
                with open(out_path, 'wb') as f:
                    f.write(resp.content)
                return True
            print(f"  Drive download failed: HTTP {resp.status_code}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"  Drive download error: {e}", file=sys.stderr)
            return False


# ---------------------------------------------------------------------------
# Auth / token helpers
# ---------------------------------------------------------------------------

_GWS_CREDENTIALS_PATH = os.path.expanduser("~/.config/gws/credentials.json")


def get_google_access_token():
    """Get a fresh Google OAuth2 access token via gws-auth stored credentials.

    Checks GOOGLE_WORKSPACE_CLI_TOKEN env var first (set by gws-auth),
    then falls back to reading credentials.json and exchanging refresh token.
    """
    # Check env var first (gws-auth sets this when running in its context)
    env_token = os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN")
    if env_token:
        return env_token

    try:
        # Read gws-auth credentials (client_id, client_secret, refresh_token)
        with open(_GWS_CREDENTIALS_PATH) as f:
            creds = json.load(f)

        # Exchange refresh token for access token
        import requests
        response = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
            'refresh_token': creds['refresh_token'],
            'grant_type': 'refresh_token',
        }, timeout=10)

        if response.status_code == 200:
            return response.json()['access_token']

        print(f"  Token exchange failed: HTTP {response.status_code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  get_google_access_token error: {e}", file=sys.stderr)
        return None
