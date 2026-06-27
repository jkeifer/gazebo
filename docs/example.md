# Example: Gazebo Gardens 🪴

> A complete, standalone OGC-style API — a multi-tenant plant catalog — that
> exercises every gazebo feature in a realistic shape.

This page is the "see it all together" companion to the feature pages: where those
use small, isolated snippets, Gazebo Gardens shows them composed into one
service. It's its own project under
[`examples/garden/`](https://github.com/jkeifer/gazebo/tree/main/examples/garden),
and the repo's standing proof that the features work in concert — CI runs its
suite separately.

## What it demonstrates

Each feature maps to a spot in the code; read it alongside the page that explains it.

| Feature | Where | Docs |
|---|---|---|
| Bare-type injection (`catalog`, `user`, `tenant`) | `garden/api.py` | [Routers & injection](fastapi/routers.md#bare-type-injection) |
| External type via `Annotated[T, Inject]` | `Session` in `garden/resources.py` | [Inject marker](fastapi/routers.md#external-types-the-inject-marker) |
| App scope with teardown + `__health__` | `Database` in `resources.py` | [Scopes & lifecycle](di/scopes.md) |
| Qualified injection (primary vs replica) | `Catalog.__provide__` | [Qualifiers](di/qualifiers-overrides.md#qualifiers) |
| Request-derived deps (auth, tenant) | `User` / `Tenant` recipes | [Scope roots](di/scopes.md#scope-roots) |
| Typed test overrides (no global mutation) | `tests/test_app.py` | [Overrides](di/qualifiers-overrides.md#overrides) |
| Deferred + paginated links | `models.py`, `api.py` | [Links](core/links.md), [Collections](core/collections.md) |
| Collection envelope with alias + counts | `PlantCollection` | [Collections](core/collections.md) |
| RFC 7807 problems (404; auto 422) | `get_plant`, bad bodies | [Problems](core/problems.md) |
| Hierarchical landing pages | `LinkedRouter` in `api.py` | [LinkedRouter](fastapi/routers.md#hierarchical-landing-pages-linkedrouter) |
| Conformance declaration | `GET /conformance` | [Landing & conformance](core/ogc.md) |
| Proxy-aware URLs + pluggable trust | `trust=` in `create_app` | [Proxy & context](fastapi/proxy.md) |
| Request-id contextvar + logging filter | `RequestIdMiddleware` | [Request id & logging](fastapi/proxy.md#request-id-logging) |

## Run it

```sh
cd examples/garden
uv run garden          # serve on http://127.0.0.1:8000
uv run pytest          # its test suite
```

## Try it

A few requests that show the load-bearing behavior (full recipe set in the
[example README](https://github.com/jkeifer/gazebo/tree/main/examples/garden)):

```sh
curl -s localhost:8000/ | jq                              # landing page + links
curl -s localhost:8000/plants                              # 401 problem (no auth)
curl -s -H 'Authorization: Bearer alice' \
     'localhost:8000/plants?limit=2' | jq                  # page 1 + a next link
curl -s -H 'Authorization: Bearer alice' -H 'X-Tenant: acme' \
     localhost:8000/plants | jq                            # a different tenant's data
curl -s -H 'Authorization: Bearer alice' \
     -H 'X-Forwarded-Proto: https' -H 'X-Forwarded-Host: garden.example.com' \
     'localhost:8000/plants?limit=1' | jq '.links'         # proxy-correct links
```

## See also

- Full walkthrough and feature map: [`examples/garden/README.md`](https://github.com/jkeifer/gazebo/tree/main/examples/garden)
- The features it uses: [core](core/index.md), [DI](di/index.md), [FastAPI glue](fastapi/index.md).
