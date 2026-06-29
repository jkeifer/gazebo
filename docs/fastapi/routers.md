# Routers & injection

> Routes opt into by-type injection by living on a `GazeboRouter`. `LinkedRouter`
> additionally builds hierarchical landing pages from router nesting.

## Bare-type injection

On a `GazeboRouter`, a handler declares its dependencies as ordinary typed
parameters — no `Depends`. At decoration the router rewrites the signature: any
parameter whose type carries a `__provide__` recipe is resolved from the
per-request DI scope, while ordinary query/path/body params are left untouched. So
injection reads as plain function arguments:

```python
--8<-- "tests/examples/routers.py:injection"
```

## External types: the `Inject` marker

A type without `__provide__` — bound by a
[standalone recipe](../di/providers.md#standalone-recipes-external-types) — has
nothing for the router to detect, so mark it `Annotated[T, Inject]` to opt it into
injection explicitly:

```python
--8<-- "tests/examples/routers.py:inject_marker"
```

## The loud-failure guarantee

Put an injectable-typed parameter on a *plain* `APIRouter` and FastAPI would
silently treat it as a request body — a quiet, confusing bug. gazebo guards
against it: at startup the app validates every route and **fails loudly, naming
the offending route**, if an injectable parameter wasn't rewritten. This is the
safety net behind the [composition rules](index.md#composition) — mistakes surface
at boot, not in production.

A related sharp edge lives one level down, in Python's annotations. gazebo decides
what to inject by resolving each parameter's annotation — and an annotation referring
to a name importable only under `if TYPE_CHECKING:` can't be resolved at runtime. To
keep one such parameter from poisoning the others, gazebo resolves annotations
**per-parameter and leniently** (the way FastAPI itself does), so an injectable
parameter still wires even when a sibling annotation is unresolvable. The unresolvable
parameter is left for FastAPI to interpret, and gazebo **warns, naming that
parameter** — heed it by importing the annotated type at runtime rather than only
under `TYPE_CHECKING` (FastAPI can't type it either otherwise).

## Hierarchical landing pages: LinkedRouter

A `LinkedRouter` mounts a landing endpoint at its own root (its
`title`/`description` plus self and root links). Include one `LinkedRouter` into
another and — if the child declares a `rel` — a link to the child's landing page
is added to the parent automatically. So the landing hierarchy falls out of how
you nest routers, with no hand-maintained link list. `Link.to_route(name,
rel=...)` builds an ad-hoc deferred link to any route when you need one outside
this scheme.

```python
--8<-- "tests/examples/routers.py:linked_router"
```

## The service root: RootRouter

The landing page at the *top* of the tree is special: it describes the whole
service, so OGC puts the API-definition links and the conformance declaration there.
`RootRouter` is the `LinkedRouter` for that spot — it keeps the hierarchical wiring
and adds the service-level concerns that only make sense at the root, all derived
from the running app rather than hand-maintained:

- **`service-desc` / `service-doc` links** to the app's OpenAPI document and its docs
  UI (each omitted when the app has that URL disabled, so the links never dangle).
- **Title/description fallback** to the app's, so the service name lives in one place
  — on the app — and an explicit router `title` still wins when you set one.
- **An auto-mounted `/conformance`** whose baseline (`core`/`landing-page`/`json`,
  plus `oas30` when the app exposes OpenAPI) is read from the live app and merged with
  the feature classes you contribute via `conformance=`. The declaration tracks what's
  actually wired instead of drifting from it.

```python
--8<-- "tests/examples/routers.py:root_router"
```

Contribute feature-level classes as a list or a [`Conformance`](../core/ogc.md#conformance),
e.g. `conformance=[*filter_conformance_classes()]` for CQL2.

## Reference

See [`gazebo.ext.fastapi`](../reference.md#fastapi-integration)
(`GazeboRouter`, `LinkedRouter`, `RootRouter`, `Inject`).
