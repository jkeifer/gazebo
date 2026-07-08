"""The framework-agnostic request-metadata seam gazebo's core builds on.

The core never imports a web framework. The request metadata gazebo's core
features need — URL building for deferred links, and the request headers for
content negotiation — is abstracted behind the ``RequestContext`` protocol and
delivered ambiently through a ``ContextVar`` (set by the framework glue) with a
pydantic-serialization-context fallback for manual dumps and tests.

For URL building, link hrefs may be callables that need "the current request" to
produce a URL; ``RequestContext`` also carries
:meth:`RequestContext.url_for_template`, which resolves a route while leaving
selected variables as RFC 6570 ``{var}`` expressions so a link can advertise an
unbound URI template (``templated: true``). For content negotiation,
:attr:`RequestContext.headers` exposes the request headers (notably ``Accept``) so
core negotiation can fall back to the ambient request with no request in hand.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@runtime_checkable
class RequestContext(Protocol):
    """The framework-agnostic seam for the request metadata gazebo's core needs.

    Covers both request-derived features of the core: URL building (for deferred link
    hrefs) and the request headers (for content negotiation). Any object structurally
    satisfying this (e.g. a framework request adapter) can be placed in
    :data:`link_context`; the core only ever calls these members.

    Because this protocol is ``@runtime_checkable``, every adapter must implement the
    whole surface below — including :meth:`url_for_template` and :attr:`headers`.
    """

    @property
    def base_url(self) -> str: ...

    @property
    def url(self) -> str: ...

    @property
    def query_params(self) -> Mapping[str, str]: ...

    @property
    def headers(self) -> Mapping[str, str]:
        """The request headers, as a case-insensitive mapping (e.g. ``Accept``)."""
        ...

    def url_for(self, name: str, /, **path: object) -> str: ...

    def url_for_template(
        self,
        name: str,
        path: Mapping[str, object],
        template: Sequence[str],
        /,
    ) -> str:
        """Resolve route ``name``, binding ``path`` and leaving ``template`` as ``{var}``.

        Binds the ``path`` params concretely while each variable in ``template`` is left
        in the returned URL as an RFC 6570 ``{var}`` expression, so a link can advertise
        an unbound URI template for the client to expand.
        """
        ...


# Holds the RequestContext for the duration of a request. Set by the framework
# glue (e.g. GazeboApp's request-scope middleware), read during serialization.
link_context: ContextVar[RequestContext | None] = ContextVar(
    'gazebo_link_context',
    default=None,
)


@contextmanager
def use_context(ctx: RequestContext) -> Iterator[RequestContext]:
    """Bind ``ctx`` as the active request context for the duration of the block.

    Uses an explicit ``reset`` in ``finally`` so it is correct on every supported
    Python version (``Token`` only became a context manager in 3.14).
    """
    token: Token[RequestContext | None] = link_context.set(ctx)
    try:
        yield ctx
    finally:
        link_context.reset(token)


def resolve_context(info_context: Any = None) -> RequestContext | None:
    """Find the active request context.

    Resolution order: the :data:`link_context` ContextVar first, then a
    ``request``/``context`` entry in a pydantic serialization ``info.context``
    mapping (the manual-dump / test escape hatch).
    """
    ctx = link_context.get(None)
    if ctx is not None:
        return ctx
    if isinstance(info_context, Mapping):
        candidate = info_context.get('request') or info_context.get('context')
        if candidate is not None:
            return candidate
    return None


def merge_params(params: dict[str, Any], overrides: Mapping[str, object]) -> None:
    """Merge ``overrides`` into ``params`` in place.

    A ``None`` value in ``overrides`` removes the key from ``params``; any other value
    sets it. Shared by :func:`with_query` (query-string overrides) and pagination's POST
    body merge, so the two identical "None removes, else sets" merges aren't re-spelled.
    """
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value


def with_query(ctx: RequestContext, **overrides: object) -> str:
    """Return the current URL with ``overrides`` merged into the query string.

    A ``None`` value removes that parameter (every occurrence). Other values are
    stringified (via :func:`urllib.parse.urlencode`). A repeated parameter
    (``?tag=a&tag=b``) is preserved verbatim unless overridden, in which case the
    override's single value replaces all occurrences. The shared "derive a URL from
    the active context" helper behind deferred pagination and content-negotiation
    hrefs.
    """
    parts = urlsplit(ctx.url)
    # Collect repeated params into lists so they survive the merge; urlencode's
    # doseq re-expands them.
    query: dict[str, Any] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in query:
            existing = query[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                query[key] = [existing, value]
        else:
            query[key] = value
    merge_params(query, overrides)
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))
