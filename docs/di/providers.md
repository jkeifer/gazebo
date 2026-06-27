# Providers & recipes

> The central registry that binds each type to the recipe that builds it and the
> scope it lives in.

## The registry

`Providers` is the one place that says what builds each type and how long it
lives. It's chainable and router-style: `.app(T)` binds `T` to the app scope,
`.request(T)` to the request scope, and `.bind(T, recipe, scope=...)` is the
general form. Keys are types, optionally plus a
[qualifier](qualifiers-overrides.md).

```python
--8<-- "tests/examples/providers.py:registry"
```

## Recipes

A *recipe* is any callable that builds the value, and its parameters are
themselves resolved by type. gazebo accepts every natural form:

- a plain or `async` function;
- a sync or async **generator**, wrapped automatically as a context manager so
  its post-`yield` code runs at teardown;
- an explicit `(async)` context manager;
- a class with no recipe, used as its own constructor.

So a resource that must be cleaned up is just a generator that yields it.

## Colocated `__provide__`

The tidiest place for a recipe is on the type itself, as a `__provide__`
classmethod — then `providers.app(Database)` needs no separate recipe, and the
recipe sits next to what it builds. `__provide__` takes its dependencies as typed
parameters like any recipe:

```python
--8<-- "tests/examples/providers.py:recipes"
```

## Standalone recipes (external types)

For types you can't add `__provide__` to — a third-party `Session`, a stdlib
object — pass a standalone recipe as the second argument to `.bind`/`.app`/
`.request`. It still declares its dependencies by type. (Injecting such a type
into a *route* additionally needs the
[`Inject` marker](../fastapi/routers.md#external-types-the-inject-marker), since
there's no `__provide__` for the glue to detect.)

```python
--8<-- "tests/examples/providers.py:external"
```

## Reference

See [`gazebo.di.providers`](../reference.md#dependency-injection).
