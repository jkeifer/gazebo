# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

### Added

- docs: a "Why gazebo" page that motivates the library by contrast — hand-rolled
  plain-FastAPI code shown failing (proxy-broken links, pagination dropping query
  params, global-mutation test overrides), then the gazebo equivalent, all backed
  by tested examples (`tests/examples/why_before.py` / `why_after.py`).

### Changed

- docs: feature pages now open with the problem they solve — pain-first summary
  blockquotes and short problem openings across the core, DI, and FastAPI pages,
  plus a decompression pass over the densest prose (context, collections,
  negotiation, DI overview).

### Fixed

- `with_query()` (and everything built on it: `paginate()`, `paginate_offset()`,
  and content-negotiation `alternate` links) now preserves repeated query
  parameters (`?tag=a&tag=b`) when rewriting a URL; previously all but the last
  occurrence were silently dropped. Overriding such a parameter replaces every
  occurrence, and a `None` override removes them all.
- A DI recipe that reads the request body (`__provide__(request)` awaiting
  `request.body()`) no longer deadlocks the request when the endpoint also
  parses a body: the request-scope middleware now shares a replaying `receive`
  between the DI-root request and the downstream app, at the cost of retaining
  consumed body messages for the request's duration.
- Duplicate route names (e.g. two `LinkedRouter`s left on the default
  `landing_name='landing'`) now fail loudly at startup, naming the duplicates
  and their paths. Previously `url_for` silently resolved to the first
  registration, so hierarchical landing links could point at the wrong router.
- `GET /health` now returns **503** when any probed resource is unhealthy
  (previously 200 with an `"unhealthy"` body), so load balancers and readiness
  probes keyed on the status code behave correctly.
- Serializing a deferred (callable-href) link with no active request context
  again raises the documented clear error (`no request context available…`).
  It had been swallowed by pydantic's union-serializer fallback into an opaque
  `Unable to serialize unknown type: <class 'function'>`.
- Problem responses no longer emit null members: `ProblemDetail` and
  `ProblemType` are now `OmitNullModel`s, so an unset `detail`/`instance` (or a
  `None` extension member) is omitted on the wire, matching the library's OGC
  omit-null convention and the documented response shapes.
- `paginate()` called without `limit` no longer strips the client's existing
  `?limit=...` from the emitted links (page size silently reset mid-walk);
  an absent `limit` now leaves the URL's (or POST body's) limit untouched.
- `ProxyHeadersMiddleware` now maps `X-Forwarded-Proto` onto websocket scopes
  correctly (`https` → `wss`, `http` → `ws`) instead of setting an invalid
  `https` scheme.
- `If-None-Match` evaluation now parses entity-tags as quoted strings, so a
  legal ETag containing a comma matches instead of always revalidating.

### Deprecated

### Removed

### Security

- `SharedSecret` trust policy now compares the proxy secret with
  `hmac.compare_digest` instead of `==`, closing a timing side channel.

## [v0.7.0] - 2026-07-05

### Added

- `gazebo.di.resolve_annotation()`: the lenient, per-annotation type-hint
  resolver (previously an internal of the FastAPI glue) is now a public, shared
  `gazebo.di` helper — the single implementation behind both the DI container's
  dependency discovery and route-signature injection.
- `gazebo.context.merge_params()`: the shared "merge overrides into params; a
  `None` value removes the key" helper behind `with_query` and the pagination
  POST-body links.

### Changed

- **Breaking:** the request-id machinery moved out of `gazebo.context` into a
  new `gazebo.requestid` module: `request_id`, `use_request_id`, and
  `RequestIdFilter`. `gazebo.context` now carries only the link-context seam.
  Migration: import from `gazebo.requestid`, and update any logging dictConfig
  filter reference from `'gazebo.context.RequestIdFilter'` to
  `'gazebo.requestid.RequestIdFilter'`.
- **Breaking:** `default_log_config()` moved from `gazebo.ext.cli` to
  `gazebo.ext.uvicorn`. It configures uvicorn's loggers and console formatters,
  so it belongs in the uvicorn-coupled module; `gazebo.ext.cli` is now honestly
  server-agnostic (`JsonFormatter` stays there). Migration: `from
  gazebo.ext.uvicorn import default_log_config`.
- **Breaking:** `decode_cursor()`'s default `parameter` is now `'token'`,
  matching `paginate()`'s default `token_param` — so a service on all defaults
  emits `?token=` links *and* blames `token` in the 400 problem for a bad
  cursor. Pass `parameter='cursor'` explicitly if your query parameter is named
  `cursor`.

### Fixed

- `upgrade()` (and therefore `GazeboApp`) no longer mutates the caller's
  `Providers` registry when adding the default `RequestContext` binding; the
  default is layered into a copy, so a registry can be safely reused or
  inspected after wiring an app.

## [v0.6.0] - 2026-07-03

### Added

