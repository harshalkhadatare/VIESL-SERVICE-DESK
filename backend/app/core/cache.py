"""Tiny in-process cache for data that changes rarely (catalog, calendars, statuses, who-has-which-role).

Each warm server instance keeps its own copy for a short time, which saves database round trips on every click.
Changes made through the app clear the relevant entries straight away; anything else expires within seconds.
"""
import threading
import time
from typing import Any, Callable

_store: dict[Any, tuple[float, Any]] = {}
_lock = threading.Lock()


def cached(key, ttl: float, load: Callable[[], Any]) -> Any:
    now = time.monotonic()
    hit = _store.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = load()
    with _lock:
        _store[key] = (now + ttl, value)
    return value


def forget(prefix) -> None:
    """Drop every entry whose key starts with prefix (keys are tuples like ('principal', 12))."""
    with _lock:
        for k in [k for k in _store if (k[0] if isinstance(k, tuple) else k) == prefix or k == prefix]:
            _store.pop(k, None)


def forget_key(key) -> None:
    with _lock:
        _store.pop(key, None)


def clear() -> None:
    with _lock:
        _store.clear()
