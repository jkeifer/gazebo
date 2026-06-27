# The core

> Everything in `gazebo` (excluding `gazebo.di` and `gazebo.ext`) is pure
> pydantic — no web framework imported.

## Why a framework-agnostic core

The OGC shapes — links, collections, problems, landing pages — are just pydantic
models, so gazebo keeps them free of any web framework. That buys three things:

- **Constructible anywhere.** You build a `LinkedCollection` or a `Link` deep in
  business logic, with no request or app object in hand.
- **Testable without a server.** Every model serializes and round-trips in a
  plain unit test.
- **Portable.** The core runs under any ASGI framework (or none); only
  `gazebo.ext` knows about FastAPI.

The one place the core needs "the current request" — to turn a deferred link into
a real URL — is abstracted behind a single seam, the
[request context](context.md). Start there.

## In this section

- [Request context](context.md) — the seam deferred links resolve against. **Read this first;** the other pages build on it.
- [Links](links.md) — the `Link` model and its deferred-href factories.
- [Collections](collections.md) — `LinkedCollection[T]`, counts, and pagination.
- [Problems](problems.md) — RFC 7807 error responses.
- [Landing & conformance](ogc.md) — OGC API Common landing page and conformance.
- [Constants](constants.md) — `Rel`, `MediaType`, and OpenAPI tags.

## Reference

See the [API reference](../reference.md#core) for the full core surface.
