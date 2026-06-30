# gazebo

[![Documentation](https://github.com/jkeifer/gazebo/actions/workflows/docs.yml/badge.svg)](https://teotl.dev/gazebo/)

Everything needed to build OGC-style APIs, under one roof.

gazebo packages the recurring machinery of OGC-style services so it doesn't get
re-implemented per project:

- **Deferred links** — a `Link` model whose `href` can be a callable resolved at
  serialization time, so links are built without a request in hand.
- **Collection envelopes** — `LinkedCollection[T]`: items + links + counts, with a
  configurable items alias (`features`, `records`, ...), plus first-class GeoJSON
  `Feature`/`FeatureCollection` for OGC API Features.
- **Typed injection & state** — a small, framework-agnostic DI container
  (`gazebo.di`) plus a FastAPI app (`GazeboApp`) that delivers app- and
  request-scoped resources as typed parameters, with teardown and
  parameter-based (not global-mutation) test overrides.
- **Proxy-aware URLs** — pure-ASGI middleware that honors
  `X-Forwarded-Proto/Host/Prefix` (with pluggable trust), so generated links are
  correct behind a load balancer.
- **The OGC request/response surface** — RFC 7807 problems (with a reusable
  `ProblemType`/`ProblemRegistry` catalog of stable, linkable `type` URIs),
  landing pages + conformance (a `RootRouter` that emits `service-desc`/
  `service-doc` and derives its conformance declaration from the running app),
  pagination, content negotiation (`?f=` then `Accept`), typed OGC query params
  (`bbox`/`datetime`/`crs`), CQL2 filtering + `sortby`, conditional requests
  (ETag / 304), RFC 8288 `Link:` headers, and typed `Rel`/`MediaType` constants.
- **A pytest plugin** — opt-in helpers that assert the OGC-ness of your service:
  link/problem assertions and a pagination driver that walks `next` to exhaustion.

The core (`gazebo`) depends only on `pydantic`. Framework integration, GeoJSON, CQL2
filtering, a self-documenting serve CLI, and the test helpers are opt-in extras.

> [!NOTE]
> This is an experiment using AI to refine a number of patterns I've
> established building out APIs over the years. The current implementation
> mainly targets use with FastAPI, but I've tried to keep the core abstractions
> agnostic to the framework, and recognize FastAPI is not the only framework
> that could value from these things.
>
> I acknowledge the documentation is AI slop and does not clearly express the
> value of these abstractions, but I think the code, while an early version and
> subject to change, is mostly solid and solves some key problems in convenient
> and clever ways. The primary goals are to reduce boilerplate and make
> implementing more robust patterns easier, and I think those goals are
> realized here. Some features are more experimental than others, but I think
> everything in here is potentially useful. If not, let me know why. If
> problems arise, tell me. Issues and pull requests are excellent vehicles for
> feedback.

## Install

```sh
pip install gazebo             # core: pydantic only
pip install 'gazebo[fastapi]'  # + the GazeboApp / FastAPI glue
pip install 'gazebo[cli]'      # + a self-documenting uvicorn serve CLI
pip install 'gazebo[geojson]'  # + GeoJSON Feature / FeatureCollection
pip install 'gazebo[cql2]'     # + CQL2 filtering (cql2-rs engine)
pip install 'gazebo[test]'     # + the pytest plugin
```

Requires Python 3.12+. Full documentation lives at
[teotl.dev/gazebo](https://teotl.dev/gazebo/).

## Quickstart

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Request

from gazebo.collection import LinkedCollection
from gazebo.link import Link
from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Overrides, Providers


@dataclass
class Settings:
    dsn: str = 'postgres://localhost/app'

    @classmethod
    def __provide__(cls) -> 'Settings':
        return cls()


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @classmethod
    @asynccontextmanager
    async def __provide__(cls, settings: Settings) -> AsyncIterator['Database']:
        db = cls(settings.dsn)
        try:
            yield db          # built once (app scope); teardown on shutdown
        finally:
            ...               # await db.close()


@dataclass
class User:                   # request-scoped; derives from the request
    name: str

    @classmethod
    async def __provide__(cls, request: Request) -> 'User':
        return cls(request.headers.get('authorization', 'anon'))


class Things(LinkedCollection[dict], items_alias='things'):
    pass


router = GazeboRouter()


@router.get('/things', response_model=Things)
async def list_things(db: Database, user: User, limit: int = 10):
    items = [{'id': i, 'owner': user.name} for i in range(limit)]
    return Things(items=items, links=[Link.self_link(), Link.root_link()])


def create_app(overrides: Overrides | None = None) -> GazeboApp:
    providers = Providers()
    providers.app(Settings).app(Database).request(User)
    app = GazeboApp(providers, overrides=overrides)
    app.include_router(router)

    @app.get('/', name='landing')
    async def landing():
        return {'service': 'things'}

    return app


app = create_app()
```

`db` and `user` are injected by type — `db` once per app, `user` per request.
Tests override by parameter, never by mutating a global:

```python
from fastapi.testclient import TestClient

def test_things():
    overrides = Overrides().set(Settings, Settings(dsn='sqlite://'))
    with TestClient(create_app(overrides)) as client:
        body = client.get('/things?limit=2', headers={'authorization': 'alice'}).json()
        assert body['numberReturned'] == 2
```

`GazeboApp` and `GazeboRouter` are an intended pair, but you can mix in plain or
third-party routers, `upgrade()` an app you didn't construct, and mount a `GazeboApp`
under a root app. The [documentation](https://teotl.dev/gazebo/) covers composition,
injecting external types, content negotiation, conditional requests, and the rest.

## Example app

[`examples/garden/`](examples/garden/) is **Gazebo Gardens** — a complete,
standalone OGC-style API (a multi-tenant plant catalog) that exercises every
feature: injection with app/request scopes and teardown, qualified bindings,
deferred + paginated links, collection envelopes, RFC 7807 problems with a
`ProblemType` catalog, CQL2 filtering and `sortby`, a `RootRouter` service landing
with conformance, proxy-aware URLs, health, and request-id logging. It's
its own project with its own `pyproject.toml`, so:

```sh
cd examples/garden
uv run garden          # serve on http://127.0.0.1:8000
uv run pytest          # its test suite
```

See [`examples/garden/README.md`](examples/garden/README.md) for a feature map and
`curl` recipes.

## Docs

Full documentation — guides, how-tos, and the generated API reference — lives at
**[teotl.dev/gazebo](https://teotl.dev/gazebo/)**.
