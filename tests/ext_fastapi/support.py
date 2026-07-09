"""Shared fixtures, domain types, and helpers for the FastAPI-glue test package.

The whole ``gazebo.ext.fastapi`` layer is exercised across the ``test_*.py`` modules in
this package; this module holds the pieces they share — the injectable domain types
(``Settings``/``Database``/``Session``/``User``/``Ping``), the ``build_router``/``make_app``
builders behind the common ``client`` fixture (defined in ``conftest.py``), and the OpenAPI
schema helpers. Per-concern models and fixtures live in the module that uses them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Request

from gazebo.asgi import trust_all
from gazebo.collection import LinkedCollection
from gazebo.ext.fastapi import (
    BBoxParam,
    CrsParam,
    DatetimeParam,
    GazeboApp,
    GazeboRouter,
    Inject,
    Overrides,
    Providers,
)
from gazebo.link import Link
from gazebo.params import CRS84, BBox, DatetimeInterval
from gazebo.problems import ProblemException
from gazebo.rels import Rel

# Teardown-order probe: request/app-scoped recipes append as they tear down, so a test can
# assert the request scope closed before the app scope. Cleared by the ``client`` fixture.
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

    @router.get('/stats/{triplet}/date-range', name='stats')
    async def stats(triplet: str):
        return {'triplet': triplet}

    @router.get('/templated')
    async def templated():
        return {
            'links': [
                Link.to_route(
                    'stats',
                    rel=Rel.ITEM,
                    template=['triplet'],
                    query_template=['from', 'to'],
                ),
            ],
        }

    @router.get('/bad-template')
    async def bad_template():
        # 'nope' is not a route variable of 'stats' — resolution must fail loudly.
        return {'links': [Link.to_route('stats', rel=Rel.ITEM, template=['nope'])]}

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


def params_app() -> GazeboApp:
    """An app whose ``/search`` route folds the OGC ``bbox``/``datetime``/``crs`` adapters.

    Shared by the param-adapter tests and the problem-typing test that drives the
    ``ParamError`` (a gazebo OGC adapter) path.
    """
    app = GazeboApp(Providers())

    @app.get('/search')
    async def search(
        bbox: Annotated[BBox | None, BBoxParam] = None,
        datetime: Annotated[DatetimeInterval | None, DatetimeParam] = None,
        crs: Annotated[str, CrsParam(allowed=[CRS84])] = CRS84,
    ) -> dict:
        return {
            'bbox': None if bbox is None else [bbox.minx, bbox.miny, bbox.maxx, bbox.maxy],
            'has_datetime': datetime is not None,
            'crs': crs,
        }

    return app


def openapi_params(schema: dict, path: str) -> dict:
    """The ``GET`` parameters of ``path`` in an OpenAPI ``schema``, keyed by name."""
    params = schema['paths'][path]['get']['parameters']
    return {p['name']: p for p in params}


def resolve_ref_schema(schema: dict, node: dict) -> dict:
    """Follow a ``$ref`` (an enum's reusable component) to its resolved schema, once."""
    ref = node.get('$ref')
    if ref is None:
        return node
    name = ref.rsplit('/', 1)[-1]
    return schema['components']['schemas'][name]
