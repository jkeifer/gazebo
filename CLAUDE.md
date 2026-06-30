# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

gazebo packages the recurring machinery of OGC-style REST APIs (deferred links,
collection envelopes, RFC 7807 problems, proxy-aware URLs, a typed DI container, and
FastAPI glue) so it isn't re-implemented per project. The core depends only
on `pydantic`; framework integration is opt-in via extras. Requires Python 3.12+.

## Commands

The project is `uv`-managed and is a `uv` workspace whose only member is
`examples/garden`. Run everything through `uv`.

```sh
uv sync --all-extras --all-packages   # install (CI also uses --locked --no-editable)
uv run pytest                          # run the library test suite (tests/)
uv run pytest tests/test_link.py::test_name   # a single test
uv run pre-commit run --all-files      # ruff check+format, mypy, pyright, file hygiene
```

`uv run pytest` always reports coverage on the `gazebo` package (`addopts=--cov=gazebo`
in `pyproject.toml`) and treats warnings as errors (`filterwarnings = ['error']`).

The example app is its **own** project under `examples/garden` with its own test suite
and entry point; run them from that directory:

```sh
cd examples/garden
uv run garden        # serve Gazebo Gardens on http://127.0.0.1:8000
uv run pytest        # the example's tests
```

Type checking is enforced by **both** mypy and pyright (pyright runs over `src` and
`tests`); both run in pre-commit and CI must be green on Python 3.12–3.14.

## Architecture

The codebase is strictly layered and **dependencies only ever point downward**. The
two load-bearing ideas are *deferred links* and a *scoped DI container*; understand
those two seams and the rest follows.

### Layers (`src/gazebo/`)

1. **Core** (`context.py`, `link.py`, `collection.py`, `pagination.py`, `rels.py`,
   `problems.py`, `ogc.py`) — pydantic + stdlib only. **Never imports a web
   framework.** Pure models and the context seam.
2. **DI core** (`di/`) — stdlib only, no web framework. A standalone, extraction-ready
   container behind a `Providers` interface.
3. **Pure ASGI** (`asgi.py`) — proxy-header middleware and context-setting middleware;
   no framework import.
4. **Framework glue** (`ext/fastapi.py`) — the only module that imports `fastapi`.
   Wires the DI container and the link context into a real app. Importing it requires
   the `gazebo[fastapi]` extra.

When adding code, respect the layer: anything a lower layer needs must not import
upward, and the core must stay framework-free.

### Deferred links (the central trick)

A `Link.href` may be a plain URL **or** a callable taking a `RequestContext` and
returning a URL. Callables are resolved at **JSON serialization time**, so links (and
whole `LinkedCollection`s) are fully constructible in business logic with no request in
hand.

- `gazebo/context.py` defines the `RequestContext` Protocol (the minimal surface link
  factories need: `base_url`, `url`, `query_params`, `url_for`) and delivers it
  ambiently via the `link_context` ContextVar.
- The framework glue sets that ContextVar per request (`use_context`). For manual dumps
  / tests there is a fallback: `model_dump(context={'request': ctx})`, resolved by
  `resolve_context`.
- `Link` factories (`self_link`, `root_link`, `to_route`) build callable hrefs that
  call back into the context — they stay framework-agnostic.

A consequence: a callable-href link only serializes correctly inside an active request
(or with an explicit dump context). Serializing one with no context raises a clear
`ValueError` by design.

### DI container (`di/`)

- `providers.py` — registration. A **recipe** is a callable that builds a value, keyed
  by the type it produces; it may be colocated as a `__provide__` classmethod on the
  type, or supplied standalone for external types. **Scope is a wiring decision bound
  at registration, never a property of the type** (`providers.app(T)` /
  `providers.request(T)`). Recipes may be sync/async functions, (async) generators, or
  (async) context managers; generators are auto-wrapped as CMs. `Qualify` disambiguates
  duplicate types; `Overrides` is a typed replacement layer (the test-override
  mechanism — by parameter, never by mutating a global).
- `container.py` — the resolution engine. Resolves a recipe's dependencies by the
  **types of its parameters**; a parameter typed as a scope's *root* (e.g. the request
  object) receives that root. Each entered scope owns a resolution cache and an
  `AsyncExitStack` for teardown. Errors are specific: `UnresolvedDependencyError`,
  `ScopeMismatchError`, `CircularDependencyError`.

### How the glue ties it together (`ext/fastapi.py`)

