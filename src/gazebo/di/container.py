"""The resolution engine: graph resolution, scopes, lifecycle, checks.

Framework-agnostic. Scopes are named (the HTTP glue uses ``app`` and ``request``);
each entered scope owns a resolution cache and an ``AsyncExitStack`` for teardown.
Recipes declare dependencies as typed parameters, resolved by type; a parameter
typed as a scope's *root* (e.g. the request object) receives that root.
"""

from __future__ import annotations

import inspect

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from gazebo.di.providers import (
    Binding,
    Key,
    Overrides,
    Providers,
    Qualify,
    normalize_recipe,
)


class DIError(Exception):
    """Base class for dependency-injection errors."""


class UnresolvedDependencyError(DIError):
    pass


class ScopeMismatchError(DIError):
    pass


class CircularDependencyError(DIError):
    pass


_MISSING = object()


def _override_recipe(key: Key, value: Any) -> Any:
    """Normalize an override value to a recipe, disambiguating by the key type.

    An instance of the key type is a constant; a class with ``__provide__`` uses
    that recipe (constructed internally, e.g. from settings); any other class is
    used as its own constructor; any other callable is a recipe.
    """
    if isinstance(value, key.type):
        return lambda: value
    if isinstance(value, type):
        provide = getattr(value, '__provide__', None)
        return normalize_recipe(provide if provide is not None else value)
    if callable(value):
        return normalize_recipe(value)
    return lambda: value


@dataclass(frozen=True, slots=True)
class Dep:
    name: str
    type: type | None
    qualifier: str | None
    has_default: bool


def _parse_annotation(ann: Any) -> tuple[type | None, str | None]:
    if get_origin(ann) is Annotated:
        args = get_args(ann)
        base = args[0]
        qualifier = next((m.qualifier for m in args[1:] if isinstance(m, Qualify)), None)
        return (base if isinstance(base, type) else None), qualifier
    return (ann if isinstance(ann, type) else None), None


def _hint_source(recipe: Any) -> Any:
    """The object whose ``__globals__``/annotations resolve string hints.

    Follows bound methods and ``functools.wraps`` chains (so ``@asynccontextmanager``
    recipes resolve against the *user* module, not contextlib), and uses ``__init__``
    for class recipes.
    """
    func = recipe
    if inspect.ismethod(func):
        func = func.__func__
    func = inspect.unwrap(func)
    if isinstance(recipe, type):
        func = inspect.unwrap(recipe.__init__)  # type: ignore[misc]
    return func


def deps_of(recipe: Any) -> list[Dep]:
    try:
        sig = inspect.signature(recipe)
    except (ValueError, TypeError):
        return []
    source = _hint_source(recipe)
    globalns = getattr(source, '__globals__', {})
    # Fast path: resolve all hints at once (best for Annotated extras). On failure
    # (e.g. one unresolvable annotation), fall back to per-parameter resolution so a
    # single bad annotation — often a return type we don't even need — isn't fatal.
    try:
        hints: dict[str, Any] | None = get_type_hints(source, include_extras=True)
    except Exception:  # noqa: BLE001
        hints = None

    deps: list[Dep] = []
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD) or name == 'self':
            continue
        if hints is not None and name in hints:
            ann: Any = hints[name]
        else:
            ann = param.annotation
            if isinstance(ann, str):
                try:
                    ann = eval(ann, globalns)  # noqa: S307 - resolving a type hint
                except Exception:  # noqa: BLE001
                    ann = None
        if ann is inspect.Parameter.empty:
            ann = None
        typ, qualifier = _parse_annotation(ann)
        deps.append(Dep(name, typ, qualifier, param.default is not inspect.Parameter.empty))
    return deps


class ScopeState:
    """An entered scope: a resolution cache + teardown stack, plus parent/root."""

    def __init__(
        self,
        container: Container,
        name: str,
        *,
        parent: ScopeState | None = None,
        root: Any = None,
    ) -> None:
        self.container = container
        self.name = name
        self.parent = parent
        self.root = root
        self.cache: dict[Key, Any] = {}
        self.stack = AsyncExitStack()

    def _scope_named(self, name: str) -> ScopeState:
        state: ScopeState | None = self
        while state is not None:
            if state.name == name:
                return state
            state = state.parent
        raise UnresolvedDependencyError(f'scope {name!r} is not active')

    def _root_for(self, typ: type) -> Any:
        state: ScopeState | None = self
        while state is not None:
            if state.root is not None and isinstance(state.root, typ):
                return state.root
            state = state.parent
        return _MISSING

    async def get(self, key_type: type, qualifier: str | None = None) -> Any:
        """Resolve a value for ``key_type`` within this scope's lineage."""
        key = Key(key_type, qualifier)
        binding = self.container.bindings.get(key)
        if binding is None:
            root = self._root_for(key_type)
            if root is not _MISSING:
                return root
            raise UnresolvedDependencyError(f'no binding or scope root for {key}')
        owner = self._scope_named(binding.scope)
        if key in owner.cache:
            return owner.cache[key]
        value = await self._build(binding, owner)
        owner.cache[key] = value
        return value

    async def _build(self, binding: Binding, owner: ScopeState) -> Any:
        kwargs: dict[str, Any] = {}
        for dep in self.container.deps[binding.key]:
            if dep.type is None:
                if dep.has_default:
                    continue
                raise UnresolvedDependencyError(
                    f'{binding.key}: parameter {dep.name!r} has no resolvable type',
                )
            dep_key = Key(dep.type, dep.qualifier)
            if dep_key in self.container.bindings:
                kwargs[dep.name] = await self.get(dep.type, dep.qualifier)
                continue
            root = self._root_for(dep.type)
            if root is not _MISSING:
                kwargs[dep.name] = root
            elif not dep.has_default:
                raise UnresolvedDependencyError(
                    f'{binding.key}: cannot resolve {dep.name}: {dep.type}',
                )
        result = binding.recipe(**kwargs)
        if hasattr(result, '__aenter__'):
            return await owner.stack.enter_async_context(result)
        if hasattr(result, '__enter__'):
            return owner.stack.enter_context(result)
        if inspect.isawaitable(result):
            return await result
        return result


