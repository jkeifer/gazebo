# Filtering

> Supporting `filter` means much more than parsing CQL2: validating what's
> filterable, advertising it at `/queryables`, handling `sortby`, rejecting bad
> input as a `400`. gazebo adopts a parser and supplies everything around it.

Filtering is the largest and most-reimplemented slice of request-side OGC
machinery: parsing CQL2, validating that a filter only touches filterable
fields, advertising which fields those are, and applying `sortby`.
`gazebo.filtering` owns that **plumbing** — and deliberately does *not* own a
CQL2 parser. Writing one (comparison, logical, spatial, temporal, and array
operators, across two encodings) is a large, perpetual maintenance burden that
mature libraries already carry. So gazebo **adopts** a CQL2 engine behind a
narrow seam and spends its effort on the parts no library provides.

The bundled engine adapts [cql2-rs](https://pypi.org/project/cql2/); install it with
the extra:

```sh
pip install 'gazebo[cql2]'
```

## Queryables from your model

A queryables resource *is* a JSON Schema, and pydantic already emits JSON Schema — so
the `/queryables` body **and** the filter allow-list both fall out of the model you
already wrote. Nested models flatten to dotted accessors (`location.lat`), so nested
data is filterable; geometry fields are advertised as spatial queryables; arrays
surface their item type. [`sortables_from_model`](../reference.md#gazebo.filtering) is
the scalar subset — the fields that have a total order to sort by.

```python
--8<-- "tests/examples/filtering.py:queryables"
```

The resulting property-name set is the authoritative artifact: a filter that
references anything outside it is rejected before evaluation. Everything else the
schema carries (types, enums, formats, constraints) is advisory metadata for clients.

## In a route

The FastAPI adapters mirror the [query-parameter](params.md) idiom: `FilterParam(queryables)`
and `SortByParam(sortables)` drop into a route signature as `Annotated` metadata. A
malformed filter, an unknown property, an unsupported `filter-crs`, or a non-sortable
`sortby` field each short-circuit to a `400 application/problem+json` before your
handler runs; a valid filter arrives as a ready-to-use
[`Filter`](../reference.md#gazebo.filtering).

```python
--8<-- "tests/examples/filtering.py:route"
```

[`Filter.matches`](../reference.md#gazebo.filtering) is the in-memory convenience used
above; it inherits SQL `WHERE` semantics — a row whose referenced property is absent or
null simply doesn't match (rather than raising), so it is safe to use directly over
sparse data. For a database backend, reach through to the engine-native expression on
`filter.compiled` (the cql2 adapter exposes `.native` for `to_sql()` and friends)
instead of evaluating in Python.

!!! note "`?f=` filter language and CRS"
    `filter-lang` selects the encoding (`cql2-text` or `cql2-json`); when omitted it is
    inferred from the value. `filter-crs` is validated against an allow-list (default
    [`CRS84`](../reference.md#gazebo.params.CRS84)) — like `CrsParam`, validating a CRS
    is not reprojecting it, so only advertise a CRS whose geometries you actually handle.

## Bringing your own engine

gazebo ships exactly one engine but keeps the
[`FilterEngine`](../reference.md#gazebo.filtering) Protocol open. The seam is what keeps
the core free of the CQL2 dependency, so it costs nothing to leave it usable: pass any
object implementing `compile(...) -> Compiled` as `FilterParam(..., engine=...)` to back
filtering with a different CQL2 implementation, without gazebo bundling a second one.

The garden example wires all of this into its `GET /collections/beds/items` endpoint,
with `/collections/beds/queryables` and `/collections/beds/sortables`.

## Reference

See [`gazebo.filtering`](../reference.md#gazebo.filtering), the engine adapter in
[`gazebo.filtering.cql2`](../reference.md#gazebo.filtering.cql2), and the `FilterParam` /
`SortByParam` adapters in [`gazebo.ext.fastapi`](../reference.md#fastapi-integration).
