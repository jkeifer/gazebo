"""Runnable examples backing ``docs/fastapi/app.md``."""

from __future__ import annotations

from fastapi.testclient import TestClient


# --8<-- [start:create_app]
from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Overrides, Providers

router = GazeboRouter()


@router.get('/ping')
async def ping() -> dict[str, str]:
    return {'pong': 'ok'}


def create_app(overrides: Overrides | None = None) -> GazeboApp:
    providers = Providers()
    app = GazeboApp(providers, overrides=overrides)
    app.include_router(router)
    return app


# --8<-- [end:create_app]


with TestClient(create_app()) as client:
    assert client.get('/ping').json() == {'pong': 'ok'}
    assert client.get('/health').status_code == 200  # mounted by default


# --8<-- [start:upgrade]
from fastapi import FastAPI

from gazebo.ext.fastapi import Providers, upgrade

existing = FastAPI()  # someone else's app
existing.include_router(router)
upgrade(existing, Providers())  # add gazebo's machinery in place; idempotent
# --8<-- [end:upgrade]


with TestClient(existing) as client:
    assert client.get('/ping').json() == {'pong': 'ok'}


# --8<-- [start:mount]
from fastapi import FastAPI

from gazebo.ext.fastapi import forward_lifespans

sub = create_app()  # a GazeboApp
root = FastAPI(lifespan=forward_lifespans(sub))  # run the sub-app's lifespan
root.mount('/api', sub)
# --8<-- [end:mount]


with TestClient(root) as client:
    assert client.get('/api/ping').json() == {'pong': 'ok'}


# --8<-- [start:validation_problem]
from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Providers

validating = GazeboRouter()


@validating.get('/widgets')
async def list_widgets(limit: int = 10) -> dict[str, int]:
    return {'limit': limit}


vapp = GazeboApp(Providers())
vapp.include_router(validating)

# Now GET /widgets?limit=nope fails request validation and the glue returns an
# application/problem+json 422 (see the response shape below) — no handler needed.
# --8<-- [end:validation_problem]


with TestClient(vapp) as client:
    resp = client.get('/widgets?limit=nope')
    assert resp.status_code == 422
    assert resp.headers['content-type'] == 'application/problem+json'
    problem = resp.json()
    assert problem['status'] == 422
    assert problem['errors'][0]['loc'] == ['query', 'limit']


# --8<-- [start:cors]
from gazebo.ext.fastapi import CorsConfig, GazeboApp, Providers

# cors=True is permissive (allow all origins) — handy for local development.
dev_app = GazeboApp(Providers(), cors=True)

# A list restricts to specific origins; a CorsConfig gives full control (here,
# allowing credentialed requests, which `*` cannot).
prod_app = GazeboApp(
    Providers(),
    cors=CorsConfig(
        allow_origins=['https://app.example.com'],
        allow_credentials=True,
    ),
)
# --8<-- [end:cors]


for cors_app in (dev_app, prod_app):

    @cors_app.get('/ping')
    async def _ping() -> dict[str, bool]:
        return {'ok': True}


with TestClient(dev_app) as client:
    r = client.get('/ping', headers={'origin': 'http://anywhere.test'})
    assert r.headers['access-control-allow-origin'] == '*'

with TestClient(prod_app) as client:
    r = client.get('/ping', headers={'origin': 'https://app.example.com'})
    assert r.headers['access-control-allow-origin'] == 'https://app.example.com'
    assert r.headers['access-control-allow-credentials'] == 'true'


# --8<-- [start:link_header]
from fastapi import Response

from gazebo.collection import LinkedCollection
from gazebo.ext.fastapi import GazeboApp, Providers, set_link_header
from gazebo.link import Link

hdr_app = GazeboApp(Providers())


class Items(LinkedCollection[dict], items_alias='items'):
    pass


@hdr_app.get('/items', response_model=Items)
async def list_items(response: Response) -> Items:
    links = [Link.self_link()]
    # Mirror the navigational links into an RFC 8288 Link: header. Pass a rel list
    # (e.g. rels=['self', 'next', 'prev']) to narrow it further.
    set_link_header(response, links)
    return Items(items=[{'id': 1}], links=links)


# --8<-- [end:link_header]


with TestClient(hdr_app) as client:
    resp = client.get('/items')
    assert 'rel="self"' in resp.headers['link']
