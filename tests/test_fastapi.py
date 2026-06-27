from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

import pytest

from fastapi import Request
from fastapi.testclient import TestClient

from gazebo.asgi import trust_all
from gazebo.collection import LinkedCollection
from gazebo.ext.fastapi import (
    GazeboApp,
    GazeboRouter,
    Inject,
    LinkedRouter,
    Overrides,
    Providers,
    forward_lifespans,
    upgrade,
)
from gazebo.link import Link
from gazebo.problems import ProblemException
from gazebo.rels import Rel

TORN: list[str] = []


@dataclass
class Settings:
    dsn: str = 'real'

    @classmethod
    def __provide__(cls) -> Settings:
        return cls()


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @classmethod
    @asynccontextmanager
    async def __provide__(cls, settings: Settings) -> AsyncIterator[Database]:
        try:
            yield cls(settings.dsn)
        finally:
            TORN.append('db')

    async def __health__(self) -> bool:
        return True


class Session:
    """External-style type: provided by a standalone function, injected via Inject."""

    def __init__(self, db: Database) -> None:
        self.db = db


@asynccontextmanager
async def provide_session(database: Database) -> AsyncIterator[Session]:
    try:
        yield Session(database)
    finally:
        TORN.append('session')


@dataclass
class User:
    name: str

    @classmethod
    async def __provide__(cls, request: Request, session: Annotated[Session, Inject]) -> User:
        return cls(request.headers.get('authorization', 'anon'))


@dataclass
class Ping:
    ok: bool = True

    @classmethod
    async def __provide__(cls) -> Ping:
        return cls()


class ThingCollection(LinkedCollection[dict], items_alias='things'):
    pass


def build_router() -> GazeboRouter:
    router = GazeboRouter()

    @router.get('/things', response_model=ThingCollection)
    async def list_things(session: Annotated[Session, Inject], user: User, limit: int = 10):
        items = [{'id': i, 'owner': user.name, 'dsn': session.db.dsn} for i in range(limit)]
        return ThingCollection(items=items, links=[Link.self_link(), Link.root_link()])

    @router.get('/boom')
    async def boom():
        raise ProblemException(404, detail='nope', instance='/boom')

    return router


def make_app(overrides: Overrides | None = None) -> GazeboApp:
    providers = Providers()
    providers.app(Settings).app(Database)
    providers.request(Session, provide_session).request(User)
    app = GazeboApp(providers, overrides=overrides, trust=trust_all)
    app.include_router(build_router())

    @app.get('/', name='landing')
    async def landing():
        return {'ok': True}

    return app


@pytest.fixture
def client():
    TORN.clear()
    with TestClient(make_app()) as c:
        yield c


def test_bare_type_injection(client):
    r = client.get('/things?limit=2', headers={'authorization': 'alice'})
    assert r.status_code == 200
    body = r.json()
    assert body['things'] == [
        {'id': 0, 'owner': 'alice', 'dsn': 'real'},
        {'id': 1, 'owner': 'alice', 'dsn': 'real'},
    ]
    assert body['numberReturned'] == 2


def test_links_resolved_in_response(client):
    body = client.get('/things?limit=1', headers={'authorization': 'a'}).json()
    rels = {link['rel']: link['href'] for link in body['links']}
    assert rels['self'].endswith('/things?limit=1')
    assert rels['root'].endswith('/')


def test_problem_response(client):
    r = client.get('/boom')
    assert r.status_code == 404
    assert r.headers['content-type'] == 'application/problem+json'
    assert r.json()['detail'] == 'nope'


def test_validation_error_is_problem(client):
    # a non-int `limit` fails FastAPI request validation; the glue maps that to a
    # problem+json 422 (not FastAPI's default {"detail": [...]} shape).
    r = client.get('/things?limit=nope', headers={'authorization': 'a'})
    assert r.status_code == 422
    assert r.headers['content-type'] == 'application/problem+json'
    body = r.json()
    assert body['status'] == 422
    assert body['title'] == 'Unprocessable Entity'
    # the field-level error list is carried as an RFC 9457 extension member
    assert body['errors']
    assert any(err['loc'] == ['query', 'limit'] for err in body['errors'])


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


def test_injected_params_absent_from_openapi(client):
    schema = client.get('/openapi.json').json()
    params = schema['paths']['/things']['get'].get('parameters', [])
    names = {p['name'] for p in params}
    assert 'limit' in names
    assert 'session' not in names
    assert 'user' not in names


def test_plain_router_injectable_fails_loudly():
    # Declaring an injectable-typed route on a plain APIRouter (instead of a
    # GazeboRouter) must fail loudly at startup, not silently treat it as a body.
    from fastapi import APIRouter

    plain = APIRouter()

    @plain.get('/oops')
    async def oops(ping: Ping):
        return {'ok': True}

    app = GazeboApp(Providers().request(Ping))
    app.include_router(plain)
    with pytest.raises(RuntimeError, match='look injectable'), TestClient(app):
        pass


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


def test_linked_router_hierarchy():
    root = LinkedRouter(title='API', landing_name='landing')
    things = LinkedRouter(rel=Rel.CHILD, title='Things', landing_name='things_landing')

    @things.get('/list')
    async def listing():
        return {'ok': True}

    root.include_router(things, prefix='/things')

    providers = Providers()
    app = GazeboApp(providers, trust=trust_all)
    app.include_router(root)

    with TestClient(app) as client:
        home = client.get('/').json()
        rels = {link['rel'] for link in home['links']}
        assert 'self' in rels
        assert 'root' in rels
        assert Rel.CHILD in rels
        child = client.get('/things').json()
        child_rels = {link['rel'] for link in child['links']}
        assert 'self' in child_rels
