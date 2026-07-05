# GeoJSON

> OGC Features items are GeoJSON, but plain GeoJSON models have no `links`,
> counts, or top-level `bbox`. These `Feature`/`FeatureCollection` models add
> gazebo's hypermedia surface to validated RFC 7946 geometry.

!!! note "Optional extra"
    The GeoJSON models live behind the `gazebo[geojson]` extra — install it to
    `import gazebo.geojson`. They build on
    [`geojson-pydantic`](https://github.com/developmentseed/geojson-pydantic) for
    coordinate-validated geometry (the seven GeoJSON geometry types are
    re-exported), so the core dependency footprint stays pydantic-only.

The item payloads of an OGC Features collection are GeoJSON. `gazebo.geojson`
reuses geojson-pydantic for the geometry/feature shapes — the tedious,
easy-to-get-subtly-wrong coordinate validation — and layers gazebo's deferred
links on top:

- `Feature[P]` is generic over its `properties` model `P`, inherits geometry
  validation, and adds a `links` array.
- `FeatureCollection[P]` is a [`LinkedCollection`](collections.md), so it carries
  `links`, `numberReturned`/`numberMatched`, and an optional top-level `bbox` —
  none of which geojson-pydantic's own collection has. Items serialize under the
  GeoJSON `features` key.

```python
--8<-- "tests/examples/geojson.py:feature"
```

Because `FeatureCollection` is a `LinkedCollection`, the same deferred-link
machinery applies: build it in business logic with no request in hand, and the
hrefs resolve at serialization. Pair it with the
[query-parameter adapters](params.md) for `bbox`/`datetime`/`crs` filtering and the
[`Collection`/`Extent`](ogc.md#collections-extents) metadata models to stand up a
full OGC Features collection — see the [garden example](../example.md).

## Reference

See [`gazebo.geojson`](../reference.md#gazebo.geojson).
</content>