- `gazebo.ext.cli.SettingsGroup`: a class that composes one or more
  `pydantic-settings` classes into a validated set of self-documenting CLI
  options. Construct it with per-group `exclude`/`rename` (keyed by the
  **generated flag**, e.g. `rename={'--app-config': '--config'}`; a `rename`
  value may be a sequence like `['-C', '--config']` to add a short option),
  read `.options` to splat onto any `click` command, and `.secrets_epilog` for
  the secrets `--help` section. Combine groups with `+`; constructing or
  combining validates the whole set (distinct `env_prefix` per group, no flag
  collisions, and every `exclude`/`rename` key must match a generated flag or
  it raises).

### Changed

- **Breaking:** `gazebo.ext.uvicorn.serve_command()` now takes a single
  `settings_group: SettingsGroup` instead of `settings` (a settings class or
  sequence) plus `exclude`/`rename`. The composition and its checks moved to
  `SettingsGroup`, keeping `serve_command` focused on the uvicorn boundary.
  Migration: `serve_command(app, settings=Settings, rename={...})` becomes
  `serve_command(app, settings_group=SettingsGroup(Settings, rename={...}))`.

### Removed

- **Breaking:** `gazebo.ext.cli.settings_options()` is replaced by
  `gazebo.ext.cli.SettingsGroup`. Migration: `settings_options(Settings, ...)`
  becomes `SettingsGroup(Settings, ...).options`, and its `exclude`/`rename`
  now key by the generated flag (e.g. `--app-greeting`) rather than the bare
  field name — so a key reads in the same namespace as a `rename` value, stays
  unambiguous across groups, and a key matching no generated flag raises
  instead of silently doing nothing (`{'greeting': ...}` -> `{'--app-greeting':
  ...}`).

## [v0.5.0] - 2026-07-03

### Added

- `gazebo.ext.uvicorn`: a self-documenting `serve` command over uvicorn.
  `serve_command()` builds a `click` command whose `--help` documents *your
  app's* settings (one option per field, with env var/default/description)
  while every uvicorn option is accepted and **forwarded verbatim** to uvicorn;
  `--help-server` prints uvicorn's own help. It treats uvicorn as a CLI, not a
  library — `serve(app, *uvicorn_args, ...)` forwards documented argv to
  `uvicorn.main.main(args=..., standalone_mode=False)`, so uvicorn does its own
  parsing, defaults, `UVICORN_*` env vars, and value transforms; a typo'd flag
  gets uvicorn's own "did you mean" error.
- `gazebo.ext.cli`: `settings_options()` and `secrets_epilog()` as the
  server-agnostic composable core — `gazebo.ext.cli` no longer imports uvicorn,
  so these compose a serve command atop **any** server (granian, ...).
  `settings_options()` returns one self-propagating, `expose_value=False`
  `click.Option` per non-secret field (each writes its env var when passed) and
  takes `exclude` (drop a field) and `rename` (re-flag a field, keeping its env
  var — a renamed `bool` still gets its `--x/--no-x` toggle);
  `secrets_epilog()` renders the `--help` section documenting secret fields
  (env var, `(required)` marker) without accepting them as flags.

### Changed

- **Breaking:** `serve_command` moved from `gazebo.ext.cli` to
  `gazebo.ext.uvicorn`.  Migration: `from gazebo.ext.uvicorn import
  serve_command` (`default_log_config` / `settings_options` stay in
  `gazebo.ext.cli`).
- **Breaking:** uvicorn's options no longer appear in `serve --help` (which now
  documents only your app's settings); they are still accepted and forwarded to
  uvicorn. Migration: run `serve --help-server` to list uvicorn's options.
- **Breaking:** `serve_command`'s `**fixed` uvicorn kwargs are replaced by
  `uvicorn_args=('--workers', '4', ...)` — author-supplied CLI argv forwarded
  *before* operator arguments, so operators can now override them on the
  command line (previously pinned constants were removed from the CLI).
  Migration: `serve_command(app, workers=4)` → `serve_command(app,
  uvicorn_args=('--workers', '4'))`.
- **Breaking:** `uvicorn` is no longer pulled in by the `gazebo[cli]` extra; it
  now lives in its own `gazebo[uvicorn]` extra (which depends on `gazebo[cli]`).
  This matches `gazebo.ext.cli` (server-agnostic: `click`, `pydantic-settings`)
  and `gazebo.ext.uvicorn` (the only module importing `uvicorn`) being separate
  modules. Migration: install `gazebo[uvicorn]` instead of `gazebo[cli]` if you
  use `gazebo.ext.uvicorn.serve` / `serve_command`; `gazebo[cli]` alone still
  gets you `gazebo.ext.cli`'s building blocks for composing atop another server.

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

## [v0.3.0] - 2026-06-29

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

## [v0.2.0] - 2026-06-28

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

## [v0.1.0] - 2026-06-27

Initial release 🎉

[unreleased]: https://github.com/jkeifer/gazebo/compare/v0.7.0...HEAD
[v0.7.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.7.0
[v0.6.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.6.0
[v0.5.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.5.0
[v0.4.1]: https://github.com/jkeifer/gazebo/releases/tag/v0.4.1
[v0.4.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.4.0
[v0.3.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.3.0
[v0.2.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.2.0
[v0.1.0]: https://github.com/jkeifer/gazebo/releases/tag/v0.1.0
