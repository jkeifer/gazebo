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
from enum import StrEnum
from typing import TYPE_CHECKING

from gazebo.context import link_context, with_query
from gazebo.link import Link, UrlResolver
from gazebo.params import ParamError
from gazebo.problems import ProblemException
from gazebo.rels import MediaType, Rel

if TYPE_CHECKING:
    from pydantic import GetJsonSchemaHandler
    from pydantic.json_schema import JsonSchemaValue
    from pydantic_core import CoreSchema

F_DESCRIPTION = (
    'The requested output format, as one of the supported representation keys (e.g. '
    '`json` or `html`). Takes precedence over the `Accept` header; an unsupported value '
    'returns a `400` problem.'
)
"""Human-readable description of the OGC ``f`` (format) query parameter."""


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
        accept: The ``Accept`` header value, if any. When omitted (``None``) and an
            ambient :data:`~gazebo.context.link_context` is active, its request's
            ``Accept`` header is used; an explicitly-passed value always takes
            precedence. Passing ``accept=''`` (or a value with no acceptable range)
            still short-circuits to the ``406``/``default`` path without the ambient
            read.
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
    if accept is None:
        # No explicit Accept: fall back to the ambient request's header, if a context
        # is active. Keeps negotiate() pure when called with no context (unit tests).
        ctx = link_context.get(None)
        if ctx is not None:
            accept = ctx.headers.get('accept')
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


# --- Composable closed-set field: format enum -----------------------------
#
# The closed set of ``?f=`` format keys is a *consumer* decision, so it must be spelled by
# the consumer as a real ``StrEnum`` subclass (a class definition is the only construct a
# static type checker accepts as a usable field type). :class:`FormatEnum` is the base to
# subclass: each member's *value* is its ``?f=`` key (so a folded field validates
# membership natively and FastAPI renders it as an ``enum`` query param) and each member
# also carries a ``.media_type``, so the member alone is enough to build a
# :class:`Representation` (``.representation``) for rendering / :func:`alternate_links` and
# for ``Accept``-aware negotiation — no external ``{key: rep}`` dict.


class FormatEnum(StrEnum):
    """Base ``StrEnum`` for a folded ``?f=`` (format) query field's closed key set.

    Subclass it, spelling each supported output format as a member of ``key, media_type``:
    the *value* is the ``?f=`` key and ``media_type`` is what that key serves. Then fold
    the subclass into a pydantic query model as a real field type (no ``type: ignore``
    needed — it is an ordinary class)::

        class BedFormat(FormatEnum):
            json = 'json', 'application/json'
            html = 'html', 'text/html'

        class BedQuery(BaseModel):
            f: BedFormat = BedFormat.json

    Pydantic validates membership by the *key* (member value): an unknown ``?f=`` is a
    ``ValidationError`` that a :class:`~gazebo.ext.fastapi.GazeboApp` renders as a `400`
    ``application/problem+json`` citing the parameter. FastAPI renders the field as an
    ``enum`` of keys, and the base carries :data:`F_DESCRIPTION` so it self-documents in
    OpenAPI. Give the field a plain default so an absent ``?f=`` resolves to it.

    Because each member carries its media type, :attr:`representation` turns a chosen
    member into a :class:`Representation` with no external mapping — drive rendering and
    :func:`alternate_links` straight off the member. For ``Accept``-aware negotiation
    (``?f=`` → ``Accept`` → default, and its `406`), make the field an **optional**
    member (``f: MyFormat | None = None``) and add a one-line
    ``negotiate(MyFormat.representations(), f=query.f)`` call in the handler —
    :func:`negotiate` reads the request's ``Accept`` from the ambient context, so no
    header wrangling is needed.
    """

    media_type: str

    def __new__(cls, key: str, media_type: str) -> FormatEnum:
        obj = str.__new__(cls, key)
        obj._value_ = key
        obj.media_type = media_type
        return obj

    @property
    def representation(self) -> Representation:
        """The :class:`Representation` (``?f=`` key + media type) this member serves."""
        return Representation(self.value, self.media_type)

    @classmethod
    def representations(cls) -> list[Representation]:
        """Every member's :class:`Representation`, in definition (server-preferred) order.

        The ``available`` list for :func:`negotiate` straight off the enum, so a folded
        field negotiates with ``negotiate(MyFormat.representations(), f=query.f)``.
        """
        return [member.representation for member in cls]

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        # Force the shared OGC description onto the enum's schema so a folded field
        # self-documents in OpenAPI (FastAPI reads the parameter description from the
        # enum's own schema, not only from a consumer Field(...)). We overwrite rather than
        # setdefault: pydantic pre-fills ``description`` from the subclass docstring, but
        # the API parameter wants F_DESCRIPTION.
        schema = handler(core_schema)
        schema['description'] = F_DESCRIPTION
        return schema


__all__ = [
    'F_DESCRIPTION',
    'GEOJSON',
    'HTML',
    'JSON',
    'FormatEnum',
    'Representation',
    'alternate_links',
    'negotiate',
]
