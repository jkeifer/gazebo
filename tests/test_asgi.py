from __future__ import annotations

import hmac

from gazebo.asgi import (
    ProxyHeadersMiddleware,
    SharedSecret,
    TrustedClient,
    all_of,
    trust_all,
    trust_none,
)


def make_scope(headers: dict[bytes, bytes], *, client=('10.0.0.1', 1234), scope_type='http'):
    return {
        'type': scope_type,
        'scheme': 'http',
        'server': ('internal', 80),
        'headers': list(headers.items()),
        'client': client,
    }


async def run(scope, *, trust) -> dict:
    captured = {}

    async def app(s, receive, send):
        captured.update(s)

    async def receive():
        return {}

    async def send(msg):
        pass

    await ProxyHeadersMiddleware(app, trust=trust)(scope, receive, send)
    return captured


async def test_proxy_headers_applied_when_trusted():
    scope = make_scope(
        {
            b'x-forwarded-proto': b'https',
            b'x-forwarded-host': b'api.public.com',
            b'x-forwarded-prefix': b'/v1',
        },
    )
    out = await run(scope, trust=trust_all)
    assert out['scheme'] == 'https'
    assert out['root_path'] == '/v1'
    assert out['server'][0] == 'api.public.com'
    assert dict(out['headers'])[b'host'] == b'api.public.com'


async def test_proxy_headers_ignored_when_untrusted():
    scope = make_scope({b'x-forwarded-proto': b'https'})
    out = await run(scope, trust=trust_none)
    assert out['scheme'] == 'http'


def test_trusted_client():
    policy = TrustedClient('10.0.0.1')
    assert policy(make_scope({}, client=('10.0.0.1', 1)))
    assert not policy(make_scope({}, client=('1.2.3.4', 1)))


def test_trusted_client_loopback_default():
    policy = TrustedClient()
    assert policy(make_scope({}, client=('127.0.0.1', 1)))


def test_shared_secret():
    policy = SharedSecret('s3cr3t', header='x-proxy-secret')
    assert policy(make_scope({b'x-proxy-secret': b's3cr3t'}))
    assert not policy(make_scope({b'x-proxy-secret': b'wrong'}))
    assert not policy(make_scope({}))


def test_all_of_composition():
    policy = all_of(TrustedClient('10.0.0.1'), SharedSecret('s', header='x-s'))
    assert policy(make_scope({b'x-s': b's'}, client=('10.0.0.1', 1)))
    assert not policy(make_scope({b'x-s': b's'}, client=('9.9.9.9', 1)))


async def test_first_value_of_comma_list():
    scope = make_scope({b'x-forwarded-proto': b'https, http'})
    out = await run(scope, trust=trust_all)
    assert out['scheme'] == 'https'


async def test_websocket_forwarded_https_becomes_wss():
    scope = make_scope({b'x-forwarded-proto': b'https'}, scope_type='websocket')
    out = await run(scope, trust=trust_all)
    assert out['scheme'] == 'wss'


async def test_websocket_forwarded_http_becomes_ws():
    scope = make_scope({b'x-forwarded-proto': b'http'}, scope_type='websocket')
    out = await run(scope, trust=trust_all)
    assert out['scheme'] == 'ws'


async def test_websocket_forwarded_ws_wss_passthrough():
    scope = make_scope({b'x-forwarded-proto': b'wss'}, scope_type='websocket')
    out = await run(scope, trust=trust_all)
    assert out['scheme'] == 'wss'

    scope = make_scope({b'x-forwarded-proto': b'ws'}, scope_type='websocket')
    out = await run(scope, trust=trust_all)
    assert out['scheme'] == 'ws'


async def test_http_scope_scheme_unaffected_by_websocket_mapping():
    scope = make_scope({b'x-forwarded-proto': b'https'})
    out = await run(scope, trust=trust_all)
    assert out['scheme'] == 'https'


def test_shared_secret_uses_constant_time_compare(monkeypatch):
    calls = []
    original = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr('gazebo.asgi.hmac.compare_digest', spy)
    policy = SharedSecret('s3cr3t', header='x-proxy-secret')
    assert policy(make_scope({b'x-proxy-secret': b's3cr3t'}))
    assert not policy(make_scope({b'x-proxy-secret': b'wrong'}))
    assert calls  # compare_digest was actually used, not `==`


def test_shared_secret_absent_header_is_untrusted():
    policy = SharedSecret('s3cr3t', header='x-proxy-secret')
    assert not policy(make_scope({}))
