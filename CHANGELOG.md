# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [v0.4.1] - 2026-06-30

### Changed

- `gazebo.ext.cli` `serve_command`: every non-secret settings field now gets a
  CLI flag (previously only `str`/`int`/`float`/`bool`/`Enum`) — `Path`,
  `UUID`, `datetime`, `Optional[...]`, and complex types (passed as a JSON
  string) included, since a flag just sets the field's env var and pydantic
  deserializes it as it does for env loading. `bool` (toggle) and `Enum`
  (`Choice`) keep their widgets. Secret (`SecretStr`) fields are now listed in
  `--help` as a documented configuration surface (their env var) without a
  value-accepting flag, so they stay discoverable yet off the command line
  (shell history / `ps`). Required fields (no default) are now marked `[required]`
  in `--help` and enforced at parse time — satisfied by the flag *or* its env var,
  since click reads the env var; a required secret is marked `(required)` in the
  Secrets section.

## [v0.4.0] - 2026-06-30

### Added

- `gazebo.ext.cli` (new `gazebo[cli]` extra): `serve_command` builds a
  self-documenting `click` "serve" command. It composes uvicorn's own options
  (`--workers`/`--reload`/`--env-file`/...) and generates one documented option
  per `pydantic-settings` field — each showing its env var, default, and
  description — so `--help` is the configuration reference. A passed flag
  simply sets its env var, so values reach uvicorn workers through the
  environment with no cross-process transport; secrets (`SecretStr`) are kept
  off the CLI. Includes `default_log_config` (with `json_logs` and `request_id`
  switches) and a `serve --check` validate-and-exit preflight. Wired into the
  garden example as `garden serve`.

## [0.3.0] - 2026-06-29

### Added

- `gazebo.filtering` (new `gazebo[cql2]` extra): CQL2 filtering with the OGC
  plumbing around it. Core (pydantic-only):
  `queryables_from_model`/`sortables_from_model` derive the
  `Queryables`/`Sortables` JSON-Schema resources — and the filter/sort
  allow-lists — from a pydantic model, flattening nested models to dotted
  accessors (`site.coord.lat`) and advertising geometry fields as spatial
  queryables; `SortBy` parses/validates the OGC/STAC `sortby` value and applies
  a stable in-memory sort; `validate_properties` rejects a filter that
  references a non-queryable field; and a `FilterEngine`/`Compiled` Protocol
  seam (`Filter`, `FilterError`, `FilterLang`) keeps the core free of the CQL2
  dependency. The bundled `Cql2Engine` (in `gazebo.filtering.cql2`, adapting
  cql2-rs) parses both encodings and is isolated behind the extra; the seam
  stays open for a user-supplied engine.
- FastAPI `FilterParam(queryables)` and `SortByParam(sortables)` adapters: drop
  the OGC `filter`/`filter-lang`/`filter-crs` and `sortby` parameters into a
  route signature as typed `Filter`/`SortBy` values, rendering a parse failure,
  an unknown filter language, an unsupported CRS, a non-queryable property, or
  a non-sortable field as a `400 application/problem+json`.
- `gazebo.problems` `ProblemType` and `ProblemRegistry` (core, pydantic-only):
  a documented, reusable kind of problem — a stable `type` URI plus a
  title/status/default detail — that you define once and raise by reference
  (`problem_type.exception(...)`), so a service's `type` URIs stop defaulting
  to `about:blank` and stay stable/linkable.  `ProblemRegistry` keys them by a
  short name, rejects duplicate keys, and hands back the whole set via
  `catalog()` to serve from an endpoint so a client can resolve a received
  `type` to its meaning.
- FastAPI `RootRouter`: the service-root `LinkedRouter`. Beyond the
  hierarchical landing page, it emits `service-desc`/`service-doc` links to the
  app's OpenAPI document and docs UI (each omitted when that URL is disabled),
  falls its `title`/`description` back to the app's, and auto-mounts a
  `/conformance` declaration whose baseline (`core`/`landing-page`/`json`, plus
  `oas30` when OpenAPI is exposed) is derived from the running app and merged
  with the feature classes contributed via `conformance=`, so the declaration
  can't drift from what's actually wired.

### Fixed

- FastAPI injection now resolves each route-handler parameter's type annotation
  independently and leniently (the way FastAPI itself does) instead of
  resolving the whole signature at once. Previously a single unresolvable
  annotation — typically a name imported only under `if TYPE_CHECKING:` — made
  `get_type_hints` fail for the entire handler, silently un-wiring *every*
  injectable parameter on it (which then surfaced as a request-time 500, the
  type treated as a request body). The injectable parameters next to an
  unresolvable one now wire correctly, and gazebo warns once, naming the
  parameter it could not resolve.

## [0.2.0] - 2026-06-28

### Added

- CORS support: `GazeboApp` and `upgrade()` accept `cors=` (off by default;
  `True` for a permissive dev policy, a list of origins for an allow-list, or a
  `CorsConfig` for full control). Added `CorsConfig`, with `resolve()` to
  normalize the argument and `apply()` to install the `CORSMiddleware`; it is
  installed outermost so CORS headers ride on every response, including
  problems.
- `gazebo.params` (core, pydantic-only): typed parsers for the standard OGC
  query parameters — `BBox`, `DatetimeInterval`, `validate_crs`, the `CRS84`
  constant, and the `ParamError` exception. `bbox` allows antimeridian-crossing
  boxes (and answers `BBox.contains(lon, lat)` accordingly); `datetime` accepts
  RFC 3339 instants and open/closed intervals, treating a naive value as UTC.
