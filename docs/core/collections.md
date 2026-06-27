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

## Pagination links

`paginate()` returns deferred `next`/`prev` links. At serialization each takes the
current request URL and rewrites *only* the pagination query params — `token` and
`limit` by default, both configurable — preserving every other param. You own the
token semantics (opaque cursor, offset, keyset); gazebo just builds the links. The
underlying `with_query` helper is public if you need to rewrite a URL yourself.

```python
--8<-- "tests/examples/collections.py:pagination"
```

## Reference

See [`gazebo.collection`](../reference.md#gazebo.collection) and
[`gazebo.pagination`](../reference.md#gazebo.pagination).
