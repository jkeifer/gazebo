# Qualifiers & overrides

> Two small tools: `Qualify` to disambiguate duplicate types, and `Overrides` to
> substitute bindings in tests without touching globals.

## Qualifiers

When two bindings produce the same type — a primary and a replica database — a
bare type can't tell them apart. Tag each with a qualifier: bind the alternate
with `qualifier='replica'`, and request it with
`Annotated[Database, Qualify('replica')]` in a recipe or route parameter. The
unqualified binding stays the default.

```python
--8<-- "tests/examples/qualifiers_overrides.py:qualify"
```

## Overrides

`Overrides` is mechanically a thin `Providers` layer: `.set(T, value)` replaces a
binding's recipe — or supplies a constant instance — keeping the original scope.
It's type-checked (`.set(Settings, 5)` is a type error) and errors if you override
a key that was never bound. Pass it at app construction, so a test swaps real
config or resources for fakes **by parameter** — never by mutating a global, which
keeps tests isolated and parallel-safe.

```python
--8<-- "tests/examples/qualifiers_overrides.py:overrides"
```

## Reference

See [`gazebo.di.providers`](../reference.md#dependency-injection) (`Qualify`,
`Overrides`).
