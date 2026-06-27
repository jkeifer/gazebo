# gazebo

> Everything needed to build OGC-style APIs, under one roof.

gazebo packages the recurring machinery of OGC-style services so it doesn't get
re-implemented per project. The core depends only on `pydantic`; framework
integration is opt-in.

## What's in the box

| Feature | Module | Page |
|---|---|---|
| Deferred links (callable hrefs resolved at serialize time) | `gazebo.link` | [Links](core/links.md) |
| The request-context seam links resolve against | `gazebo.context` | [Request context](core/context.md) |
| Collection envelopes (items + links + counts) | `gazebo.collection` | [Collections](core/collections.md) |
| Pagination links (next/prev) | `gazebo.pagination` | [Collections](core/collections.md) |
| RFC 7807 problem responses | `gazebo.problems` | [Problems](core/problems.md) |
| Landing pages + conformance | `gazebo.ogc` | [Landing & conformance](core/ogc.md) |
| Typed `Rel` / `MediaType` / tag constants | `gazebo.rels`, `gazebo.tags` | [Constants](core/constants.md) |
| Typed, scoped dependency injection | `gazebo.di` | [Dependency injection](di/index.md) |
| Proxy-aware URLs + pluggable trust | `gazebo.asgi` | [Proxy & context](fastapi/proxy.md) |
| FastAPI app, routers, health, composition | `gazebo.ext.fastapi` | [FastAPI integration](fastapi/index.md) |

## When to use it

gazebo is for **OGC-style, hypermedia REST APIs on FastAPI** — services where:

- responses carry `links` whose URLs depend on the incoming request (and must
  stay correct behind a proxy);
- resources have lifetimes worth managing (app-lifetime pools, per-request
  sessions, request-derived identity);
- you want OGC shapes — collections, landing pages, conformance, RFC 7807
  problems — without rebuilding them each time.

gazebo is a **toolkit, not a framework**: you build on FastAPI and write your own
handlers, and gazebo supplies the OGC plumbing those handlers reach for — so it
lives in one place instead of being rebuilt each project. The core is just
pydantic, so you can pull in one piece without adopting the rest.

## Where to go next

- **New here?** [Getting started](getting-started.md) — install + a working app in ~40 lines.
- **Browsing features?** Start with [the core](core/index.md), then [DI](di/index.md), then [FastAPI glue](fastapi/index.md).
- **Want the whole thing at once?** [Gazebo Gardens](example.md), the complete example app.
- **Looking up an API?** [Reference](reference.md), generated from the source.

## Status

Early / pre-1.0. The `gazebo.di` container is intentionally minimal and
extraction-ready (stdlib only); it sits behind a `Providers` interface so a
mature container could be adopted later without changing user code.
