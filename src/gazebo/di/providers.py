"""Provider registration: central, typed, scope-bound.

A *recipe* is a callable that builds a value; its key is the type it produces. A
recipe may be colocated as a ``__provide__`` classmethod on the type, or supplied
standalone (for external types). Scope is a wiring decision, bound here — never a
property of the type.
"""

from __future__ import annotations

import inspect

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass, field
from typing import (
    Annotated,
    Any,
    Protocol,
    Self,
    get_args,
    get_origin,
    overload,
    runtime_checkable,
)

type Recipe[T] = Callable[
    ...,
    T
    | Awaitable[T]
    | Iterator[T]
    | AsyncIterator[T]
    | AbstractContextManager[T]
    | AbstractAsyncContextManager[T],
]
"""A callable building T: sync/async function, (async) generator, or (async) CM."""


@runtime_checkable
class HasProvide(Protocol):
    """A type that colocates its own recipe as a ``__provide__`` classmethod."""

    @classmethod
    def __provide__(cls, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class Qualify:
    """Annotation marker to disambiguate duplicate types.

    >>> def h(db: Annotated[Database, Qualify('replica')]): ...
    """

    qualifier: str


def parse_annotation(ann: Any) -> tuple[type | None, str | None, tuple[Any, ...]]:
    """Split a type annotation into ``(base type, Qualify qualifier, metadata)``.

    For ``Annotated[T, ...]`` returns ``T`` (when it is a class), the qualifier from
    any :class:`Qualify` marker, and the remaining ``Annotated`` metadata. For a plain
    annotation the metadata tuple is empty. A non-class base resolves to ``None`` so
    callers can treat it as unresolvable.
    """
    if get_origin(ann) is Annotated:
        args = get_args(ann)
        base = args[0]
        meta = args[1:]
        qualifier = next((m.qualifier for m in meta if isinstance(m, Qualify)), None)
        return (base if isinstance(base, type) else None), qualifier, meta
    return (ann if isinstance(ann, type) else None), None, ()


@dataclass(frozen=True, slots=True)
class Key:
    """A registry key: a type plus an optional qualifier."""

    type: type
    qualifier: str | None = None

    def __str__(self) -> str:
        name = getattr(self.type, '__name__', repr(self.type))
        return f'{name}#{self.qualifier}' if self.qualifier else name


@dataclass
class Binding:
    """A bound recipe: what builds a key, and in which scope."""

    key: Key
    scope: str
    recipe: Callable[..., Any]


def normalize_recipe(recipe: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap raw (async) generator recipes as context managers.

    Already-decorated CMs, plain functions, async functions, and classes pass
    through unchanged.
    """
    if inspect.isasyncgenfunction(recipe):
        return asynccontextmanager(recipe)
    if inspect.isgeneratorfunction(recipe):
        return contextmanager(recipe)
    return recipe


class Providers:
    """The central registry binding each type to a scope (and its recipe)."""

    def __init__(self) -> None:
        self._bindings: dict[Key, Binding] = {}

    @overload
    def bind[T: HasProvide](
        self,
        key: type[T],
        *,
        scope: str,
        qualifier: str | None = None,
    ) -> Self: ...
    @overload
    def bind[T](
        self,
        key: type[T],
        recipe: Recipe[T],
        *,
        scope: str,
        qualifier: str | None = None,
    ) -> Self: ...

    def bind(
        self,
        key: type,
        recipe: Recipe[Any] | None = None,
        *,
        scope: str,
        qualifier: str | None = None,
    ) -> Self:
        if recipe is None:
            recipe = getattr(key, '__provide__', None)
            if recipe is None:
                raise TypeError(
                    f'{key.__name__} has no __provide__; supply a recipe to bind it',
                )
        k = Key(key, qualifier)
        self._bindings[k] = Binding(k, scope, normalize_recipe(recipe))
        return self

    @overload
    def app[T: HasProvide](self, key: type[T], *, qualifier: str | None = None) -> Self: ...
    @overload
    def app[T](
        self,
        key: type[T],
        recipe: Recipe[T],
        *,
        qualifier: str | None = None,
    ) -> Self: ...

    def app(
        self,
        key: type,
        recipe: Recipe[Any] | None = None,
        *,
        qualifier: str | None = None,
    ) -> Self:
        return self.bind(key, recipe, scope='app', qualifier=qualifier)  # type: ignore[arg-type]

    @overload
    def request[T: HasProvide](self, key: type[T], *, qualifier: str | None = None) -> Self: ...
    @overload
    def request[T](
        self,
        key: type[T],
        recipe: Recipe[T],
        *,
        qualifier: str | None = None,
    ) -> Self: ...

    def request(
        self,
        key: type,
        recipe: Recipe[Any] | None = None,
        *,
        qualifier: str | None = None,
    ) -> Self:
        return self.bind(key, recipe, scope='request', qualifier=qualifier)  # type: ignore[arg-type]

    @property
    def bindings(self) -> dict[Key, Binding]:
        return dict(self._bindings)

    def keys(self) -> set[Key]:
        return set(self._bindings)


@dataclass
class Overrides:
    """A typed layer of replacements for bound recipes/values.

    Mechanically a partial ``Providers`` layer: it replaces a binding's recipe (or
    supplies a constant instance), inheriting the binding's scope.
    """

    _values: dict[Key, Any] = field(default_factory=dict)

    def set[T](self, key: type[T], value: T | Recipe[T], *, qualifier: str | None = None) -> Self:
        self._values[Key(key, qualifier)] = value
        return self

    @property
    def values(self) -> dict[Key, Any]:
        return dict(self._values)
