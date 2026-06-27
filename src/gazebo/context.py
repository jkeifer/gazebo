"""Request-context seam for deferred URL generation.

The core never imports a web framework. Link hrefs may be callables that need
"the current request" to produce a URL; that request is abstracted behind the
``RequestContext`` protocol and delivered ambiently through a ``ContextVar`` (set
by the framework glue) with a pydantic-serialization-context fallback for manual
dumps and tests.
"""

from __future__ import annotations

import logging

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RequestContext(Protocol):
    """The minimal surface link factories need to build URLs.

    Any object structurally satisfying this (e.g. a framework request adapter) can be
    placed in :data:`link_context`. The core only ever calls these members.
    """

    @property
    def base_url(self) -> str: ...

    @property
    def url(self) -> str: ...

    @property
    def query_params(self) -> Mapping[str, str]: ...

    def url_for(self, name: str, /, **path: object) -> str: ...


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


# --- request id + logging (deferred nicety, opt-in) -----------------------

request_id: ContextVar[str | None] = ContextVar('gazebo_request_id', default=None)


@contextmanager
def use_request_id(value: str) -> Iterator[str]:
    token = request_id.set(value)
    try:
        yield value
    finally:
        request_id.reset(token)


class RequestIdFilter(logging.Filter):
    """Logging filter that stamps each record with the active request id.

    Add to a handler/logger and reference ``%(request_id)s`` in the format. The
    field is always present (``-`` when no request is active), so the format
    string never breaks outside a request.
    """

    def __init__(self, name: str = '', *, default: str = '-') -> None:
        super().__init__(name)
        self._default = default

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get(None) or self._default
        return True
