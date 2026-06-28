# Landing pages & conformance

> OGC API Common building blocks: the landing page (`GET /`) and the conformance
> declaration (`GET /conformance`).

## Landing page

`LandingPage` is the OGC API Common root document (`GET /`): a `title`, a
`description`, and a `links` list (deferred `Link`s, like everywhere). It allows
extras for profile-specific members. This is the plain model; if your landing
page mirrors your router tree, the FastAPI glue can
[generate a hierarchical one for you](../fastapi/routers.md#hierarchical-landing-pages-linkedrouter)
instead of your building it by hand.

```python
--8<-- "tests/examples/ogc.py:landing"
```

## Conformance

A service advertises which OGC conformance classes it implements at
`GET /conformance`. The `Conformance` registry collects the class URIs —
construct it with some, `.add()` more — and `.declaration()` produces a
`ConformanceDeclaration` that serializes as `conformsTo`. Common Common-spec URIs
are bundled as constants (`Conformance.CORE`, `LANDING_PAGE`, `JSON`, `OAS30`,
`HTML`).

```python
--8<-- "tests/examples/ogc.py:conformance"
```

## Collections & extents

Right after the landing page, the OGC API Common endpoints are `/collections`
(a list) and `/collections/{id}` (one collection's metadata). `Collection`
describes a dataset — `id`, `title`, `description`, an `extent`, an `itemType`
(serialized as `itemType`), the `crs` list (defaulting to
[`CRS84`](params.md)), and `links`. `Extent` carries an optional
`SpatialExtent` (one or more bounding boxes in a CRS) and `TemporalExtent` (one or
more `[start, end]` intervals in a temporal RS, `null` meaning open). `Collections`
is the `/collections` envelope — a [`LinkedCollection`](collections.md) whose items
serialize under `collections`:

```python
--8<-- "tests/examples/ogc.py:collection"
```

For the actual feature items of a collection, see [GeoJSON](geojson.md).

## Reference

See [`gazebo.ogc`](../reference.md#gazebo.ogc).