class Container:
    """A configured, validated injection container."""

    def __init__(
        self,
        providers: Providers,
        *,
        overrides: Overrides | None = None,
        scopes: tuple[str, ...] = ('app', 'request'),
        roots: dict[str, type] | None = None,
    ) -> None:
        self.scopes = tuple(scopes)
        self._index = {name: i for i, name in enumerate(self.scopes)}
        self.roots = dict(roots or {})
        self.bindings = self._merge(providers, overrides)
        self.deps: dict[Key, list[Dep]] = {
            key: deps_of(binding.recipe) for key, binding in self.bindings.items()
        }
        self.check()

    def _merge(self, providers: Providers, overrides: Overrides | None) -> dict[Key, Binding]:
        bindings = providers.bindings
        if overrides:
            for key, value in overrides.values.items():
                if key not in bindings:
                    raise KeyError(f'override for unbound key {key}')
                bindings[key] = Binding(key, bindings[key].scope, _override_recipe(key, value))
        return bindings

    def _scope_index(self, name: str) -> int:
        try:
            return self._index[name]
        except KeyError:
            raise UnresolvedDependencyError(f'unknown scope {name!r}') from None

    def _root_satisfies(self, typ: type, max_index: int) -> bool:
        for name, root_type in self.roots.items():
            if self._scope_index(name) <= max_index and issubclass(typ, root_type):
                return True
        return False

    def check(self) -> None:
        """Validate the graph: missing deps, scope mismatch, cycles. Raises on error."""
        for key, binding in self.bindings.items():
            b_index = self._scope_index(binding.scope)
            for dep in self.deps[key]:
                if dep.type is None:
                    if dep.has_default:
                        continue
                    raise UnresolvedDependencyError(
                        f'{key}: parameter {dep.name!r} has no resolvable type',
                    )
                dep_key = Key(dep.type, dep.qualifier)
                if dep_key in self.bindings:
                    d_index = self._scope_index(self.bindings[dep_key].scope)
                    if d_index > b_index:
                        raise ScopeMismatchError(
                            f'{binding.scope!r} recipe for {key} depends on '
                            f'{self.bindings[dep_key].scope!r}-scoped {dep_key}',
                        )
                    continue
                if self._root_satisfies(dep.type, b_index):
                    continue
                if not dep.has_default:
                    raise UnresolvedDependencyError(
                        f'{key} needs {dep.name}: {dep.type.__name__} which is not bound, '
                        f'not a scope root, and has no default',
                    )
        self._check_cycles()

    def _check_cycles(self) -> None:
        visiting: set[Key] = set()
        done: set[Key] = set()

        def visit(key: Key, path: list[Key]) -> None:
            visiting.add(key)
            for dep in self.deps[key]:
                if dep.type is None:
                    continue
                dep_key = Key(dep.type, dep.qualifier)
                if dep_key not in self.bindings:
                    continue
                if dep_key in visiting:
                    chain = ' -> '.join(str(k) for k in [*path, dep_key])
                    raise CircularDependencyError(chain)
                if dep_key not in done:
                    visit(dep_key, [*path, dep_key])
            visiting.discard(key)
            done.add(key)

        for key in self.bindings:
            if key not in done:
                visit(key, [key])

    def graph(self) -> dict[str, list[str]]:
        """Adjacency of the dependency DAG (for visualization/debugging)."""
        out: dict[str, list[str]] = {}
        for key, deps in self.deps.items():
            edges = []
            for dep in deps:
                if dep.type is None:
                    continue
                dep_key = Key(dep.type, dep.qualifier)
                known = dep_key in self.bindings
                edges.append(str(dep_key) if known else f'{dep.type.__name__}(root/external)')
            out[f'{key} [{self.bindings[key].scope}]'] = edges
        return out

    def reachable_app_keys(self, entry_types: set[type]) -> set[Key]:
        """App-scoped keys reachable from ``entry_types`` (dead-provider elimination)."""
        seen: set[Key] = set()
        targets: set[Key] = set()
        stack = [Key(t) for t in entry_types]
        while stack:
            key = stack.pop()
            if key in seen or key not in self.bindings:
                continue
            seen.add(key)
            if self.bindings[key].scope == 'app':
                targets.add(key)
            for dep in self.deps[key]:
                if dep.type is not None:
                    stack.append(Key(dep.type, dep.qualifier))
        return targets

    @asynccontextmanager
    async def open_app_scope(self, *, eager: set[type] | None = None) -> AsyncIterator[ScopeState]:
        """Enter the app scope, optionally eagerly building reachable app providers."""
        state = ScopeState(self, self.scopes[0])
        try:
            targets = (
                self.reachable_app_keys(eager)
                if eager is not None
                else {k for k, b in self.bindings.items() if b.scope == self.scopes[0]}
            )
            for key in targets:
                await state.get(key.type, key.qualifier)
            yield state
        finally:
            await state.stack.aclose()

    @asynccontextmanager
    async def open_request_scope(
        self,
        app_state: ScopeState,
        *,
        root: Any,
        name: str = 'request',
    ) -> AsyncIterator[ScopeState]:
        """Enter a request (operation) scope as a child of the app scope."""
        state = ScopeState(self, name, parent=app_state, root=root)
        try:
            yield state
        finally:
            await state.stack.aclose()
