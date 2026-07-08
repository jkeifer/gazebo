# Content negotiation

> `?f=` and `Accept` say what the client wants; something has to pick a
> representation and link the alternates. Pure resolution — gazebo takes no
> position on HTML or templating.

OGC clients live on `?f=json|html`, with the HTTP `Accept` header as the
fallback. Every multi-format endpoint therefore needs the same two decisions
made correctly: which representation to serve, and how to advertise the others.
`gazebo.negotiation` is exactly that *resolution* logic — given the
representations a resource offers, it picks one and builds the `alternate` links
to the rest.

It deliberately ships **no HTML renderer**. Turning the chosen representation
into bytes — a template, a callable — is the app's job; gazebo only tells you
*which* representation won, and links the others.

## Resolving a representation

A [`Representation`](../reference.md#gazebo.negotiation.Representation) pairs a `?f=` key
with a media type (`JSON`, `GEOJSON`, `HTML` are ready-made). `negotiate()` applies the
OGC order — `?f=` wins, then `Accept`, then the first offered (or an explicit
`default`):

```python
--8<-- "tests/examples/negotiation.py:negotiate"
```

A `?f=` naming a format that isn't offered is a client error
([`ParamError`](params.md) → `400`); an `Accept` that lists nothing on offer is a `406`
([`ProblemException`](problems.md)). Both already render as problem+json through the
FastAPI glue, so a failed negotiation needs no extra handler.

## In a route

The glue's `Negotiate([...])` dependency resolves the representation from the request
(`?f=` query + `Accept` header). The endpoint branches on it — render HTML or return the
model — and attaches `alternate_links()` so each representation advertises the others.
Inject `Response` semantics by returning an `HTMLResponse` for the HTML branch while
keeping a `response_model` for the JSON one:

```python
--8<-- "tests/examples/negotiation.py:route"
```

`alternate_links(current, available)` returns one deferred `alternate` link per *other*
representation, each pointing at the current URL with `?f=` switched — so a client on
the JSON view can discover and follow the HTML one. Pair it with a normal `self` link
for the current representation.

## Folded into your own query model

When a route already takes a Pydantic query model, you can fold `?f=` into it as a field
rather than adding a separate dependency. The supported formats are a *closed set* you
own, so — as with [`crs`](params.md#folded-into-your-own-query-model) — gazebo gives you a
base enum to subclass: [`FormatEnum`](../reference.md#gazebo.negotiation.FormatEnum), a
`StrEnum` whose members are `(?f= key, media type)` pairs. It is a real class, so it drops
onto your model as an ordinary field type (no `type: ignore`), pydantic validates the key
natively, and FastAPI renders it as an `enum` query param whose OpenAPI description names
your subclass's actual `?f=` keys (not a stock example):

```python
--8<-- "tests/examples/negotiation.py:folded"
```

Give the field a default so an absent `?f=` resolves to it. Because each member carries
its media type, a member alone yields its
[`Representation`](../reference.md#gazebo.negotiation.Representation) via
[`.representation`](../reference.md#gazebo.negotiation.FormatEnum.representation) — no
external `{key: rep}` dict — so drive rendering and `alternate_links` straight off it. An
unknown `?f=` is a `400` problem. A plain-default field like this negotiates on the query
key alone; the next section adds `Accept`.

### Getting `Accept`-aware negotiation

A plain-default `FormatEnum` field negotiates on the query key alone. For the full OGC
order — `?f=` → `Accept` → default — make the field **optional** (`f: MyFormat | None =
None`) and add a one-line `negotiate(MyFormat.representations(), f=query.f)` in the handler:

```python
--8<-- "tests/examples/negotiation.py:folded_accept"
```

`negotiate()` applies the order for you: an explicit `?f=` wins; otherwise the request's
`Accept` — read ambiently from the active context, so you never pull the header yourself —
with the enum's members (definition order is server-preferred) scored by their media
types; otherwise the `default`. An unknown `?f=` is a `400` problem (the enum field
validates the key), and an `Accept` that lists nothing on offer is a `406`.

Reach for the `Negotiate` dependency when negotiation is the route's primary input; reach
for a `FormatEnum` field — plain-default for key-only, or optional + a one-line
`negotiate()` call for the full `Accept`-aware order — when `?f=` is one field among
several in a query model you already have.

## Reference

See [`gazebo.negotiation`](../reference.md#gazebo.negotiation) (`Representation`,
`negotiate`, `alternate_links`) and the glue's
[`Negotiate`](../reference.md#fastapi-integration) dependency.
