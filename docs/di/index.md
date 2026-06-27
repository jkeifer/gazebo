# Dependency injection

> `gazebo.di` — a small, typed, framework-agnostic injection container. Stdlib
> only; it never imports gazebo's OGC code or any web framework.

## Why a container

As a service grows it accumulates resources with lifetimes: a database pool opened
once at startup, a session per request, a user and tenant derived from each
request's headers. Wiring these by hand means threading objects through call
sites; FastAPI's `Depends` handles per-request needs but has no app-lifetime scope
and leans on global state for test substitution. `gazebo.di` gives you:

- one **central, typed registry** of what builds each resource and how long it lives;
- **deterministic teardown** for anything that needs closing;
- **test overrides by parameter**, never by mutating a global.

It's stdlib-only and framework-agnostic — usable on its own, and driven per
request by the [FastAPI glue](../fastapi/index.md).

## The mental model

Five terms carry the whole system:

- **Recipe** — a callable that builds a value, keyed by the type it produces.
  Often a `__provide__` classmethod on the type itself.
- **Binding** — a recipe plus the scope it lives in.
- **Scope** — a named lifetime: `app` (once per process) or `request` (once per
  operation).
- **Qualifier** — disambiguates two bindings of the same type (primary vs replica).
- **Root** — a scope's seed object (the request, for the request scope),
  injectable by type.

Resolution is by type and recursive: to build a value, the container builds each
of its typed parameters first.

## In this section

- [Providers & recipes](providers.md) — registering what builds each type.
- [Scopes & lifecycle](scopes.md) — `app` vs `request`, teardown, health, validation.
- [Qualifiers & overrides](qualifiers-overrides.md) — duplicate types and test substitution.

## Standalone use

The container needs no web framework: `Container.open_app_scope()` and
`open_request_scope()` drive it directly (that's how the tested examples here run).
In a web app the [FastAPI glue](../fastapi/index.md) opens those scopes for you —
the app scope in the lifespan, a request scope per request.

## Reference

See [`gazebo.di`](../reference.md#dependency-injection).
