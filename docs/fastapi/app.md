# GazeboApp & upgrade

> Two ways to get gazebo's machinery onto a FastAPI app: construct a `GazeboApp`,
> or `upgrade()` an app you didn't create.

## GazeboApp

`GazeboApp(providers, *, overrides=None, trust=trust_none, health_path='/health',
**fastapi_kwargs)` is a thin `FastAPI` subclass wired from a registry. It opens
the app scope in its lifespan, installs the request-scope and proxy-headers
middleware, registers the problem handlers, and mounts `/health` — and otherwise
*is* a FastAPI app, so any `FastAPI(...)` keyword passes straight through. It
exposes `.container` and `.app_state` for introspection. Build it behind a
`create_app()` factory so tests can pass
[`Overrides`](../di/qualifiers-overrides.md#overrides):

```python
--8<-- "tests/examples/app.py:create_app"
```

## upgrade() an existing app

When you don't construct the app — it's made by a framework, or needs custom
`FastAPI(...)` config you'd rather not route through a subclass — call
`upgrade(app, providers, ...)` to apply the same machinery in place: it wraps the
lifespan, installs the middleware, registers the handlers, rewrites `@app.get`
routes for injection, and adds `/health`. Same options as `GazeboApp`, and
idempotent (calling it twice is a no-op).

```python
--8<-- "tests/examples/app.py:upgrade"
```

## Problem & validation responses

`GazeboApp` and `upgrade()` register two exception handlers so every error
response is `application/problem+json` (see [Problems](../core/problems.md)):

- `problem_exception_handler` renders any [`ProblemException`](../core/problems.md)
  you raise with its status and detail.
- `validation_exception_handler` maps FastAPI's `RequestValidationError` to a
  `422` problem, carrying the field-level errors under an `errors` extension
  member (RFC 9457). Without this, bad input would return FastAPI's default
  `{"detail": [...]}` shape and break problem+json uniformity.

The second is automatic — you write nothing for it:

```python
--8<-- "tests/examples/app.py:validation_problem"
```

A bad request then yields:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "request validation failed: 1 error(s)",
  "errors": [{"type": "int_parsing", "loc": ["query", "limit"], "msg": "..."}]
}
```

## CORS

OGC APIs are usually consumed from a browser, so cross-origin requests matter.
CORS is **off by default** (an open policy is a security smell to ship silently);
opt in with the `cors=` argument to `GazeboApp`/`upgrade()`:

- `cors=True` — a permissive policy (any origin, no credentials), fine for local
  development.
- `cors=['https://app.example.com', ...]` — restrict to an explicit origin list.
- `cors=CorsConfig(...)` — full control (methods, headers, credentials, `max_age`).
  Note that `allow_origins=['*']` with `allow_credentials=True` is rejected by
  browsers, so credentials default off.

The middleware is installed outermost, so even a problem+json error response
carries the CORS headers.

```python
--8<-- "tests/examples/app.py:cors"
```

## Mounting under a root app

A mounted sub-app's lifespan isn't run automatically, so a mounted `GazeboApp`
would never open its app scope. Set the root app's `lifespan` to
`forward_lifespans(sub_app)` to run it. This is general framework behavior, not
gazebo-specific — but it's the one wiring step that's easy to miss.

```python
--8<-- "tests/examples/app.py:mount"
```

## Reference

See [`gazebo.ext.fastapi`](../reference.md#fastapi-integration)
(`GazeboApp`, `upgrade`, `forward_lifespans`).
