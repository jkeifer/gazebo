"""Runnable examples backing ``docs/fastapi/routers.md``."""

from __future__ import annotations

from typing import Annotated

from fastapi.testclient import TestClient

from gazebo.ext.fastapi import GazeboApp, Providers


# --8<-- [start:injection]
from dataclasses import dataclass

from gazebo.ext.fastapi import GazeboRouter


@dataclass
class Catalog:
    name: str = 'default'

    @classmethod
    def __provide__(cls) -> Catalog:
        return cls()


router = GazeboRouter()


@router.get('/things')
async def list_things(catalog: Catalog, limit: int = 10) -> dict:
    # `catalog` is injected by type; `limit` stays an ordinary query parameter.
    return {'catalog': catalog.name, 'limit': limit}


# --8<-- [end:injection]


# --8<-- [start:inject_marker]
from gazebo.ext.fastapi import Inject


class Session:  # external type, no __provide__
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog


def provide_session(catalog: Catalog) -> Session:
    return Session(catalog)


@router.get('/items')
async def list_items(session: Annotated[Session, Inject]) -> dict:
    return {'via': session.catalog.name}


# --8<-- [end:inject_marker]


def _build() -> GazeboApp:
    providers = Providers().app(Catalog).request(Session, provide_session)
    app = GazeboApp(providers)
    app.include_router(router)
    return app


with TestClient(_build()) as client:
    assert client.get('/things?limit=5').json() == {'catalog': 'default', 'limit': 5}
    assert client.get('/items').json() == {'via': 'default'}


# --8<-- [start:linked_router]
from gazebo.ext.fastapi import LinkedRouter
from gazebo.rels import Rel

root = LinkedRouter(title='API', landing_name='landing')
collections = LinkedRouter(
    prefix='/collections',
    rel=Rel.DATA,
    title='Collections',
    landing_name='collections',
)
root.include_router(collections)  # adds a link to the child's landing page
# --8<-- [end:linked_router]


def _build_linked() -> GazeboApp:
    app = GazeboApp(Providers())
    app.include_router(root)
    return app


with TestClient(_build_linked()) as client:
    rels = [link['rel'] for link in client.get('/').json()['links']]
    assert 'data' in rels
