# Query parameters

> `bbox`, `datetime`, and `crs` look like simple query params and are anything
> but. Typed parsers that get the edge cases right — and turn bad input into a
> `400` problem instead of a wrong answer.

OGC APIs share a small set of standardized query parameters, and parsing them
correctly (RFC 3339 intervals, antimeridian-crossing bounding boxes, CRS
allow-lists) is the most-reimplemented, easiest-to-get-subtly-wrong slice of an
OGC service. `gazebo.params` is the framework-agnostic core: pydantic models with
`parse` classmethods that raise [`ParamError`](../reference.md#gazebo.params.ParamError)
on malformed input. The [FastAPI adapters](#in-a-route) wire them into a route and
render that error as `application/problem+json` with a `400` status — the OGC
convention for a bad query parameter (distinct from request-*body* validation,
which is a `422`).

## Parsing directly

Each model parses a raw string. `BBox` accepts the 4-coordinate 2D form or the
6-coordinate 3D form, and allows `minx > maxx` to denote a box crossing the
antimeridian. `DatetimeInterval` accepts an RFC 3339 instant or a `start/end`
interval, where either side may be open (`..` or empty):

```python
--8<-- "tests/examples/params.py:parse"
```

`DatetimeInterval.contains()` answers whether a timestamp falls within the
(possibly half-open) interval; an instant is represented as `start == end`.

## In a route

The glue ships ready-made adapters — `BBoxParam`, `DatetimeParam`, and the
`CrsParam(allowed=[...])` factory — that drop into a route signature as `Annotated`
metadata. A malformed value short-circuits to a `400` problem before your handler
runs; a valid one arrives already typed:

```python
--8<-- "tests/examples/params.py:route"
```

`CrsParam` validates the supplied CRS URI against the allow-list (a value outside it
is a 400). Pass `name='bbox-crs'` for the companion parameter. When the parameter is
**absent**, what it resolves to depends on what a default can reasonably be:

- an explicit `default=` (which must itself be in `allowed`), if you pass one; else
- [`CRS84`](../reference.md#gazebo.params.CRS84) (the OGC default output CRS: WGS 84,
  lon/lat) if it is in `allowed`; else
- nothing — with a non-default allow-list and no marked default there is no safe
  assumption, so `crs` becomes **required** and an absent value is a 400.

In other words: as soon as you offer CRSs that don't include CRS84, you must either
mark one as the `default` or require the caller to choose.

!!! warning "Validating a CRS is not reprojecting it"
    `CrsParam` only checks the requested CRS is in your allow-list; it does **not**
    transform coordinates. If you add a second CRS to `allowed=[...]`, your handler
    must actually reproject its output (and the `bbox` input) into that CRS —
    otherwise you will accept the request and return coordinates in the wrong
    reference system. Only advertise a CRS you genuinely serve.

`BBox` is deliberately CRS-agnostic: it validates the coordinate **count** and that
`miny <= maxy` (and `minz <= maxz`), and it allows `minx > maxx` (a box crossing the
antimeridian). It does *not* range-check latitude/longitude, since the axis meanings
depend on the CRS.

Because the box owns the antimeridian-wrap rule, it also answers the containment
question so consumers don't re-derive it: `BBox.contains(lon, lat)` returns whether a
point falls within the box, handling the wrapped case. The garden example filters its
beds with it.

## Reference

See [`gazebo.params`](../reference.md#gazebo.params) and the adapters in
[`gazebo.ext.fastapi`](../reference.md#fastapi-integration).
</content>
