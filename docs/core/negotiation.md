# Content negotiation

> Pick a representation from `?f=` (then `Accept`), and link the alternates — without
> gazebo taking a position on HTML or templating.

OGC clients live on `?f=json|html`, with the HTTP `Accept` header as the fallback. The
core ships the `ALTERNATE` rel and an `HTML` media type but no negotiation logic, so
choosing a representation — and advertising the others — was on you. `gazebo.negotiation`
closes that gap with pure *resolution*: given the representations a resource offers, it
picks one and builds the `alternate` links to the rest. It deliberately ships **no HTML
renderer**: turning the chosen representation into bytes (a template, a callable) is the
app's job; gazebo only tells you *which* representation and links the others.

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

## Reference

See [`gazebo.negotiation`](../reference.md#gazebo.negotiation) (`Representation`,
`negotiate`, `alternate_links`) and the glue's
[`Negotiate`](../reference.md#fastapi-integration) dependency.
