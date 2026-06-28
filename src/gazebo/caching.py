"""Conditional-request / caching primitives (RFC 7232 / RFC 9111).

Core layer: pydantic + stdlib only, no web framework. Provides the pure pieces a
service needs to support conditional GETs — derive an ``ETag`` from a value, format/
parse HTTP dates, and evaluate ``If-None-Match`` / ``If-Modified-Since`` preconditions
— leaving the request/response plumbing to the FastAPI glue (``not_modified`` /
``set_cache_headers`` in :mod:`gazebo.ext.fastapi`).

ETags are **weak by default** (``W/"…"``): they are derived from a *serialization* of
the value, which signals semantic equivalence rather than byte-for-byte identity — the
honest validator strength for a hash of a JSON dump.
"""

from __future__ import annotations

import hashlib
import json

from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any

from pydantic import BaseModel

_CONDITIONAL_METHODS = frozenset({'GET', 'HEAD'})


def _canonical_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode('utf-8')
    if isinstance(value, BaseModel):
        return value.model_dump_json(by_alias=True).encode('utf-8')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')


def etag_for(value: Any, *, weak: bool = True) -> str:
    """Derive an ``ETag`` from ``value`` (a model, mapping, str, or bytes).

    The value is reduced to canonical bytes — a pydantic model via
    ``model_dump_json(by_alias=True)``, anything else via sorted-key JSON — and hashed
    (SHA-256). The result is a quoted entity-tag, prefixed ``W/`` when ``weak`` (the
    default).

    Note:
        A model carrying deferred (callable-href) links only serializes inside an
        active request context; outside one, ETag such a model from its underlying
        data rather than the link-bearing envelope.
    """
    digest = hashlib.sha256(_canonical_bytes(value)).hexdigest()
    etag = f'"{digest}"'
    return f'W/{etag}' if weak else etag


def http_date(value: datetime) -> str:
    """Format ``value`` as an IMF-fixdate HTTP date (e.g. for ``Last-Modified``)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return format_datetime(value, usegmt=True)


def parse_http_date(value: str) -> datetime | None:
    """Parse an HTTP date header into an aware ``datetime`` (``None`` if malformed)."""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _normalize_etag(tag: str) -> str:
    tag = tag.strip()
    if tag.startswith('W/'):
        tag = tag[2:].strip()
    return tag


def if_none_match_satisfied(etag: str, header: str) -> bool:
    """Whether ``etag`` matches an ``If-None-Match`` header value (weak comparison).

    ``*`` matches any current entity. Per RFC 7232, ``If-None-Match`` uses the *weak*
    comparison function, so the ``W/`` prefix is ignored on both sides.
    """
    header = header.strip()
    if header == '*':
        return True
    current = _normalize_etag(etag)
    return any(current == _normalize_etag(candidate) for candidate in header.split(','))


def is_not_modified(
    *,
    method: str = 'GET',
    etag: str | None = None,
    last_modified: datetime | None = None,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> bool:
    """Evaluate the conditional-GET preconditions; ``True`` means respond ``304``.

    Only ``GET``/``HEAD`` are eligible. ``If-None-Match`` takes precedence over
    ``If-Modified-Since`` (which is ignored entirely when the former is present, per
    RFC 7232 §3.3). HTTP dates carry one-second resolution, so ``last_modified`` is
    truncated to whole seconds before comparison.
    """
    if method.upper() not in _CONDITIONAL_METHODS:
        return False
    if if_none_match is not None:
        return etag is not None and if_none_match_satisfied(etag, if_none_match)
    if if_modified_since is not None and last_modified is not None:
        since = parse_http_date(if_modified_since)
        if since is None:
            return False
        lm = (
            last_modified
            if last_modified.tzinfo is not None
            else last_modified.replace(tzinfo=UTC)
        )
        return lm.replace(microsecond=0) <= since
    return False


__all__ = [
    'etag_for',
    'http_date',
    'if_none_match_satisfied',
    'is_not_modified',
    'parse_http_date',
]
