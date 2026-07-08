# Links

> Link URLs depend on the request — its host, its routes, its query string — but
> responses are built far from any request. `Link` defers the URL: the href can
> be a callable, resolved at serialization time.

Every hypermedia response is full of URLs only the live request can determine,
and holding a request in your business logic just to format them couples every
layer to the web framework (and breaks the moment the app sits behind a proxy —
[Why gazebo](../why.md#links-make-the-request-leak-everywhere) shows this going
wrong in code). `Link` removes the coupling: build links anywhere, and let them
resolve when the response serializes.

## Deferred hrefs

`Link.href` accepts either a concrete URL or a `UrlResolver`: a callable taking
the [request context](context.md) and returning a URL. A resolver href is invoked
during JSON serialization, which is what lets you build the link far from any
request:

```python
--8<-- "tests/examples/links.py:self_link"
```

## The Link model

Beyond `href`, a `Link` carries the usual OGC/Atom members — `rel`, `type`,
`title`, `method`, `headers`, `body` — and allows extras (`extra='allow'`) for
anything a profile defines. `None` fields are dropped on JSON serialization, so
an unset `title` simply doesn't appear. See the
[reference](../reference.md#gazebo.link.Link) for the full field list.

## Factories

You rarely spell out a `rel` and a resolver by hand. Three classmethods cover the
common links, each deferred so it resolves against the live request:

| Factory | Builds a link to | Resolves via |
|---|---|---|
| `Link.self_link()` | the current request URL | `ctx.url` |
| `Link.root_link()` | the landing page | `ctx.url_for('landing')` |
| `Link.to_route(name, rel=...)` | a named route | `ctx.url_for(name, **path)` |

```python
--8<-- "tests/examples/links.py:factories"
```

For a route with path parameters, pass them as the `path` mapping
(`Link.to_route('plant', rel=Rel.ITEM, path={'id': 1})`). Those values are bound
into the deferred resolver and handed to `ctx.url_for` at serialization time —
they are *not* stored as fields on the link, so they never appear in the emitted
JSON.

## Templated links

Sometimes a link's URL isn't fully known even to the server: the client supplies
the final path segment, or a set of optional query filters. Rather than resolve
those, `to_route` can leave chosen variables *unbound* as RFC 6570 `{var}`
expressions and mark the link `templated: true`, so the client expands it. Pass
`template` for path-position variables and `query_template` for form-query
variables — the latter is appended as `{?a,b}` (or `{&a,b}` when the resolved
base already carries a query string):

```python
--8<-- "tests/examples/links.py:templated"
```

Path variables you *do* know still go in `path` and are resolved normally;
`template` is only for the ones you want the client to fill in. A plain
`to_route` call (no `template`/`query_template`) serializes exactly as before,
with no `templated` member. Under the FastAPI glue the unbound path variables are
resolved through the real router, so the emitted template stays proxy-correct
(scheme, host, and root path intact).

## Resolving without a request

A link only serializes to a real URL when a context is available. Under the
[FastAPI glue](../fastapi/index.md) that's automatic for every response. For a
manual dump, pass the context (see [request context](context.md)); with no
context available, a callable href raises a clear error instead of emitting a
broken link.

## Reference

See [`gazebo.link`](../reference.md#gazebo.link).
