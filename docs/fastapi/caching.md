# Conditional requests & caching

> Let clients revalidate cheaply: derive an `ETag`, honor `If-None-Match` /
> `If-Modified-Since`, and answer an unchanged resource with a bodyless `304`.

OGC services are read-heavy and lean on conditional GETs, but FastAPI gives you
nothing for them out of the box. gazebo ships the pieces — and they are strictly
**opt-in**: nothing changes until you call them in a route. The split mirrors the rest
of the library: the pure logic (hashing a value into an `ETag`, evaluating the
preconditions) is framework-free in [`gazebo.caching`](../reference.md#gazebo.caching);
the request/response plumbing is two small helpers in the FastAPI glue.

## ETags

`etag_for(value)` reduces a value — a pydantic model, a mapping, a string, or bytes —
to a hash and returns a quoted entity-tag. It is **weak** (`W/"…"`) by default, because
it hashes a *serialization*: that signals semantic equivalence, the honest strength for
a content hash. Derive the tag from the underlying data (a row, an `updated_at`), not
the link-bearing response envelope — a model with deferred links only serializes inside
a request, and you rarely want the ETag to change just because a URL did.

```python
--8<-- "tests/examples/caching.py:etag"
```

## Short-circuiting to `304`

Inside a route, build the `ETag` (and/or a `Last-Modified`), then ask `not_modified()`
whether the request's preconditions are already satisfied. If they are, it returns a
ready `304` carrying the validators — return it directly. Otherwise stamp the success
response with `set_cache_headers()` so the *next* request can be conditional. Inject the
`Response` parameter so you can set headers while still returning your model:

```python
--8<-- "tests/examples/caching.py:conditional"
```

`not_modified()` follows RFC 7232: only `GET`/`HEAD` are eligible, `If-None-Match` uses
weak comparison and takes precedence over `If-Modified-Since`, and HTTP dates are
compared at one-second resolution. When neither precondition matches it returns `None`,
so the pattern above degrades to an ordinary response.

## Reference

See [`gazebo.caching`](../reference.md#gazebo.caching) (`etag_for`, `http_date`,
`is_not_modified`) and the glue helpers
[`not_modified` / `set_cache_headers`](../reference.md#fastapi-integration).
