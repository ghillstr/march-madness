"""Content-addressed disk cache for generated reports.

Reports are a pure function of (model, prompt version, grounding pack), so a
re-render of a page — or re-opening an expander — should never re-bill.
"""

import hashlib
import json
import os
import time

from config import LLM_CACHE_DIR, LLM_MODEL

# Bump when a prompt changes so stale text is not served.
PROMPT_VERSION = "1"

DEFAULT_TTL = 24 * 3600


def cache_key(kind, pack):
    """Stable key for a report of `kind` grounded in `pack`."""
    payload = json.dumps(pack, sort_keys=True, default=str)
    digest = hashlib.sha256(
        f"{LLM_MODEL}|{PROMPT_VERSION}|{kind}|{payload}".encode("utf-8")
    ).hexdigest()
    return f"{kind}-{digest[:32]}"


def _path(key):
    return os.path.join(LLM_CACHE_DIR, f"{key}.json")


def load(key, ttl=DEFAULT_TTL):
    """Return cached text for `key`, or None on miss/expiry/corruption."""
    path = _path(key)
    try:
        with open(path) as f:
            entry = json.load(f)
    except (OSError, ValueError):
        return None
    if ttl is not None and time.time() - entry.get("created_at", 0) > ttl:
        return None
    return entry.get("text")


def store(key, text):
    """Write `text` to the cache. Cache failures are never fatal."""
    try:
        os.makedirs(LLM_CACHE_DIR, exist_ok=True)
        with open(_path(key), "w") as f:
            json.dump({"created_at": time.time(), "text": text}, f)
    except OSError:
        pass
    return text


def invalidate(key):
    """Drop one cached report so the next request regenerates it."""
    try:
        os.remove(_path(key))
        return True
    except OSError:
        return False


def clear():
    """Drop every cached report. Returns the number of files removed."""
    removed = 0
    try:
        names = os.listdir(LLM_CACHE_DIR)
    except OSError:
        return 0
    for name in names:
        if name.endswith(".json"):
            try:
                os.remove(os.path.join(LLM_CACHE_DIR, name))
                removed += 1
            except OSError:
                pass
    return removed
