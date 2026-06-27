# Constants & tags

> Typed `Rel` and `MediaType` enums that kill stringly-typed `rel`/`type` bugs,
> plus OpenAPI tag helpers.

## Rel and MediaType

`Rel` and `MediaType` are `StrEnum`s, so their members *are* strings — they drop
straight into `Link(rel=Rel.SELF, type=MediaType.JSON)` and serialize as their
plain value, while giving you autocomplete and catching typos that a bare string
wouldn't. `Rel` covers the IANA/OGC relations (`self`, `root`, `next`, `prev`,
`items`, `collection`, ...); `MediaType` the common types (`application/json`,
`application/geo+json`, `application/problem+json`, ...). Full lists in the
[reference](../reference.md#gazebo.rels).

```python
--8<-- "tests/examples/constants.py:rels"
```

## OpenAPI tags

`Tag`/`TagDocs` model OpenAPI tags (with `external_docs` serializing as
`externalDocs`), and `tags_metadata(*tags)` builds the list FastAPI wants for
`openapi_tags`. Optional sugar for grouping endpoints in the Swagger UI — reach
for it once you have enough routes to want sections.

```python
--8<-- "tests/examples/constants.py:tags"
```

## Reference

See [`gazebo.rels`](../reference.md#gazebo.rels) and
[`gazebo.tags`](../reference.md#gazebo.tags).
