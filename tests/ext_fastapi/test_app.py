"""App wiring: lifespan/scopes, upgrade, mounted lifespans, request-body replay, health."""

from __future__ import annotations

import asyncio

import httpx2 as httpx

from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gazebo.context import RequestContext
from gazebo.di import Key
from gazebo.ext.fastapi import (
    GazeboApp,
    GazeboRouter,
    Overrides,
    Providers,
    forward_lifespans,
    upgrade,
)

from .support import TORN, Ping, Settings, make_app


def test_health(client):
    body = client.get('/health').json()
    assert body['status'] == 'healthy'
    assert body['checks'].get('Database') == 'ok'


def test_proxy_headers_make_links_https(client):
    body = client.get(
        '/things?limit=1',
        headers={
            'authorization': 'b',
            'x-forwarded-proto': 'https',
            'x-forwarded-host': 'api.public.com',
            'x-forwarded-prefix': '/v1',
        },
    ).json()
    rels = {link['rel']: link['href'] for link in body['links']}
    assert rels['self'].startswith('https://api.public.com/')
    assert rels['root'] == 'https://api.public.com/v1/'


def test_teardown_order(client):
    client.get('/things?limit=1', headers={'authorization': 'a'})
    # request-scoped session torn down before app-scoped db at shutdown
    assert 'session' in TORN


def test_overrides():
    with TestClient(make_app(Overrides().set(Settings, Settings(dsn='TEST')))) as client:
        body = client.get('/things?limit=1', headers={'authorization': 'x'}).json()
        assert body['things'][0]['dsn'] == 'TEST'


def test_upgrade_existing_app():
    from fastapi import FastAPI

    gr = GazeboRouter()

    @gr.get('/ping')
    async def ping_route(ping: Ping):
        return {'ok': ping.ok}

    app = FastAPI(title='pre-existing')
    app.include_router(gr)
    upgrade(app, Providers().request(Ping))  # gazebo-ify an app we didn't construct
    with TestClient(app) as client:
        assert client.get('/ping').json() == {'ok': True}
        assert client.get('/health').status_code == 200


def test_upgrade_does_not_mutate_callers_providers():
    from fastapi import FastAPI

    providers = Providers().request(Ping)
    assert Key(RequestContext) not in providers.bindings  # type: ignore[type-abstract]

    app = FastAPI(title='pre-existing')
    upgrade(app, providers)

    # upgrade() must layer in the default RequestContext binding on its own copy,
    # never write it back into the caller-owned registry.
    assert Key(RequestContext) not in providers.bindings  # type: ignore[type-abstract]
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200


def test_forward_lifespans_mount():
    from fastapi import FastAPI

    sub = GazeboApp(Providers().request(Ping))
    subr = GazeboRouter()

    @subr.get('/ping')
    async def ping_route(ping: Ping):
        return {'ok': ping.ok}

    sub.include_router(subr)

    root = FastAPI(lifespan=forward_lifespans(sub))
    root.mount('/api', sub)
    with TestClient(root) as client:
        assert client.get('/api/ping').json() == {'ok': True}


# --- body-reading recipes share the request body with the endpoint --------


async def _asgi_request(app, method, path, *, json=None, timeout=5.0):
    # Drive the app via an in-process ASGI transport with an explicit timeout so a
    # regression that re-introduces the body-read deadlock fails the suite instead of
    # hanging it (TestClient has no server-side hang protection). We enter the lifespan
    # ourselves because ASGITransport does not run it.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            return await asyncio.wait_for(client.request(method, path, json=json), timeout)


class _Audit:
    """A request-scoped recipe that reads the raw request body."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    @classmethod
    async def __provide__(cls, request: Request) -> _Audit:
        return cls(await request.body())


class _Item(BaseModel):
    name: str


async def test_body_reading_recipe_and_body_endpoint_do_not_deadlock():
    # A recipe reading the body AND an endpoint parsing the body consume the same ASGI
    # receive channel; without a replayable receive the second reader blocks forever.
    router = GazeboRouter()

    @router.post('/items')
    async def create(item: _Item, audit: _Audit) -> dict:
        return {'name': item.name, 'audit_len': len(audit.raw)}

    app = GazeboApp(Providers().request(_Audit))
    app.include_router(router)

    resp = await _asgi_request(app, 'POST', '/items', json={'name': 'widget'})
    assert resp.status_code == 200
    body = resp.json()
    assert body['name'] == 'widget'
    assert body['audit_len'] > 0


async def test_body_reading_recipe_without_body_endpoint():
    # The recipe reads the body even though the endpoint does not parse one.
    router = GazeboRouter()

    @router.post('/audit')
    async def audit_only(audit: _Audit) -> dict:
        return {'audit_len': len(audit.raw)}

    app = GazeboApp(Providers().request(_Audit))
    app.include_router(router)

    resp = await _asgi_request(app, 'POST', '/audit', json={'hello': 'world'})
    assert resp.status_code == 200
    assert resp.json()['audit_len'] > 0


async def test_ordinary_body_endpoint_without_recipe_still_works():
    # Regression: the replay wrapper must not disturb the plain case (endpoint parses a
    # body, no body-reading recipe).
    router = GazeboRouter()

    @router.post('/plain')
    async def plain(item: _Item) -> dict:
        return {'name': item.name}

    app = GazeboApp(Providers())
    app.include_router(router)

    resp = await _asgi_request(app, 'POST', '/plain', json={'name': 'plain'})
    assert resp.status_code == 200
    assert resp.json() == {'name': 'plain'}


# --- health status code reflects readiness --------------------------------


class _Unhealthy:
    @classmethod
    def __provide__(cls) -> _Unhealthy:
        return cls()

    async def __health__(self) -> bool:
        return False


class _Erroring:
    @classmethod
    def __provide__(cls) -> _Erroring:
        return cls()

    def __health__(self) -> bool:
        raise RuntimeError('probe blew up')


def test_health_healthy_is_200(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'healthy'


def test_health_unhealthy_resource_is_503():
    app = GazeboApp(Providers().app(_Unhealthy))
    with TestClient(app) as client:
        r = client.get('/health')
        assert r.status_code == 503
        body = r.json()
        assert body['status'] == 'unhealthy'
        assert body['checks'][str(Key(_Unhealthy))] == 'fail'


def test_health_erroring_probe_is_503():
    app = GazeboApp(Providers().app(_Erroring))
    with TestClient(app) as client:
        r = client.get('/health')
        assert r.status_code == 503
        assert r.json()['checks'][str(Key(_Erroring))] == 'error'
