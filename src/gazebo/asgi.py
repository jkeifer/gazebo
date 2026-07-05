"""Pure-ASGI middleware — no web-framework import required.

Works with any ASGI app (Starlette, FastAPI, Litestar, Quart). Provides
proxy-header normalization (with pluggable trust) and a context-setting middleware
parametrized by a scope->RequestContext factory.
"""

from __future__ import annotations

import hmac

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any, ClassVar

from gazebo.context import RequestContext, use_context

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
TrustPolicy = Callable[[Scope], bool]

Headers = list[tuple[bytes, bytes]]


class _ReplayableReceive:
    """Wrap an ASGI ``receive`` so its message stream can be read more than once.

    The request body arrives as a one-shot stream of ``http.request`` messages: once a
    reader has drained ``receive``, a second reader blocks forever. This wrapper caches
    every message it pulls from the original channel and can hand out independent
    ``fork()`` callables, each of which first replays the cache from its own position
    and only then pulls (and caches) further messages from the original.

    That lets, e.g., a DI recipe's ``Request`` and the downstream app each get a fork
    and both read the same body. The trade-off is that consumed body messages are
    retained for the request's duration; this is acceptable because the framework
    (FastAPI/Starlette) already retains the parsed body for the same lifetime.
    """

    def __init__(self, receive: Receive) -> None:
        self._receive = receive
        self._cache: list[MutableMapping[str, Any]] = []

    def fork(self) -> Receive:
        index = 0

        async def receive() -> MutableMapping[str, Any]:
            nonlocal index
            if index < len(self._cache):
                message = self._cache[index]
                index += 1
                return message
            message = await self._receive()
            self._cache.append(message)
            index += 1
            return message

        return receive


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
        value = _get(list(scope.get('headers') or []), self._header)
        if value is None:
            return False
        return hmac.compare_digest(value, self._secret)


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

    # Forwarded protos name the HTTP scheme; a websocket scope needs the ws twin.
    _WEBSOCKET_SCHEMES: ClassVar[dict[str, str]] = {'http': 'ws', 'https': 'wss'}

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
            scheme = _first(proto).decode('latin-1')
            if scope['type'] == 'websocket':
                scheme = ProxyHeadersMiddleware._WEBSOCKET_SCHEMES.get(scheme, scheme)
            scope['scheme'] = scheme

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