- `gazebo.serialization`: pure-pydantic helpers for OGC-style serialization —
  `OmitNullModel`, a base model that omits absent (`None`) members on the JSON
  wire while keeping an honest (non-opaque) OpenAPI response schema, plus the
  underlying `faithful_serialization_schema` and `drop_none`. `OmitNullModel`
  is re-exported from the top-level `gazebo` package.
- FastAPI query-parameter adapters `BBoxParam`, `DatetimeParam`, and the
  `CrsParam(allowed=[...])` factory, plus a `ParamError` handler that renders
  parse failures as `400 application/problem+json` (registered automatically by
  `upgrade()` / `GazeboApp`).
- `gazebo.geojson` (new `gazebo[geojson]` extra): GeoJSON `Feature[P]` and
  `FeatureCollection[P]` with gazebo's deferred links, building on
  `geojson-pydantic` for coordinate validation; the geometry types and
  `Position2D`/`Position3D` are re-exported.
- OGC collection-metadata models in `gazebo.ogc`: `Collection`, `Extent`,
  `SpatialExtent`, `TemporalExtent`, the `Collections` envelope, and the
  `DEFAULT_TRS` constant.
- `LinkedCollection` gained a `number_returned` class keyword to omit the
  computed `numberReturned` member (the OGC `/collections` envelope
  `Collections` uses it).
- `gazebo.testing` (new `gazebo[test]` extra): a pytest plugin for asserting a
  service's OGC shapes — `assert_problem`, `assert_has_link`, `find_link`, the
  `drive_pagination` driver (envelope invariants per page, loop guard,
  GET/POST, and a `request_kwargs` passthrough for authenticated clients), and
  the opt-in `gazebo_link_context` and `gazebo_overrides` fixtures.
- `gazebo.negotiation` (core): content negotiation in OGC order —
  `Representation` (with `JSON`/`GEOJSON`/`HTML` constants), `negotiate` (`?f=`
  wins, then the `Accept` header with full q-value/specificity matching, then a
  default; unknown `f=` → `ParamError`/400, unsatisfiable `Accept` →
  `ProblemException`/406), and `alternate_links`. The FastAPI
  `Negotiate([...])` dependency resolves it from the request; HTML rendering
  stays the app's job (no templating dependency added).
- `gazebo.caching` (core): conditional-request primitives — `etag_for` (weak
  ETags by default), `http_date`/`parse_http_date`, and the RFC 7232
  precondition logic (`is_not_modified`, `if_none_match_satisfied`). FastAPI
  helpers `not_modified()` (a ready `304` when preconditions match, carrying
  the validators and an optional `cache_control` so the `304` refreshes the
  cache's freshness directives) and `set_cache_headers()`; opt-in.
- `gazebo.linkheader` (core) and a `set_link_header()` FastAPI helper: mirror a
  response's navigational links as an RFC 8288 `Link:` header. Call it inside
  an endpoint with the links you're returning (the companion to
  `set_cache_headers()`); it resolves the deferred hrefs against the active
  request. Narrowed to a rel allow-list (`NAV_RELS`) and capped
  (`DEFAULT_MAX_LINKS`) so per-item-heavy collections can't bloat the header.
- `gazebo.pagination` conveniences: `encode_cursor`/`decode_cursor` (opaque
  base64-JSON cursors; a bad cursor raises `ParamError` → 400),
  `paginate_offset` (derives `self`/`first`/`prev`/`next`/`last` from
  offset/limit/total), and `first`/`last_token`/ `self_` on `paginate`. Both
  builders now take the full `Link` surface — `type`, `headers`,
  `**link_fields`, and `method`/`body`; with `method='POST'` the token rides in
  the request body for stateless POST-search pagination. `paginate`'s existing
  `next`/`prev` output is unchanged.
- `gazebo.pagination.last_page_offset(total, limit)`: the zero-based offset of
  the last page for a given total and page size — the rounding helper
  `paginate_offset` uses internally, exposed so callers deriving their own
  `last` cursor don't re-spell the math.
- `parse_annotation` (exported from `gazebo.di`): splits a type annotation into
  `(base type, Qualify qualifier, Annotated metadata)` — the shared parser the
  DI container and the FastAPI injection glue both use to read injectable
  parameters.
- `ScopeState.health_probes()`: yields `(label, probe)` for each resolved value
  in a scope that carries a `__health__` callable. The FastAPI health endpoint
  uses it to discover probes rather than reaching into the resolution cache.

### Changed

- `gazebo.ext.fastapi` is organized as a package — one module per concern
  (injection, OGC param adapters, CORS, response helpers, routers, app wiring)
  — rather than a single module. The public import surface is flat and
  unchanged: keep importing from `gazebo.ext.fastapi`. The `Cors` type alias is
  now exported.

### Fixed

- `Link.to_route` no longer leaks the `path` mapping as a stored link field,
  and no longer mutates its captured path params — repeated serializations of a
  link to a route with path parameters now resolve to the same correct URL.
  `path` is now an explicit keyword argument.
- `LinkedCollection`'s `items_alias` now survives generic parametrization (e.g.
  `FeatureCollection[P]`) and is applied in both python and JSON dump modes. It
  previously mutated `model_fields`, which pydantic rebuilds for each generic
  specialization, so a generic subclass serialized `items` instead of the
  alias.
- The OpenAPI/serialization JSON schema for `Link` and `LinkedCollection` (and
  their subclasses) is faithful again. The null-dropping `@model_serializer`
  made the serialization schema collapse to `{"additionalProperties": true}`,
  so FastAPI's documented response shape was an opaque object; it now reflects
  the real fields, the items alias, the computed `numberReturned`, and
  non-opaque `links`.

## [0.1.0] - 2026-06-27

Initial release 🎉

[unreleased]: https://github.com/jkeifer/gazebo/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.4.0
[0.3.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.3.0
[0.2.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.2.0
[0.1.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.1.0
