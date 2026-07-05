# Why gazebo

> Three things every OGC-style service ends up hand-rolling — request-dependent
> links, pagination, resource lifetimes — shown breaking in a plain FastAPI app,
> then handled by gazebo.

Machinery is easiest to judge by the code it replaces. This page takes one small
plain-FastAPI service and shows the three places it goes wrong. Every snippet is
a runnable, tested example: the "before" failures are asserted in this repo's
test suite, not imagined.

## Links make the request leak everywhere

An OGC response carries links, and a link's URL depends on the request that asked
for it: its scheme, its host, its query string. In a plain app the only way to
build a link is to hold the request — so the request goes wherever links go:

```python
--8<-- "tests/examples/why_before.py:links"
```

Two things are wrong here, one structural and one operational.

The structural one: `plant_page` is business logic, but it takes a `Request` —
and so will every function below it that ever needs to emit a link. The web
framework has leaked into the layer that should know nothing about it, and none
of that code can run (or be tested) without a request in hand.

The operational one: deploy this behind a TLS-terminating load balancer and every
link says `http://internal-host/...`. TLS ends at the proxy, so the app never
sees the public scheme or host. The test backing this snippet sends
`X-Forwarded-Proto: https` and asserts that it's ignored.

gazebo's answer is to defer the URL. `Link.self_link()` returns a link whose
href is a *callable*, resolved when the response serializes — against a request
the framework glue supplies ambiently. Business logic builds complete responses,
links included, with no request in sight. The same glue applies `X-Forwarded-*`
headers from proxies you explicitly trust, so the resolved URLs are also correct
behind the load balancer:

```python
--8<-- "tests/examples/why_after.py:app"
```

The tests behind this version assert the flip side: the same forwarded headers
now yield `https://api.example.com/plants`. How the deferral works is the
[request context](core/context.md); the model and its factories are
[Links](core/links.md); the trust policies are
[Proxy & context](fastapi/proxy.md).

## Pagination is URL surgery, repeated per endpoint

A `next` link is the current URL with the paging parameters swapped out and
everything else kept. The "everything else kept" is where hand-rolled versions
quietly fail:

```python
--8<-- "tests/examples/why_before.py:pagination"
```

Search `?q=fern`, follow the `next` link, and the filter is gone —
`replace_query_params` replaced the *whole* query string, so page two returns
different results than page one. The fix is to merge the existing params first,
remember to drop `token` on the last page, and then repeat all of that in every
paginated endpoint. It's the kind of code that's correct the day you write it
and wrong after the next refactor.

`paginate()` owns that surgery. It emits deferred `next`/`prev` (and on request
`first`/`last`/`self`) links that rewrite *only* the paging params of whatever
URL the client actually called, preserving the rest. It's the two-line branch in
the snippet above:

```python
--8<-- "tests/examples/why_after.py:paginate"
```

The token's meaning stays yours — opaque cursor, offset, keyset. See
[Collections](core/collections.md) for the cursor helpers, offset paging, and
POST-body pagination for stateless search.

## Resources have lifetimes FastAPI doesn't model

A real service holds resources that outlive any one request: a connection pool
opened at startup, a session per request, a user derived from headers. FastAPI's
`Depends` covers the per-request slice; for the rest, apps improvise — state
stashed on the app, wiring restated at each route, and tests that substitute
dependencies by mutating the application object:

```python
--8<-- "tests/examples/why_before.py:lifetimes"
```

Each line is a small liability. `app.state.pool` is untyped and invisible —
nothing declares it exists, nothing manages its teardown, and a typo'd attribute
fails at request time. Every route restates the wiring with `Depends(get_pool)`.
And `dependency_overrides` is mutation of a shared global: forget to clean it up
and the fake leaks into the next test.

gazebo gives resources one typed registry that says what builds each type and
how long it lives, delivers them to handlers as plain typed parameters, and runs
teardown when the scope closes:

```python
--8<-- "tests/examples/why_after.py:lifetimes"
```

Tests substitute by *parameter* — an `Overrides` passed into the factory, never
a mutated global — so they stay isolated and parallel-safe:

```python
--8<-- "tests/examples/why_after.py:test"
```

The container is [Dependency injection](di/index.md); the by-type route
parameters are [Routers & injection](fastapi/routers.md).

## What it doesn't cost

gazebo is a toolkit, not a framework: you still write a FastAPI app and your own
handlers, and each piece above is usable without the others. The core — links,
collections, [problems](core/problems.md), [landing pages](core/ogc.md) — is
pure pydantic with no framework import, so you can adopt a single model class
and stop there. When these three pains aren't yours, you don't need gazebo; when
they are, [Getting started](getting-started.md) is a working app in ~40 lines.
