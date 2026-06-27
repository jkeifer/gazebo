# FastAPI integration

> `gazebo.ext.fastapi` turns a `Providers` registry into a working FastAPI app:
> by-type injection into routes, a published request context, problem handlers,
> proxy-correct URLs, and health. Requires the `gazebo[fastapi]` extra.

## What the glue does

`gazebo.ext.fastapi` is the only part of gazebo that imports FastAPI. It turns a
[`Providers`](../di/index.md) registry into a running app. On each request it:

- opens a DI **request scope** and seeds it with the request;
- publishes the link [`RequestContext`](../core/context.md), so deferred links in
  the response resolve to real URLs;
- resolves bound types injected into route parameters;
- renders any `ProblemException` as problem+json.

At startup it opens the **app scope** and validates that the routes and the
dependency graph are wired correctly.

## In this section

- [GazeboApp & upgrade](app.md) — constructing or retrofitting an app.
- [Routers & injection](routers.md) — `GazeboRouter`, `Inject`, `LinkedRouter`.
- [Proxy & context](proxy.md) — forwarded headers, trust, request id, health.

## Composition

gazebo's request machinery lives on `GazeboApp` (or [`upgrade()`](app.md));
bare-type injection lives on `GazeboRouter`. They're a pair — use both. Routers
that don't use gazebo injection (plain or third-party `APIRouter`s) drop into a
`GazeboApp` unchanged. The combinations:

| Combination | Works? |
|---|---|
| `GazeboApp` + `GazeboRouter` (injection) | ✅ the intended pairing |
| `GazeboApp` + plain/external `APIRouter` (no injection) | ✅ |
| plain `FastAPI` + `GazeboRouter` with injection | ❌ needs `GazeboApp`'s middleware |
| root `FastAPI` mounting a `GazeboApp` | ✅ forward the sub-app's lifespan |

## Reference

See [`gazebo.ext.fastapi`](../reference.md#fastapi-integration).
