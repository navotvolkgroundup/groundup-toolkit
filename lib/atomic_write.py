"""Atomic file write utilities.

Ensures state files are never half-written by using temp file + os.replace().
"""

import os
import json
import tempfile


def atomic_json_write(path, data, indent=2):
    """Write JSON data to a file atomically.

    Creates a temp file in the same directory, writes data, then atomically
    replaces the target file. If writing fails, the original file is untouched.

    Args:
        path: Target file path.
        data: JSON-serializable data.
        indent: JSON indentation (default: 2).
    """
    dir_path = os.path.dirname(path) or '.'
    os.makedirs(dir_path, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix='.json', dir=dir_path)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=indent)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
