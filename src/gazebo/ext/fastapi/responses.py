"""In-endpoint helpers for conditional responses and response headers.

The request/response plumbing for gazebo's pure caching/link primitives: ``not_modified``
evaluates conditional-GET preconditions and returns a ready ``304``; ``set_cache_headers``
and ``set_link_header`` stamp the validators and the RFC 8288 ``Link`` header onto a
success response.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from fastapi import Request, Response

from gazebo.caching import http_date, is_not_modified
from gazebo.link import Link
from gazebo.linkheader import DEFAULT_MAX_LINKS, NAV_RELS, format_link_header


def not_modified(
    request: Request,
    *,
    etag: str | None = None,
    last_modified: datetime | None = None,
    cache_control: str | None = None,
) -> Response | None:
    """Return a ``304 Not Modified`` response if the request's preconditions match.

    Reads ``If-None-Match`` / ``If-Modified-Since`` from ``request`` and compares them
    against the supplied ``etag`` / ``last_modified`` (see
    :func:`gazebo.caching.is_not_modified` for the precedence rules). Returns a ready
    ``304`` carrying the validators when they match, else ``None`` — so the caller
    proceeds to build the full response.

    Pass the same ``cache_control`` you set on the ``200`` path: per RFC 9111 §4.3.4 a
    ``304`` should refresh the cache's freshness directives, so omitting it would make a
    revalidating cache fall back to stale or more-conservative behavior::

        @router.get('/thing', response_model=Thing)
        async def thing(request: Request, response: Response):
            obj = load_thing()
            tag = etag_for(obj)
            if (resp := not_modified(request, etag=tag, cache_control='max-age=60')) is not None:
                return resp
            set_cache_headers(response, etag=tag, cache_control='max-age=60')
            return obj
    """
    if is_not_modified(
        method=request.method,
        etag=etag,
        last_modified=last_modified,
        if_none_match=request.headers.get('if-none-match'),
        if_modified_since=request.headers.get('if-modified-since'),
    ):
        headers: dict[str, str] = {}
        if etag is not None:
            headers['ETag'] = etag
        if last_modified is not None:
            headers['Last-Modified'] = http_date(last_modified)
        if cache_control is not None:
            headers['Cache-Control'] = cache_control
        return Response(status_code=304, headers=headers)
    return None


def set_cache_headers(
    response: Response,
    *,
    etag: str | None = None,
    last_modified: datetime | None = None,
    cache_control: str | None = None,
) -> None:
    """Stamp ``ETag`` / ``Last-Modified`` / ``Cache-Control`` onto ``response``.

    The companion to :func:`not_modified`: set the validators on the success response
    so the *next* request can be made conditional.
    """
    if etag is not None:
        response.headers['ETag'] = etag
    if last_modified is not None:
        response.headers['Last-Modified'] = http_date(last_modified)
    if cache_control is not None:
        response.headers['Cache-Control'] = cache_control


def set_link_header(
    response: Response,
    links: Sequence[Link],
    *,
    rels: Sequence[str] | None = NAV_RELS,
    max_links: int = DEFAULT_MAX_LINKS,
) -> None:
    """Set an RFC 8288 ``Link`` header on ``response`` from ``links``.

    A peer of :func:`set_cache_headers`: call it inside an endpoint to mirror a
    response's navigational links into a ``Link`` header, so non-JSON clients and
    crawlers can follow them without parsing the body. ``links`` is **any** sequence of
    :class:`~gazebo.link.Link` (a collection envelope's ``.links``, or a hand-built
    list) — it is not tied to any response type.

    Deferred (callable) hrefs are resolved against the active request context, so this
    must be called within a request. Only navigational rels (:data:`NAV_RELS`) are
    emitted by default and the count is capped at ``max_links``; pass ``rels=None`` to
    include every rel. Sets nothing when nothing qualifies.
    """
    dumped = [link.model_dump(mode='json') for link in links]
    header = format_link_header(dumped, rels=rels, max_links=max_links)
    if header:
        response.headers['Link'] = header


__all__ = ['not_modified', 'set_cache_headers', 'set_link_header']
