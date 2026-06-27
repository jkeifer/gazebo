# gazebo

[![Documentation](https://github.com/jkeifer/gazebo/actions/workflows/docs.yml/badge.svg)](https://teotl.dev/gazebo/)

Everything needed to build OGC-style APIs, under one roof.

gazebo packages the recurring machinery of OGC-style services so it doesn't get
re-implemented per project:

- **Deferred links** — a `Link` model whose `href` can be a callable resolved at
  serialization time, so links are built without a request in hand.
- **Collection envelopes** — `LinkedCollection[T]`: items + links + counts, with a
  configurable items alias (`features`, `records`, ...).
- **Typed injection & state** — a small, framework-agnostic DI container
  (`gazebo.di`) plus a FastAPI app (`GazeboApp`) that delivers app- and
  request-scoped resources as typed parameters, with teardown and
  parameter-based (not global-mutation) test overrides.
- **Proxy-aware URLs** — pure-ASGI middleware that honors
  `X-Forwarded-Proto/Host/Prefix` (with pluggable trust), so generated links are
  correct behind a load balancer.
- **OGC bits** — RFC 7807 problem responses, landing pages + conformance,
  pagination links, and typed `Rel`/`MediaType` constants.

The core (`gazebo`) depends only on `pydantic`. Framework integration is opt-in.

> ![NOTE]
> This is an experiment using AI to refine a number of patterns I've
> established building out APIs over the years. The current implementation
> mainly targets use with FastAPI, but I've tried to keep the core abstractions
> agnostic to the framework, and recognize FastAPI is not the only framework
> that could value from these things.
>
> I acknowledge the documentation is AI slop and does not clearly express the
> value of these abstractions, but I think the code, while an early version and
> subject to change, is solid and solves some key problems in convenient and
> clever ways. The primary goals are to reduce boilerplate and make
> implementing more robust patterns easier, and I think those goals are
> realized here.

## Install

```sh
pip install gazebo            # core: pydantic only
pip install 'gazebo[fastapi]' # + the GazeboApp / FastAPI glue
```

Requires Python 3.12+.

## Quickstart

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Request

from gazebo.collection import LinkedCollection
from gazebo.link import Link
from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Inject, Overrides, Providers


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

External types you can't add `__provide__` to are bound with a standalone
provider and injected with `Annotated[T, Inject]`:

```python
@asynccontextmanager
async def provide_session(database: Database) -> AsyncIterator[Session]:
    async with database.session() as s:
        yield s

providers.request(Session, provide_session)

@router.get('/x')
async def handler(session: Annotated[Session, Inject]): ...
```

## Composition

gazebo's request machinery (typed injection + proxy-correct link context) lives in
`GazeboApp`; routes that use bare-type injection live on a `GazeboRouter`. They are
a pair — use both. Beyond that, you can mix and match:

| Combination | Works? |
|---|---|
| `GazeboApp` + `GazeboRouter` (injection) | ✅ the intended pairing |
| `GazeboApp` + plain/external `APIRouter` (no injection) | ✅ |
| plain `FastAPI` + `GazeboRouter` with injection | ❌ needs `GazeboApp`'s middleware |
| root `FastAPI` mounting a `GazeboApp` | ✅ forward the sub-app's lifespan |

**External / third-party routers** that don't use gazebo injection can be included
into a `GazeboApp` unchanged. If you accidentally put an injectable-typed route on a
plain `APIRouter`, the app fails loudly at startup naming the route (rather than
silently treating the parameter as a request body).

**Upgrade an existing app** you didn't construct (created by a framework, or with
custom config) instead of subclassing:

```python
from fastapi import FastAPI
from gazebo.ext.fastapi import upgrade, GazeboRouter, Providers

app = FastAPI(...)              # someone else's app
app.include_router(my_gazebo_router)
upgrade(app, providers)         # adds the middleware, lifespan, handlers, health
```

**Mount a `GazeboApp` under a root app.** A mounted sub-app's lifespan isn't run
automatically, so forward it (this is general framework behavior, not
gazebo-specific):

```python
from gazebo.ext.fastapi import forward_lifespans

root = FastAPI(lifespan=forward_lifespans(sub_app))
root.mount('/api', sub_app)     # sub_app is a GazeboApp
```

## Example app

[`examples/garden/`](examples/garden/) is **Gazebo Gardens** — a complete,
standalone OGC-style API (a multi-tenant plant catalog) that exercises every
feature: injection with app/request scopes and teardown, qualified bindings,
deferred + paginated links, collection envelopes, RFC 7807 problems, hierarchical
landing pages, conformance, proxy-aware URLs, health, and request-id logging. It's
its own project with its own `pyproject.toml`, so:

```sh
cd examples/garden
uv run garden          # serve on http://127.0.0.1:8000
uv run pytest          # its test suite
```

See [`examples/garden/README.md`](examples/garden/README.md) for a feature map and
`curl` recipes.

## Design docs

- `docs/design.md` — the OGC/web shapes (links, collections, pagination,
  problems, landing pages, proxy headers).
- `docs/design-di.md` — the injection & state system (providers, recipes,
  scopes, `GazeboApp`).
- `docs/examples/` — `wiring.py` (stock FastAPI baseline) and
  `wiring_gazeboapp.py` (the gazebo version).

## Status

Early / pre-1.0. The `gazebo.di` container is intentionally minimal and
extraction-ready (stdlib only); it sits behind a `Providers` interface so a
mature container could be adopted later without changing user code.
