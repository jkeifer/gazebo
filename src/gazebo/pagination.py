"""Pagination link helpers.

Builds ``next``/``prev`` (and optional ``first``/``last``/``self``) links as deferred
resolvers: at serialization they take the current request URL from the context and
rewrite only the pagination query params, preserving everything else. The caller owns
token semantics; gazebo only builds the links.

The builders are a thin convenience over :class:`~gazebo.link.Link`, **not** a lossy
abstraction over it: every generated link can carry the full ``Link`` surface — a
``type``, ``headers``, a ``title`` (or any extra member, via ``**link_fields``), and a
``method``/``body``. That last pair is what makes **POST** pagination work on a
*stateless* server: with ``method='POST'`` the page token rides in the request **body**
(merged into the ``body`` you pass) rather than the query string, so each ``next`` link
re-states the full search criteria the server doesn't remember.

Two flavours, both additive and framework-agnostic:

- :func:`paginate` — **token**-based: you supply opaque ``next``/``prev`` tokens (and
  optionally a ``last`` token). Pair it with :func:`encode_cursor`/:func:`decode_cursor`
  if you want a ready-made opaque cursor format instead of hand-rolling one.
- :func:`paginate_offset` — **offset/limit**-based: you supply the current ``offset``,
  the page ``limit``, and (optionally) the ``total``; the ``first``/``prev``/``next``/
  ``last``/``self`` links are derived for you.
"""

from __future__ import annotations

import base64
import json

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from gazebo.context import RequestContext
from gazebo.link import Link
from gazebo.params import ParamError
from gazebo.rels import MediaType, Rel


