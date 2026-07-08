# Request context

> The core never imports a web framework, yet link URLs depend on the live
> request. `RequestContext` is the seam that squares that — the minimal request
> surface, delivered ambiently at serialization time.

## The problem

A link's `href` often depends on the incoming request — its scheme and host, the
matched route, the current query string. But the model carrying that link is
built far from the request, down in business logic or even a pure function.
Threading the request through every layer would couple all of them to the web
framework ([Why gazebo](../why.md#links-make-the-request-leak-everywhere) shows
that coupling in code). gazebo resolves the tension by *deferring*: the href is
a callable, and the request is supplied ambiently at serialization time, through
the one small seam this page describes.

## RequestContext: the minimal surface

That seam is the `RequestContext` protocol — the minimal slice of "the request" a
link factory needs: `base_url`, `url`, `query_params`, `url_for(name, **path)`,
and `url_for_template` (which resolves a route while leaving selected variables as
RFC 6570 `{var}` expressions, backing [templated links](links.md#templated-links)).
It's a `Protocol`, so anything structurally matching it qualifies: the FastAPI glue
adapts a FastAPI `Request`, and a test can pass a hand-rolled object. Because the
protocol is `@runtime_checkable`, a conforming object must implement the whole
surface.

```python
--8<-- "tests/examples/context.py:protocol"
```

## How it's delivered

A context reaches a serializing model two ways, tried in order:

1. **The `link_context` ContextVar**, set by the framework glue for the duration
   of each request (via `use_context`). This is the normal path — handlers return
   models and the glue has already published the context.
2. **A pydantic serialization context** — `model_dump(context={'request': ctx})`
   — for when you serialize by hand, outside any request.

If neither is present, resolving a callable href raises a clear error rather than
emitting a wrong URL.

```python
--8<-- "tests/examples/context.py:resolve"
```

## Manual / test resolution

Outside a live request — a unit test, or a script rendering a document — no
ContextVar is set, so hand the context to `model_dump` as above. The object only
needs to satisfy `RequestContext`; it doesn't have to be a real request. (This is
exactly how the examples throughout these docs stay runnable.) In a running app
under the glue, you never do this by hand.

## Request id + logging (opt-in)

A separate nicety lives in the sibling module `gazebo.requestid`: a `request_id`
ContextVar with `use_request_id(value)` to bind one per request, and
`RequestIdFilter`, a logging filter that stamps each record with the active id (or
`-` outside a request) so a `%(request_id)s` format field never breaks. It's
independent of the link context above. Wiring it into middleware is shown in
[Proxy, context & health](../fastapi/proxy.md#request-id-logging).

## Reference

See [`gazebo.context`](../reference.md#gazebo.context) and
[`gazebo.requestid`](../reference.md#gazebo.requestid).
