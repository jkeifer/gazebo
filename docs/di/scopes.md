# Scopes & lifecycle

> A resource's lifetime shouldn't be hardcoded into its class — the same type
> can live per-process or per-request depending on the app. Scope is a wiring
> decision, bound in the registry; `app` and `request` ship by default.

## app vs request

Scope is a wiring decision, not a property of the type — the same class can be
app- or request-scoped depending on how you bind it.

- **`app`** resources are built once when the app scope opens and torn down at
  shutdown: database pools, HTTP clients, settings.
- **`request`** resources are built once per operation and torn down when it
  ends: the request-derived user, a database session.

"Request" is really *operation* scope — the per-unit-of-work lifetime, which in an
HTTP app is the request.

## Lifecycle & teardown

Each entered scope owns a resolution cache and an `AsyncExitStack`. A type is
built at most once per scope (the cache), and any generator or context-manager
recipe has its teardown run when the scope closes, in reverse order of creation.
Under the FastAPI glue the app scope builds **every** app-scoped provider eagerly
when it opens, so a misconfigured resource fails at startup rather than on the first
request. (Standalone users who want reachability-based pruning can pass
`open_app_scope(eager=...)` to build only the providers reachable from a set of entry
types — dead-provider elimination — but the glue deliberately builds them all, since a
resource may be reached only via `__health__` or a manual `app_state.get`.)

## Scope roots

A scope may carry a *root* object — for the request scope, the request itself. A
recipe parameter typed as the root receives it directly, with no binding. This is
how request-derived dependencies read the incoming request:

```python
--8<-- "tests/examples/scopes.py:request_dep"
```

The [FastAPI glue](../fastapi/index.md) seeds the request root with the FastAPI
`Request`, so a `__provide__` can take `request: Request` and read headers, path
params, or the body.

## Startup validation

When the `Container` is built it validates the whole dependency graph and raises
immediately on:

- an unbound dependency with no default (`UnresolvedDependencyError`);
- a **scope mismatch** — an app-scoped recipe depending on a request-scoped type,
  which would outlive its dependency (`ScopeMismatchError`);
- a cycle (`CircularDependencyError`).

These are startup failures, not per-request surprises — a wiring mistake stops
the app from booting.

## Health checks

Any resource may expose a `__health__()` method (sync or async). `GazeboApp`'s
[`/health` endpoint](../fastapi/proxy.md#health) probes every app-scoped resource
that has one and reports a per-resource and aggregate status — readiness falls out
of the resources you already built.

## Reference

See [`gazebo.di.container`](../reference.md#dependency-injection).
