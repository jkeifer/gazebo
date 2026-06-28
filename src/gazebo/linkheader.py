"""RFC 8288 ``Link:`` header serialization for already-resolved links.

Core layer: stdlib only, no web framework. Turns a list of *resolved* links (the
serialized link dicts gazebo already emits in a JSON body) into a single ``Link:``
header value, so non-JSON-parsing clients and crawlers can follow ``self``/``next``/
``prev``/``alternate`` without reading the body. The framework glue (see
:mod:`gazebo.ext.fastapi`) installs the header from a response's top-level links;
this module owns only the formatting and the deliberate *narrowing* that keeps the
header small.

Two guards keep the header from bloating — the classic failure mode of ``Link:``
when a collection carries hundreds of per-item links:

- **A rel allow-list.** Only *navigational* relations (:data:`NAV_RELS`) are emitted
  by default — never arbitrary or per-item rels.
- **A hard cap** (:data:`DEFAULT_MAX_LINKS`) on how many links are serialized.

Callers that want everything can pass ``rels=None`` (no filter) and a large
``max_links``, but the defaults are intentionally conservative.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

NAV_RELS: tuple[str, ...] = (
    'self',
    'first',
    'prev',
    'next',
    'last',
    'alternate',
    'root',
    'up',
    'collection',
    'describedby',
    'conformance',
    'service-desc',
)
"""The link relations safe to surface in a ``Link:`` header by default.

Navigational/hypermedia rels a client or crawler follows — deliberately *not* every
rel a body might carry, and never per-item links. Override via the ``rels`` argument
to :func:`format_link_header` (or the FastAPI ``set_link_header`` helper)."""

DEFAULT_MAX_LINKS = 25
"""Default ceiling on links emitted into one header, so a pathological body can't
produce an oversized header that trips server/proxy header-size limits."""


def _latin1_ok(value: str) -> bool:
    # ASGI header values are latin-1; a value that can't be encoded would raise when the
    # glue does ``header.encode('latin-1')``, so it is dropped rather than crashing the
    # response. Most hrefs/rels are ASCII, but a non-ASCII IRI href (or an arbitrary rel
    # under ``rels=None``) can reach here.
    try:
        value.encode('latin-1')
    except UnicodeEncodeError:
        return False
    return True


def _quote(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _format_one(link: Mapping[str, Any]) -> str | None:
    href = link.get('href')
    rel = link.get('rel')
    if not href or not rel:
        return None
    href, rel = str(href), str(rel)
    # href/rel are mandatory; if either can't go in a latin-1 header, drop the whole
    # link (the JSON body still carries it) rather than emitting a broken header.
    if not _latin1_ok(href) or not _latin1_ok(rel):
        return None
    parts = [f'<{href}>', f'rel="{_quote(rel)}"']
    media = link.get('type')
    if media and _latin1_ok(str(media)):
        parts.append(f'type="{_quote(str(media))}"')
    title = link.get('title')
    if title and _latin1_ok(str(title)):
        parts.append(f'title="{_quote(str(title))}"')
    return '; '.join(parts)


def format_link_header(
    links: Iterable[Mapping[str, Any]],
    *,
    rels: Sequence[str] | None = NAV_RELS,
    max_links: int = DEFAULT_MAX_LINKS,
) -> str:
    """Serialize resolved ``links`` into an RFC 8288 ``Link:`` header value.

    Args:
        links: Resolved link mappings — each a dict with at least ``href`` and
            ``rel`` (the shape gazebo serializes into a JSON body). A link missing
            either is skipped, and a callable (unresolved) href cannot appear here.
        rels: The relations to include, in any order; a link whose ``rel`` is not in
            this set is dropped. ``None`` disables filtering (include every rel) —
            use with care, since that can include per-item links.
        max_links: Stop after this many links (after filtering), guarding header size.

    Returns:
        The header value (links joined by ``, ``), or ``''`` when nothing qualifies —
        callers should then omit the header entirely rather than send an empty one.
    """
    allowed = None if rels is None else frozenset(rels)
    out: list[str] = []
    for link in links:
        if allowed is not None and link.get('rel') not in allowed:
            continue
        formatted = _format_one(link)
        if formatted is None:
            continue
        out.append(formatted)
        if len(out) >= max_links:
            break
    return ', '.join(out)


__all__ = [
    'DEFAULT_MAX_LINKS',
    'NAV_RELS',
    'format_link_header',
]