`GazeboApp` enters the **app** scope in its lifespan and opens a **request** scope per
request, publishing the link `RequestContext` for that request. Routes opt into
bare-type injection by living on a `GazeboRouter` (or the app directly): any parameter
whose type carries `__provide__`, or is marked `Annotated[T, Inject]`, is resolved from
the per-request scope by rewriting the route signature into FastAPI `Depends`.

`GazeboApp` + `GazeboRouter` are an **intended pair**. Putting an injectable-typed route
on a plain `APIRouter` fails loudly at startup (naming the route) rather than silently
treating the parameter as a request body. To add gazebo behavior to an app you didn't
construct, use `upgrade(app, providers)` instead of subclassing; to mount a `GazeboApp`
under a root app, forward its lifespan with `forward_lifespans`.

## Docs

- `working-docs/` — design specs and drafts: `design.md` (the OGC/web shapes),
  `design-di.md` (the injection system), `roadmap.md` (post-v1 feature backlog). These
  are the authoritative rationale for why things are shaped as they are; read the
  relevant one before reworking a subsystem.
- `docs/` — the published documentation site (zensical/mkdocs, versioned with mike).
- `examples/garden/` — a complete standalone OGC-style API that exercises every feature;
  the best end-to-end reference for how the pieces fit.

```sh
uv run --group docs zensical build --strict --clean   # build (CI gate; fails on issues)
uv run --group docs zensical serve                     # live preview while writing
```

### Documentation style & guidelines

- **Split by document type; never duplicate across the boundary.** *Reference* (what
  each symbol is — signatures, params) lives in **docstrings** and is autogenerated into
  `docs/reference.md` via mkdocstrings. *Explanation/how-to* (why you'd reach for it, how
  pieces combine) lives in **handwritten Markdown**. Keep docstrings Google-style and
  current — they are the single source of truth for the reference layer.
- **Narrative pages must not restate the API.** No retyped signatures or param tables in
  prose; link into the reference anchor instead (e.g. `reference.md#gazebo.link`, or a
  per-symbol anchor like `#gazebo.link.Link.self_link`). Each page ends with a
  **Reference** link.
- **Structure is layered by architecture** (Core → DI → FastAPI integration), one page
  per module, mirroring `src/gazebo/`. The nav lives in `zensical.toml`; update it when
  adding a page.
- **Page shape:** open with a one-line *why* blockquote, lead with the rationale (the
  *why*) before the *how*, then concept sections. Prefer small, self-contained,
  copy-pasteable snippets over one large example; the garden example is the
  "see it all together" reference.
- **All code snippets are tested.** Example code lives in `tests/examples/<page>.py` as
  runnable modules with module-level `assert`s; `tests/test_examples.py` executes each
  via `runpy`, so a broken snippet fails CI. Docs **include** the clean region with
  pymdownx.snippets — ` ```python\n--8<-- "tests/examples/links.py:self_link"\n``` ` —
  rather than pasting code, so what readers see is exactly what runs. Wrap the rendered
  region in `# --8<-- [start:name]` / `# --8<-- [end:name]` markers and keep the driving
  `assert`/`TestClient` code *outside* the markers so it doesn't render. `check_paths`
  is on, so a bad include path or region name fails the strict build.

## Landing a feature

A new feature or behavior change is not complete until all of these land with it:

1. **Tests** in `tests/` covering the new behavior (coverage and warnings-as-errors are
   enforced; CI runs the suite on Python 3.12–3.14).
2. **Use in the garden example** — `examples/garden` is meant to exercise *every*
   feature, so wire the new capability into the example app and its tests. CI runs the
   garden suite separately, so this is load-bearing, not decorative.
3. **Documentation** — update the relevant page under `docs/` (and the design spec in
   `working-docs/` if the feature changes a subsystem's rationale or shape).
4. **Changelog** — add an entry under `## [unreleased]` in `CHANGELOG.md`, in the
   appropriate Added/Changed/Deprecated/Removed/Fixed/Security subsection.
5. **README** — update `README.md` (and `examples/garden/README.md` when relevant) if
   the change adds an extra, a user-facing capability, or changes how the app is run.

## Conventions

- Ruff is configured with single quotes and a 99-char line length, with a broad lint
  rule set (see `[tool.ruff.lint]` in `pyproject.toml`). Match the surrounding style.
- Every module starts with a docstring explaining its role in the layering; keep that
  up to date when a module's responsibility shifts.
</content>
</invoke>
</invoke>
