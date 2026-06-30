# Gazebo Gardens 🪴

A small but complete OGC-style API — a multi-tenant plant catalog — built to
exercise **every** feature of [gazebo](../../README.md) in a realistic shape. It's
its own project (own `pyproject.toml` and tests) and a member of the repo's uv
workspace, so it resolves `gazebo` from one directory up.

## What it demonstrates, and where to look

| Feature | Where |
|---|---|
| Bare-type injection (`catalog`, `user`, `tenant`) | `garden/api.py` endpoints |
| External type via `Annotated[T, Inject]` + standalone provider | `Session` in `garden/resources.py`, `create_plant` in `api.py` |
| App scope with teardown + `__health__` | `Database` / `provide_primary` in `resources.py` |
| Qualified injection (primary vs replica) | `Catalog.__provide__` (`Qualify('replica')`) |
| Request-derived deps (auth, tenant) | `User` / `Tenant` recipes (read the `Request`) |
| Raising a problem from a recipe | `User.__provide__` → 401 |
| Central, typed provider registry | `build_providers()` in `garden/app.py` |
| Typed test overrides (no global mutation) | `test_override_seam` in `tests/test_app.py` |
| Deferred links (self / root / collection / item) | `to_plant()` in `garden/models.py` |
| Collection envelope with items alias + counts | `PlantCollection` (`plants`, `numberReturned`, `numberMatched`) |
| Pagination links (next/prev) | `list_plants` in `api.py` (`paginate(...)`) |
| RFC 7807 problem responses | `get_plant` 404; auto 422 on bad bodies |
| Hierarchical landing pages | `LinkedRouter` root → collections in `api.py` |
| Conformance declaration | `GET /conformance` |
| Proxy-aware URLs + pluggable trust | `trust=trust_all` in `create_app` (demo) |
| OpenAPI tags | `TAGS` + `tags_metadata` in `app.py` |
| Request-id contextvar + logging filter | `RequestIdMiddleware` + `default_log_config(request_id=True)` |
| Self-documenting CLI / serve command | `serve_command(create_app, settings=Settings)` in `app.py` |
| Secret as a documented config surface | `primary_dsn: SecretStr` — shown under `garden serve --help`'s Secrets, no value flag |

## Endpoints

| Method & path | What |
|---|---|
| `GET /` | Landing page with links to everything |
| `GET /conformance` | Conformance classes |
| `GET /collections` | Collections landing page |
| `GET /plants?limit=&token=` | Paginated plants (needs auth) |
| `GET /plants/{id}` | One plant, or a 404 problem |
| `POST /plants` | Create a plant (body + injection) |
| `GET /health` | Readiness (aggregates resource `__health__`) |
| `GET /docs` | Swagger UI |

All `/plants` routes require an `Authorization: Bearer <name>` header, and read an
optional `X-Tenant` header (defaults to `public`; `acme` has its own data).

## Run it

With [uv](https://docs.astral.sh/uv/), from the example directory (uv resolves the
workspace's `gazebo` automatically):

```sh
cd examples/garden
uv run garden serve           # serves on http://127.0.0.1:8000
uv run garden serve --help    # every GARDEN_* setting + uvicorn options
```

`garden` is a `click` group; `garden serve` runs the app via uvicorn (equivalent to
`uvicorn --factory garden.app:create_app`, but with `--workers`/`--reload` and the
settings options).

## Try it

```sh
curl -s localhost:8000/ | jq                       # landing page + links
curl -s localhost:8000/plants                       # 401 problem (no auth)
curl -s -H 'Authorization: Bearer alice' \
     'localhost:8000/plants?limit=2' | jq           # page 1 + a next link
curl -s -H 'Authorization: Bearer alice' \
     -H 'X-Tenant: acme' localhost:8000/plants | jq # different tenant's data
curl -s -H 'Authorization: Bearer alice' \
     -X POST localhost:8000/plants \
     -H 'Content-Type: application/json' \
     -d '{"name":"Cactus"}' | jq                    # create (body + injection)

# proxy-correct links: note the https + forwarded host in the response links
curl -s -H 'Authorization: Bearer alice' \
     -H 'X-Forwarded-Proto: https' -H 'X-Forwarded-Host: garden.example.com' \
     'localhost:8000/plants?limit=1' | jq '.links'
```

## What to look for

- **Links resolve to the live request.** The handlers build `Link` objects with no
  request in hand; the hrefs (and the `next`/`prev` pages) are filled in at
  serialization, and follow `X-Forwarded-*` headers.
- **Scopes in the logs.** Run with logging on and watch app-scoped databases open
  once at startup and close at shutdown, while a per-request `Session` closes after
  every request — each log line tagged with a request id.
- **Tests need no server.** `tests/test_app.py` drives everything through
  `TestClient` and overrides config by *parameter* (`Overrides().set(...)`), never by
  mutating a global.

## Test

```sh
cd examples/garden
uv run pytest
```
