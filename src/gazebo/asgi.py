"""Pure-ASGI middleware — no web-framework import required.

Works with any ASGI app (Starlette, FastAPI, Litestar, Quart). Provides
proxy-header normalization (with pluggable trust) and a context-setting middleware
parametrized by a scope->RequestContext factory.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from gazebo.context import RequestContext, use_context

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
TrustPolicy = Callable[[Scope], bool]

Headers = list[tuple[bytes, bytes]]


def _get(headers: Headers, name: bytes) -> bytes | None:
    for key, value in headers:
        if key == name:
            return value
    return None


def _set(headers: Headers, name: bytes, value: bytes) -> None:
    for i, (key, _) in enumerate(headers):
        if key == name:
            headers[i] = (name, value)
            return
    headers.append((name, value))


def _first(value: bytes) -> bytes:
    return value.split(b',')[0].strip()


# --- trust policies -------------------------------------------------------


def trust_none(scope: Scope) -> bool:
    return False


def trust_all(scope: Scope) -> bool:
    return True


class TrustedClient:
    """Trust requests whose immediate client host is in an allowlist."""

    LOOPBACK = ('127.0.0.1', '::1')

    def __init__(self, *hosts: str, loopback: bool = True) -> None:
        self.hosts = set(hosts) | (set(self.LOOPBACK) if loopback else set())

    def __call__(self, scope: Scope) -> bool:
        client = scope.get('client')
        return bool(client) and client[0] in self.hosts  # type: ignore[index]


class SharedSecret:
    """Trust requests carrying a matching shared-secret header (proxy-chain auth)."""

    def __init__(self, secret: str, *, header: str = 'x-proxy-secret') -> None:
        self._secret = secret.encode('latin-1')
        self._header = header.lower().encode('latin-1')

    def __call__(self, scope: Scope) -> bool:
        return _get(list(scope.get('headers') or []), self._header) == self._secret


def all_of(*policies: TrustPolicy) -> TrustPolicy:
    return lambda scope: all(policy(scope) for policy in policies)


def any_of(*policies: TrustPolicy) -> TrustPolicy:
    return lambda scope: any(policy(scope) for policy in policies)


# --- proxy headers --------------------------------------------------------


class ProxyHeadersMiddleware:
    """Apply ``X-Forwarded-{Proto,Host,Prefix}`` to the ASGI scope when trusted.

    Supersedes uvicorn's partial ``--proxy-headers``: it also sets the scheme from
    ``X-Forwarded-Proto`` (so URLs come out ``https`` behind a TLS-terminating
    proxy) and mutates the header list in place rather than round-tripping a dict.
    """

    def __init__(self, app: ASGIApp, *, trust: TrustPolicy = trust_none) -> None:
        self.app = app
        self.trust = trust

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] in ('http', 'websocket') and self.trust(scope):
            self._apply(scope)
        await self.app(scope, receive, send)

    @staticmethod
    def _apply(scope: Scope) -> None:
        headers: Headers = list(scope.get('headers') or [])
        scope['headers'] = headers

        if proto := _get(headers, b'x-forwarded-proto'):
            scope['scheme'] = _first(proto).decode('latin-1')

        if host := _get(headers, b'x-forwarded-host'):
            value = _first(host)
            _set(headers, b'host', value)
            name = value.split(b':')[0].decode('latin-1')
            _, port = scope.get('server') or (None, None)
            scope['server'] = (name, port)

        if prefix := _get(headers, b'x-forwarded-prefix'):
            scope['root_path'] = _first(prefix).decode('latin-1').rstrip('/')


# --- context setting ------------------------------------------------------


class ContextMiddleware:
    """Set :data:`~gazebo.context.link_context` for each request.

    ``factory`` turns the ASGI ``scope`` into a :class:`RequestContext`; the
    framework glue supplies it (e.g. wrapping the framework's request object). Use this
    when you are *not* using ``GazeboApp`` (which manages context via its request
    scope).
    """

    def __init__(self, app: ASGIApp, factory: Callable[[Scope], RequestContext]) -> None:
        self.app = app
        self.factory = factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        with use_context(self.factory(scope)):
            await self.app(scope, receive, send)
