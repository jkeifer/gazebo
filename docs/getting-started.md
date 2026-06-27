# Getting started

> Install gazebo and stand up a minimal OGC-style API.

## Install

```sh
pip install gazebo            # core: pydantic only
pip install 'gazebo[fastapi]' # + the GazeboApp / FastAPI glue
```

Requires Python 3.12+.

## Your first app

The app below is complete and runnable. It shows the three ideas you'll use in
every gazebo service: an endpoint on a `GazeboRouter` returning a
`LinkedCollection` of deferred links; one app-scoped dependency injected by type;
and a `create_app()` factory so tests can pass overrides. (A real service would
also inject a database and a request-derived user — see
[Gazebo Gardens](example.md).)

```python
--8<-- "tests/examples/getting_started.py:app"
```

## What just happened

Four gazebo features are already at work:

- **Links resolved at serialize time.** `Link.self_link()` / `root_link()` are
  built with no request in hand; the glue fills in real URLs when the response
  serializes — see [Links](core/links.md).
- **A collection envelope.** `Things` adds `numberReturned` and a configurable
  items alias for free — see [Collections](core/collections.md).
- **By-type injection.** `settings` is resolved from the registry by its type, no
  `Depends` — see [Dependency injection](di/index.md).
- **Proxy-correct URLs.** Put this behind a load balancer and the links follow
  `X-Forwarded-*` — see [Proxy & context](fastapi/proxy.md).

## Testing it

Tests drive the app through `TestClient` and substitute config with
[`Overrides`](di/qualifiers-overrides.md#overrides) passed into `create_app` — by
parameter, never by mutating a global, so tests stay isolated:

```python
--8<-- "tests/examples/getting_started.py:test"
```

## Next

- [The core](core/index.md) — links, collections, problems, landing pages.
- [Dependency injection](di/index.md) — providers, scopes, lifecycle.
- [FastAPI integration](fastapi/index.md) — the app, routers, proxy, health.
