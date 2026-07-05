"""Runnable examples backing ``docs/why.md`` — the plain-FastAPI "before" side.

Each region shows the hand-rolled version of something gazebo packages; the
asserts below each region demonstrate the failure the page describes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# --8<-- [start:links]
from fastapi import FastAPI, Request

PLANTS = [{'id': 1, 'name': 'fern'}, {'id': 2, 'name': 'ivy'}, {'id': 3, 'name': 'oak'}]

plain = FastAPI()


def plant_page(request: Request, limit: int) -> dict:
    # the request is here only because the links need it
    return {
        'plants': PLANTS[:limit],
        'links': [
            {'rel': 'self', 'href': str(request.url)},
            {'rel': 'root', 'href': str(request.base_url)},
        ],
    }


@plain.get('/plants')
async def list_plants(request: Request, limit: int = 10) -> dict:
    return plant_page(request, limit)


# --8<-- [end:links]


with TestClient(plain) as client:
    _body = client.get(
        '/plants',
        headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'api.example.com'},
    ).json()
    # the forwarded headers are ignored: every link advertises the internal host
    assert _body['links'][0]['href'] == 'http://testserver/plants'


# --8<-- [start:pagination]
PAGE_SIZE = 2


@plain.get('/search')
async def search(request: Request, token: str = '0') -> dict:
    start = int(token)
    next_url = request.url.replace_query_params(token=str(start + PAGE_SIZE))
    return {
        'plants': PLANTS[start : start + PAGE_SIZE],
        'links': [{'rel': 'next', 'href': str(next_url)}],
    }


# --8<-- [end:pagination]


with TestClient(plain) as client:
    _body = client.get('/search', params={'q': 'fern'}).json()
    _next_href = _body['links'][0]['href']
    # the client's filter didn't survive into the next link
    assert 'token=2' in _next_href
    assert 'q=fern' not in _next_href


# --8<-- [start:lifetimes]
from typing import Annotated

from fastapi import Depends


class Pool:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn


def get_pool(request: Request) -> Pool:
    return request.app.state.pool  # created at startup, reached through untyped state


@plain.get('/pool')
async def pool_info(pool: Annotated[Pool, Depends(get_pool)]) -> dict:
    return {'dsn': pool.dsn}


# tests substitute by mutating the application object itself
plain.dependency_overrides[get_pool] = lambda: Pool('sqlite://')
# --8<-- [end:lifetimes]


with TestClient(plain) as client:
    assert client.get('/pool').json() == {'dsn': 'sqlite://'}
plain.dependency_overrides.clear()
