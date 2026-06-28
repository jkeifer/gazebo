"""Bare-type injection: signature rewriting and the route-validation guard.

The seam that lets a route declare an injectable parameter by *type* (a type carrying
``__provide__``, or one marked ``Annotated[T, Inject]``) and have it resolved from the
per-request DI scope. ``inject_signature`` rewrites such parameters into FastAPI
``Depends`` at decoration time; ``_validate_routes`` fails loudly when an injectable
parameter slips onto a plain ``APIRouter`` and was never rewritten.
"""

from __future__ import annotations

import inspect

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, get_type_hints

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute

from gazebo.di import Container, Key, ScopeState, parse_annotation

# The ASGI scope key under which the request-scope middleware publishes the open DI
# ``ScopeState``; the injected resolver reads it back out. Both sides share this name.
_SCOPE_KEY = 'gazebo_request_scope'


@dataclass(frozen=True, slots=True)
class _Inject:
    """Marker for ``Annotated[T, Inject]`` to force injection of external types."""


Inject = _Inject()


def _make_resolver(key: Key) -> Callable[..., Any]:
    """Build the FastAPI dependency that resolves ``key`` from the request scope."""

    async def resolve(request: Request) -> Any:
        state: ScopeState = request.scope[_SCOPE_KEY]
        return await state.get(key.type, key.qualifier)

    return resolve


def _is_injectable(base: type | None, meta: tuple[Any, ...]) -> bool:
    if any(isinstance(m, _Inject) for m in meta):
        return True
    return base is not None and hasattr(base, '__provide__')


def _iter_api_routes(routes: list[Any]) -> Iterator[APIRoute]:
    """Yield every APIRoute, recursing into lazily-included routers.

    FastAPI may keep an included router as a lazy wrapper (``_IncludedRouter`` with
    an ``original_router``) instead of flattening its routes into the parent.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        else:
            sub = getattr(route, 'original_router', None)
            if sub is not None:
                yield from _iter_api_routes(sub.routes)


def inject_signature(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Rewrite ``endpoint`` so injectable params resolve from the DI scope.

    Idempotent: parameters already carrying a default (e.g. a prior ``Depends``)
    are left alone, so re-registration via ``include_router`` is a no-op.
    """
    try:
        sig = inspect.signature(endpoint)
    except (ValueError, TypeError):
        return endpoint
    try:
        hints = get_type_hints(inspect.unwrap(endpoint), include_extras=True)
    except Exception:  # noqa: BLE001
        hints = {}

    kept: list[inspect.Parameter] = []
    injected: list[inspect.Parameter] = []
    var_keyword: list[inspect.Parameter] = []

    for name, param in sig.parameters.items():
        if param.kind is param.VAR_KEYWORD:
            var_keyword.append(param)
            continue
        if param.default is not inspect.Parameter.empty:
            kept.append(param)
            continue
        base, qualifier, meta = parse_annotation(hints.get(name, param.annotation))
        if _is_injectable(base, meta):
            injected.append(
                param.replace(
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=Depends(_make_resolver(Key(base, qualifier))),  # type: ignore[arg-type]
                    annotation=base,
                ),
            )
        else:
            kept.append(param)

    if injected:
        endpoint.__signature__ = sig.replace(  # type: ignore[attr-defined]
            parameters=[*kept, *injected, *var_keyword],
        )
    return endpoint


def _validate_routes(app: FastAPI, container: Container) -> None:
    """Fail loudly if a route has an injectable param that wasn't rewritten.

    Catches the footgun of declaring an injectable-typed route on a plain
    ``APIRouter`` (where FastAPI silently treats a dataclass/pydantic type as a
    request body) instead of a ``GazeboRouter``. Rewritten params carry a
    ``Depends`` default, so they are skipped; a bare injectable param is the error.
    """
    problems: list[str] = []
    for route in _iter_api_routes(app.routes):
        try:
            sig = inspect.signature(route.endpoint)
            hints = get_type_hints(inspect.unwrap(route.endpoint), include_extras=True)
        except (ValueError, TypeError):
            continue
        for name, param in sig.parameters.items():
            if param.default is not inspect.Parameter.empty:
                continue
            base, qualifier, meta = parse_annotation(hints.get(name, param.annotation))
            bound = base is not None and Key(base, qualifier) in container.bindings
            if _is_injectable(base, meta) or bound:
                method = next(iter(route.methods or {'?'}))
                typename = getattr(base, '__name__', base)
                problems.append(f'{method} {route.path}  ({name}: {typename})')
    if problems:
        joined = '\n  '.join(problems)
        raise RuntimeError(
            'these route parameters look injectable but were not rewritten for '
            'injection — declare the route on a GazeboRouter/LinkedRouter (or via '
            f'@app.get), or mark external types Annotated[T, Inject]:\n  {joined}',
        )


__all__ = ['Inject', 'inject_signature']
