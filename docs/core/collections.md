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

## Reference

See [`gazebo.collection`](../reference.md#gazebo.collection),
[`gazebo.pagination`](../reference.md#gazebo.pagination), and
[`OmitNullModel`](../reference.md#gazebo.jsonschema.OmitNullModel).