def last_page_offset(total: int, limit: int) -> int:
    """The zero-based offset of the last page for ``total`` items at page size ``limit``.

    Zero when there are no items. ``limit`` must be positive. Shared so callers
    deriving their own ``last`` cursor don't re-spell the rounding math.
    """
    return ((total - 1) // limit) * limit if total > 0 else 0


def with_query(ctx: RequestContext, **overrides: object) -> str:
    """Return the current URL with ``overrides`` merged into the query string.

    A ``None`` value removes that parameter. Other values are stringified.
    """
    parts = urlsplit(ctx.url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in overrides.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = str(value)
    return urlunsplit(parts._replace(query=urlencode(query)))


def _link_fields(
    type: str | None,
    headers: Mapping[str, str | list[str]] | None,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    fields: dict[str, Any] = dict(extra)
    if type is not None:
        fields['type'] = type
    if headers is not None:
        fields['headers'] = dict(headers)
    return fields


def _page_link(
    rel: str,
    params: Mapping[str, object],
    *,
    method: str,
    body: Mapping[str, Any] | None,
    type: str | None,
    headers: Mapping[str, str | list[str]] | None,
    extra: Mapping[str, Any],
) -> Link:
    """Build one pagination link, carrying the token in the query (GET) or body (POST).

    ``params`` is the set of pagination parameters to apply (a ``None`` value removes
    that key). For GET they rewrite the current URL's query; for POST they are merged
    into ``body`` and the href stays the current URL (the token travels in the body).
    """
    fields = _link_fields(type, headers, extra)
    if method.upper() == 'POST':
        payload: dict[str, Any] = dict(body or {})
        for key, value in params.items():
            if value is None:
                payload.pop(key, None)
            else:
                payload[key] = value
        return Link(href=lambda ctx: ctx.url, rel=rel, method='POST', body=payload, **fields)
    return Link(href=lambda ctx: with_query(ctx, **params), rel=rel, **fields)


def paginate(
    *,
    next_token: str | None = None,
    prev_token: str | None = None,
    limit: int | None = None,
    first: bool = False,
    last_token: str | None = None,
    self_: bool = False,
    method: str = 'GET',
    body: Mapping[str, Any] | None = None,
    type: str | None = MediaType.JSON,
    headers: Mapping[str, str | list[str]] | None = None,
    token_param: str = 'token',  # noqa: S107
    limit_param: str = 'limit',
    **link_fields: Any,
) -> list[Link]:
    """Return token-based pagination links for the values provided (deferred).

    Args:
        next_token: Token for the next page; emits a ``next`` link when set.
        prev_token: Token for the previous page; emits a ``prev`` link when set.
        limit: Page size to carry on every emitted link (omitted when ``None``).
        first: Emit a ``first`` link to the un-tokened first page when ``True``.
        last_token: Token for the last page; emits a ``last`` link when set.
        self_: Emit a ``self`` link to the current request when ``True``.
        method: ``'GET'`` (default) carries the token in the query string; ``'POST'``
            carries it in the request **body** (merged into ``body``) and keeps the
            current URL as the href — the form a stateless server needs.
        body: Base request body for ``method='POST'`` (e.g. the search criteria); the
            pagination params are merged into a copy of it per link.
        type: The ``type`` (target media type) set on every emitted link.
        headers: Optional ``headers`` member set on every emitted link.
        token_param: Query/body parameter name carrying the token.
        limit_param: Query/body parameter name carrying the limit.
        **link_fields: Any further ``Link`` members (e.g. ``title``) applied to every
            emitted link.

    The ``next``/``prev`` links lead the list (unchanged from earlier releases); any
    ``first``/``last``/``self`` links follow.
    """
    opts: dict[str, Any] = {'method': method, 'body': body, 'type': type, 'headers': headers}

    def link(rel: str, token: str | None) -> Link:
        return _page_link(rel, {token_param: token, limit_param: limit}, extra=link_fields, **opts)

    links: list[Link] = []
    if next_token is not None:
        links.append(link(Rel.NEXT, next_token))
    if prev_token is not None:
        links.append(link(Rel.PREV, prev_token))
    if first:
        # The first page is the collection with no token (limit preserved).
        links.append(
            _page_link(
                Rel.FIRST,
                {token_param: None, limit_param: limit},
                extra=link_fields,
                **opts,
            ),
        )
    if last_token is not None:
        links.append(link(Rel.LAST, last_token))
    if self_:
        # self repeats the current request unchanged (no token rewrite).
        links.append(_page_link(Rel.SELF, {}, extra=link_fields, **opts))
    return links


def paginate_offset(
    *,
    offset: int,
    limit: int,
    total: int | None = None,
    self_: bool = True,
    method: str = 'GET',
    body: Mapping[str, Any] | None = None,
    type: str | None = MediaType.JSON,
    headers: Mapping[str, str | list[str]] | None = None,
    offset_param: str = 'offset',
    limit_param: str = 'limit',
    **link_fields: Any,
) -> list[Link]:
    """Return offset/limit pagination links, derived from the current page (deferred).

    Emits ``self``/``first``/``prev``/``next``/``last`` as the position warrants:
    ``first``/``prev`` only when ``offset > 0``; ``next`` whenever ``total`` is unknown
    or another page follows; ``last`` only when ``total`` is known and differs from the
    current page. Each link is canonical — it carries the explicit ``offset``/``limit``.

    Accepts the same ``method``/``body``/``type``/``headers``/``**link_fields``
    pass-through as :func:`paginate` (so offset paging can also ride a POST body).

    Args:
        offset: The current page's zero-based item offset.
        limit: The page size (must be positive).
        total: Total matching items, if known; enables the ``last`` link and lets
            ``next`` stop at the end.
        self_: Emit a ``self`` link to the current (canonical) page when ``True``.
        offset_param: Query/body parameter name carrying the offset.
        limit_param: Query/body parameter name carrying the limit.

    Raises:
        ValueError: If ``limit`` is not positive or ``offset`` is negative.
    """
    if limit <= 0:
        raise ValueError('limit must be positive')
    if offset < 0:
        raise ValueError('offset must not be negative')

    opts: dict[str, Any] = {'method': method, 'body': body, 'type': type, 'headers': headers}

    def at(rel: str, page_offset: int) -> Link:
        params = {offset_param: page_offset, limit_param: limit}
        return _page_link(rel, params, extra=link_fields, **opts)

    links: list[Link] = []
    if self_:
        links.append(at(Rel.SELF, offset))
    if offset > 0:
        links.append(at(Rel.FIRST, 0))
        links.append(at(Rel.PREV, max(0, offset - limit)))
    if total is None or offset + limit < total:
        links.append(at(Rel.NEXT, offset + limit))
    if total is not None:
        last_offset = last_page_offset(total, limit)
        if last_offset != offset:
            links.append(at(Rel.LAST, last_offset))
    return links


def encode_cursor(payload: Mapping[str, Any]) -> str:
    """Encode an arbitrary token ``payload`` as one opaque, URL-safe cursor string.

    The payload (any JSON-serializable mapping — e.g. ``{'after_id': 42}``) is
    serialized to compact JSON and base64url-encoded without padding, so the result
    is safe to drop straight into a ``next``/``prev`` token. Round-trips through
    :func:`decode_cursor`. The cursor is **opaque, not secret** — it is encoded, not
    signed or encrypted, so never trust it without validating the decoded contents.
    """
    raw = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def decode_cursor(token: str, *, parameter: str = 'cursor') -> dict[str, Any]:
    """Decode a cursor produced by :func:`encode_cursor` back into its payload.

    A malformed or non-object cursor raises :class:`~gazebo.params.ParamError` (which
    the FastAPI glue renders as a ``400`` problem) carrying ``parameter`` — treat a
    bad client-supplied cursor as a client error, not a 500.
    """
    padded = token + '=' * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode('ascii'))
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ParamError(parameter, 'malformed cursor') from exc
    if not isinstance(data, dict):
        raise ParamError(parameter, 'cursor must encode an object')
    return data


__all__ = [
    'decode_cursor',
    'encode_cursor',
    'last_page_offset',
    'paginate',
    'paginate_offset',
    'with_query',
]
