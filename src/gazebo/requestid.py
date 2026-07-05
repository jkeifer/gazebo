"""Opt-in per-request-id tracking for logging.

Independent of the link context in :mod:`gazebo.context`: this module carries a
``ContextVar`` for a request id plus a ``logging.Filter`` that stamps log records
with it. Framework glue (e.g. app middleware) sets the id per request; anything
that logs during that request can then include it in its output. Core layer:
stdlib only.
"""

from __future__ import annotations

import logging

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

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
