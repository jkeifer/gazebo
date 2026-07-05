"""Runnable examples backing ``docs/why.md`` — the gazebo "after" side.

The asserts mirror the failures demonstrated in ``why_before.py`` and show each
one resolved: proxy-correct links, preserved query params, typed overrides.
"""

from __future__ import annotations

# --8<-- [start:app]
from gazebo.collection import LinkedCollection
from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Overrides, Providers
from gazebo.link import Link
from gazebo.pagination import paginate

PLANTS = [{'id': 1, 'name': 'fern'}, {'id': 2, 'name': 'ivy'}, {'id': 3, 'name': 'oak'}]


class Plants(LinkedCollection[dict], items_alias='plants'):
    pass


def plant_page(limit: int, token: str | None = None) -> Plants:
    # business logic builds the whole response, links included -- no request in sight
    start = int(token or 0)
    links = [Link.self_link(), Link.root_link()]
    # --8<-- [start:paginate]
    if start + limit < len(PLANTS):
        links += paginate(next_token=str(start + limit), limit=limit)
    # --8<-- [end:paginate]
    return Plants(items=PLANTS[start : start + limit], links=links)


router = GazeboRouter()


@router.get('/plants', response_model=Plants)
async def list_plants(limit: int = 2, token: str | None = None) -> Plants:
    return plant_page(limit, token)


# --8<-- [end:app]


# --8<-- [start:lifetimes]
from gazebo.asgi import trust_all


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @classmethod
    def __provide__(cls) -> Database:
        return cls('postgres://prod/app')


def create_app(overrides: Overrides | None = None) -> GazeboApp:
    providers = Providers().app(Database)  # what builds it, and how long it lives
    app = GazeboApp(providers, overrides=overrides, trust=trust_all)
    app.include_router(router)

    @app.get('/', name='landing')
    async def landing() -> dict:
        return {'service': 'plants'}

    return app


# --8<-- [end:lifetimes]


@router.get('/db')
async def db_info(db: Database) -> dict:
    return {'dsn': db.dsn}


# --8<-- [start:test]
from fastapi.testclient import TestClient


def test_db() -> None:
    overrides = Overrides().set(Database, Database('sqlite://'))  # by parameter, typed
    with TestClient(create_app(overrides)) as client:
        assert client.get('/db').json() == {'dsn': 'sqlite://'}


# --8<-- [end:test]


test_db()


with TestClient(create_app()) as client:
    # the same forwarded headers why_before.py ignores are honored here
    _body = client.get(
        '/plants',
        headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'api.example.com'},
    ).json()
    _hrefs = {link['rel']: link['href'] for link in _body['links']}
    assert _hrefs['self'] == 'https://api.example.com/plants'
    assert _hrefs['root'] == 'https://api.example.com/'

    # the next link preserves the filter params why_before.py drops -- even repeated ones
    _body = client.get('/plants', params=[('q', 'fern'), ('tag', 'a'), ('tag', 'b')]).json()
    _next_href = {link['rel']: link['href'] for link in _body['links']}['next']
    assert 'q=fern' in _next_href
    assert 'tag=a' in _next_href
    assert 'tag=b' in _next_href
    assert 'token=2' in _next_href
