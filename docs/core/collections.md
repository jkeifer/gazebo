# Collections

> `LinkedCollection[T]` — the OGC collection envelope: a list of items plus
> hypermedia links and counts.

## The envelope

`LinkedCollection[T]` is the standard OGC collection wrapper: a `Sequence[T]` of
items plus a `links` list and counts. `numberReturned` is computed from the
items; `numberMatched` (the total across all pages) is optional and dropped when
unset. Because the links are deferred, the whole envelope — items, links, and all
— is built in business logic with no request in hand.

```python
--8<-- "tests/examples/collections.py:collection"
```

## Naming the items field

OGC specs name the items array differently per resource type — `features` in
Features, `records` in Records. Subclass and set the serialization alias once with
the `items_alias` class keyword; the field stays `items` in Python but serializes
under your name:

```python
class FeatureCollection(LinkedCollection[Feature], items_alias='features'):
    pass
```

Both class keywords survive generic parametrization (`FeatureCollection[P]`).

## Omitting `numberReturned`

`numberReturned` is emitted by default, but some OGC envelopes don't define it — the
`/collections` listing, for one. Turn it off per subclass with the `number_returned`
class keyword (this is exactly how the built-in [`Collections`](ogc.md#collections-extents)
envelope is defined):

```python
class Collections(LinkedCollection[Collection], items_alias='collections',
                  number_returned=False):
    pass
```

## Omitting null members

OGC omits absent members rather than emitting `null`, so an unset `numberMatched`
or `Link.title` simply doesn't appear. That behavior comes from `OmitNullModel`,
the base both `Link` and `LinkedCollection` build on. Subclass it directly when you
define your own resource models and want the same: optional fields left unset are
dropped on JSON serialization, and — unlike a hand-rolled null-dropping serializer —
the OpenAPI response schema still reflects the real fields rather than collapsing to
an opaque object.

```python
--8<-- "tests/examples/collections.py:omit_null"
```

It only drops top-level `None` members; nulls *inside* values (an open-ended
temporal interval `[start, null]`) are preserved.

## Pagination links

`paginate()` returns deferred `next`/`prev` links. At serialization each takes the
current request URL and rewrites *only* the pagination query params — `token` and
`limit` by default, both configurable — preserving every other param. You own the
token semantics (opaque cursor, offset, keyset); gazebo just builds the links. The
underlying `with_query` helper is public if you need to rewrite a URL yourself.

```python
--8<-- "tests/examples/collections.py:pagination"
```

### Opaque cursors

When you'd rather not invent a token format, `encode_cursor`/`decode_cursor` pack an
arbitrary payload into one opaque, URL-safe string. The cursor is *encoded, not
signed* — so it's opaque to clients, but always validate the decoded contents. A
malformed cursor raises a [`ParamError`](params.md) (a `400` problem via the glue).
`paginate()` also emits `first`/`last`/`self` links on request:

```python
--8<-- "tests/examples/collections.py:cursor"
```

### Offset/limit

For classic offset paging, `paginate_offset()` derives the whole
`self`/`first`/`prev`/`next`/`last` set from the current page position (and the
`total`, when known) — so `prev`/`first` appear only past the first page, and `next`/
`last` only when another page follows:

```python
--8<-- "tests/examples/collections.py:offset"
```

### POST-body pagination (stateless servers)

The builders are a thin convenience over [`Link`](links.md), not a lossy wrapper: every
generated link can carry the full `Link` surface — a `type`, `headers`, a `title` (or
any extra member, via `**link_fields`), and a `method`/`body`. That last pair is what
makes pagination work for a **POST** search on a *stateless* server: with
`method='POST'` the page token rides in the request **body** (merged into the `body` you
pass) instead of the query string, so each `next` link re-states the whole search the
server doesn't remember. The companion [`drive_pagination`](../testing/pagination.md)
test driver follows these POST `next` links by reposting that body.

```python
--8<-- "tests/examples/collections.py:post"
```

## Reference

See [`gazebo.collection`](../reference.md#gazebo.collection),
[`gazebo.pagination`](../reference.md#gazebo.pagination), and
[`OmitNullModel`](../reference.md#gazebo.serialization.OmitNullModel).
