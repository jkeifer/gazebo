"""Runnable examples backing ``docs/fastapi/proxy.md``."""

from __future__ import annotations

import logging


# --8<-- [start:trust]
import os

from gazebo.asgi import SharedSecret, TrustedClient, all_of
from gazebo.ext.fastapi import GazeboApp, Providers

# Only honor forwarded headers when the request is both from a known proxy host
# and carries the shared secret (defense in depth). Default is to trust nothing.
trust = all_of(
    TrustedClient('10.0.0.1'),
    SharedSecret(os.environ.get('PROXY_SECRET', 'shh')),
)
app = GazeboApp(Providers(), trust=trust)
# --8<-- [end:trust]


_scope = {
    'type': 'http',
    'client': ('10.0.0.1', 5000),
    'headers': [(b'x-proxy-secret', b'shh')],
}
assert trust(_scope) is True
assert trust({**_scope, 'client': ('1.2.3.4', 5000)}) is False


# --8<-- [start:request_id]
import uuid

from gazebo.asgi import ASGIApp, Receive, Scope, Send
from gazebo.requestid import RequestIdFilter, use_request_id


class RequestIdMiddleware:
    """Pure-ASGI middleware that tags each request with an id."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        with use_request_id(str(uuid.uuid4())):
            await self.app(scope, receive, send)


# Reference %(request_id)s in your log format; the filter supplies the value.
handler = logging.StreamHandler()
handler.addFilter(RequestIdFilter())
handler.setFormatter(logging.Formatter('%(request_id)s %(message)s'))
# --8<-- [end:request_id]


class StampedRecord(logging.LogRecord):
    """A LogRecord with the attribute RequestIdFilter stamps onto every record."""

    request_id: str


record = StampedRecord('x', logging.INFO, '', 0, 'hi', None, None)
RequestIdFilter().filter(record)
assert record.request_id == '-'  # default outside a request

with use_request_id('abc-123'):
    record = StampedRecord('x', logging.INFO, '', 0, 'hi', None, None)
    RequestIdFilter().filter(record)
    assert record.request_id == 'abc-123'
