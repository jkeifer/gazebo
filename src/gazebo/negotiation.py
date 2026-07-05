"""Content negotiation: resolve a representation from ``?f=`` then ``Accept``.

Core layer: pydantic + stdlib only, no web framework. OGC APIs let a client pick a
representation with a ``?f=json|html`` query parameter (which takes precedence) and
fall back to the HTTP ``Accept`` header. This module owns that *resolution* — given the
representations a resource offers, pick one — plus the ``alternate`` links that point at
the others. It ships no HTML/templating opinion: rendering a chosen representation is
the caller's job (a callable or template hook); gazebo only tells you *which* one and
links the rest.

Resolution order (per OGC API Common):

1. ``?f=`` — an explicit format key wins. An *unknown* key is a client error
   (:class:`~gazebo.params.ParamError` → ``400``).
2. ``Accept`` — standard HTTP negotiation over the offered media types. When an
   ``Accept`` is present but *nothing* it lists is on offer, that's a ``406``
   (:class:`~gazebo.problems.ProblemException`).
3. Otherwise the ``default`` (or the first offered representation).

Both error types already have handlers in the FastAPI glue, so a failed negotiation
renders as ``application/problem+json`` with no extra wiring.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from gazebo.context import with_query
from gazebo.link import Link, UrlResolver
from gazebo.params import ParamError
from gazebo.problems import ProblemException
from gazebo.rels import MediaType, Rel


@dataclass(frozen=True, slots=True)
class Representation:
    """One representation a resource offers: a ``?f=`` key and its media type."""

    key: str
    media_type: str


# Ready-made representations for the common OGC media types.
JSON = Representation('json', MediaType.JSON)
GEOJSON = Representation('geojson', MediaType.GEOJSON)
HTML = Representation('html', MediaType.HTML)


def _parse_accept(header: str) -> list[tuple[str, str, float]]:
    """Parse an ``Accept`` header into ``(type, subtype, q)`` ranges."""
    ranges: list[tuple[str, str, float]] = []
    for part in header.split(','):
        tokens = [token.strip() for token in part.split(';')]
        media = tokens[0].lower()
        if '/' not in media:
            continue
        q = 1.0
        for token in tokens[1:]:
            if token.startswith('q='):
                try:
                    q = float(token[2:])
                except ValueError:
                    q = 0.0
                # A qvalue is 0..1 (RFC 9110 §12.4.2); reject anything outside that,
                # including non-finite values like nan/inf that would otherwise poison
                # the max() in negotiate().
                if not 0.0 <= q <= 1.0:
                    q = 0.0
        mtype, _, msub = media.partition('/')
        ranges.append((mtype, msub, q))
    return ranges


def _accept_quality(media_type: str, ranges: Sequence[tuple[str, str, float]]) -> float:
    """The q-value the parsed ``Accept`` ranges assign to ``media_type`` (0 = no match).

    The most *specific* matching range wins (exact ``type/subtype`` over ``type/*`` over
    ``*/*``), as required by HTTP content negotiation.
    """
    mtype, _, msub = media_type.split(';')[0].strip().lower().partition('/')
    best: tuple[int, float] | None = None
    for rtype, rsub, q in ranges:
        if rtype == '*' and rsub == '*':
            specificity = 0
        elif rtype == mtype and rsub == '*':
            specificity = 1
        elif rtype == mtype and rsub == msub:
            specificity = 2
        else:
            continue
        if best is None or specificity > best[0]:
            best = (specificity, q)
    return best[1] if best else 0.0


def negotiate(
    available: Sequence[Representation],
    *,
    f: str | None = None,
    accept: str | None = None,
    default: Representation | None = None,
    f_param: str = 'f',
) -> Representation:
    """Resolve which of ``available`` to serve from ``f`` (wins) then ``accept``.

    Args:
        available: The representations the resource offers, in server-preferred order.
        f: The ``?f=`` query value, if any (an explicit format key).
        accept: The ``Accept`` header value, if any.
        default: The representation to serve when neither ``f`` nor ``accept`` selects
            one; falls back to the first of ``available``.
        f_param: The query parameter name to cite in an unknown-format error.

    Raises:
        ValueError: If ``available`` is empty (a server misconfiguration).
        ParamError: If ``f`` names a format that is not on offer (→ ``400``).
        ProblemException: If ``accept`` is present but lists nothing on offer (→ ``406``).
    """
    if not available:
        raise ValueError('negotiate requires at least one available representation')
    if f is not None:
        for rep in available:
            if rep.key == f:
                return rep
        keys = ', '.join(rep.key for rep in available)
        raise ParamError(f_param, f'unsupported format {f!r}; available: {keys}')
    if accept:
        ranges = _parse_accept(accept)
        if ranges:
            scored = [
                (_accept_quality(rep.media_type, ranges), i, rep)
                for i, rep in enumerate(available)
            ]
            # highest q wins; ties fall to server-preferred order (lowest index)
            best_q, _, best = min(scored, key=lambda s: (-s[0], s[1]))
            if best_q > 0:
                return best
            offered = ', '.join(rep.media_type for rep in available)
            raise ProblemException(
                406,
                detail=f'no acceptable representation; offered: {offered}',
            )
    return default or available[0]


def _f_href(key: str, f_param: str) -> UrlResolver:
    """A deferred href that rewrites only the ``f_param`` query value to ``key``."""
    return lambda ctx: with_query(ctx, **{f_param: key})


def alternate_links(
    current: Representation,
    available: Sequence[Representation],
    *,
    f_param: str = 'f',
    rel: str = Rel.ALTERNATE,
) -> list[Link]:
    """Build deferred ``alternate`` links to every offered representation but ``current``.

    Each link points at the current request URL with ``?f=`` set to that
    representation's key, so a client on the JSON view can discover (and switch to) the
    HTML one, and vice versa. Pair with a normal ``self`` link for ``current``.
    """
    links: list[Link] = []
    for rep in available:
        if rep.key == current.key:
            continue
        links.append(
            Link(href=_f_href(rep.key, f_param), rel=rel, type=rep.media_type, title=rep.key),
        )
    return links


__all__ = [
    'GEOJSON',
    'HTML',
    'JSON',
    'Representation',
    'alternate_links',
    'negotiate',
]
