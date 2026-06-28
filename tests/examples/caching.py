"""Runnable examples backing ``docs/fastapi/caching.md``."""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.testclient import TestClient


# --8<-- [start:etag]
from gazebo.caching import etag_for

# a weak ETag derived from a serialization of the value
tag = etag_for({'id': 1, 'name': 'Fern'})
assert tag.startswith('W/"')
# --8<-- [end:etag]


# --8<-- [start:conditional]
from gazebo.ext.fastapi import GazeboApp, Providers, etag_for, not_modified, set_cache_headers

app = GazeboApp(Providers())

PLANT = {'id': '1', 'name': 'Fern'}


@app.get('/plants/{plant_id}', response_model=dict)
async def get_plant(plant_id: str, request: Request, response: Response) -> dict | Response:
    etag = etag_for(PLANT)
    # If the client's cached copy is still current, short-circuit to 304 (no body) —
    # passing cache_control so the 304 refreshes the cache's freshness directives too.
    if (cached := not_modified(request, etag=etag, cache_control='max-age=300')) is not None:
        return cached
    # Otherwise stamp the validators so the *next* request can be conditional.
    set_cache_headers(response, etag=etag, cache_control='max-age=300')
    return PLANT


# --8<-- [end:conditional]


with TestClient(app) as client:
    first = client.get('/plants/1')
    assert first.status_code == 200
    etag = first.headers['etag']

    revalidate = client.get('/plants/1', headers={'if-none-match': etag})
    assert revalidate.status_code == 304
    assert revalidate.content == b''
    assert revalidate.headers['cache-control'] == 'max-age=300'
