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
rather than adding a separate dependency. The supported format keys are a *closed set*
you own, so — as with [`crs`](params.md#folded-into-your-own-query-model) — gazebo gives
you a base enum to subclass: [`FormatEnum`](../reference.md#gazebo.negotiation.FormatEnum),
a `StrEnum` whose members are your `?f=` keys. It is a real class, so it drops onto your
model as an ordinary field type (no `type: ignore`), pydantic validates membership
natively, and FastAPI renders it as an `enum` query param carrying the shared `f`
description:

```python
--8<-- "tests/examples/negotiation.py:folded"
```

A folded field only ever sees `?f=` — there is no `Accept` header at model-validation
time — so it validates the query key alone; give the field a default so an absent `?f=`
resolves to it. The enum carries *keys*, not `Representation`s, so map the chosen member
to the `Representation` you serve (a small `{key: rep}` dict) to drive rendering and
`alternate_links`. An unknown `?f=` is a `400` problem.

Reach for the `Negotiate` dependency instead when you need `Accept`-header negotiation
(and its `406`); reach for a `FormatEnum` field when `?f=` is one field among several in
a query model you already have.

## Reference

See [`gazebo.negotiation`](../reference.md#gazebo.negotiation) (`Representation`,
`negotiate`, `alternate_links`) and the glue's
[`Negotiate`](../reference.md#fastapi-integration) dependency.
