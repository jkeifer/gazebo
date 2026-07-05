"""Bare-type injection: signature rewriting and the route-validation guard.

The seam that lets a route declare an injectable parameter by *type* (a type carrying
``__provide__``, or one marked ``Annotated[T, Inject]``) and have it resolved from the
per-request DI scope. ``inject_signature`` rewrites such parameters into FastAPI
``Depends`` at decoration time; ``_validate_routes`` fails loudly when an injectable
parameter slips onto a plain ``APIRouter`` and was never rewritten.
"""

from __future__ import annotations

import contextlib
import inspect
import warnings

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute

from gazebo.di import Container, Key, ScopeState, parse_annotation, resolve_annotation

# The ASGI scope key under which the request-scope middleware publishes the open DI
# ``ScopeState``; the injected resolver reads it back out. Both sides share this name.
_SCOPE_KEY = 'gazebo_request_scope'

# Attribute stamped on an endpoint once ``inject_signature`` has processed it, so a
# re-registration (``include_router`` re-invokes the rewrite) is a cheap no-op and the
# unresolved-hint warning fires at most once per endpoint.
_INJECTED_FLAG = '__gazebo_injection_applied__'


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


@dataclass(frozen=True, slots=True)
class _Candidate:
    """A parameter eligible for injection, paired with its parsed annotation."""

    name: str
    param: inspect.Parameter
    base: type | None
    qualifier: str | None
    meta: tuple[Any, ...]
    resolved: bool


def _candidate_params(endpoint: Callable[..., Any]) -> Iterator[_Candidate]:
    """Yield each injection-eligible parameter of ``endpoint`` with its resolved type.

    Eligible means a positional/keyword parameter with no default (a default already
    marks it as wired or framework-handled, and ``**kwargs`` is never injectable). Each
    annotation is resolved independently and leniently (see :func:`gazebo.di.resolve_annotation`),
    so one unresolvable sibling cannot mask the injectable parameters next to it. This is
    the single source of that resolution rule for both the rewrite and the route guard.
    """
    try:
        sig = inspect.signature(endpoint)
    except (ValueError, TypeError):
        return
    globalns = getattr(inspect.unwrap(endpoint), '__globals__', {})
    for name, param in sig.parameters.items():
        if param.kind is param.VAR_KEYWORD or param.default is not inspect.Parameter.empty:
            continue
        annotation, resolved = resolve_annotation(param.annotation, globalns)
        base, qualifier, meta = parse_annotation(annotation)
        yield _Candidate(name, param, base, qualifier, meta, resolved)


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

    Injectable parameters are discovered via :func:`_candidate_params` (which resolves
    each annotation independently and leniently), so an injectable parameter still wires
    even when a *sibling* annotation cannot be resolved. Idempotent: ``include_router``
    re-invokes this on the same endpoint, so the first application is recorded and later
    calls return early.
    """
    if getattr(endpoint, _INJECTED_FLAG, False):
        return endpoint

    injected: dict[str, inspect.Parameter] = {}
    unresolved: list[str] = []
    for cand in _candidate_params(endpoint):
        if not cand.resolved:
            unresolved.append(cand.name)
        if _is_injectable(cand.base, cand.meta):
            injected[cand.name] = cand.param.replace(
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=Depends(_make_resolver(Key(cand.base, cand.qualifier))),  # type: ignore[arg-type]
                annotation=cand.base,
            )

    if unresolved:
        # A name we cannot resolve might have been injectable; we cannot tell, so it is
        # left un-wired (and FastAPI cannot type it either). Surface it rather than let
        # it become a request-time 500 — the usual cause is an import kept only under
        # ``if TYPE_CHECKING:``.
        qualname = getattr(endpoint, '__qualname__', repr(endpoint))
        names = ', '.join(unresolved)
        warnings.warn(
            f'gazebo could not resolve the type hint for parameter(s) {names} on route '
            f'handler {qualname!r}; if meant to be injected they will NOT be wired. '
            f'Import the annotated types at runtime, not only under TYPE_CHECKING.',
            stacklevel=2,
        )

    new_signature: inspect.Signature | None = None
    if injected:
        # Rewritten params become KEYWORD_ONLY, which must follow the kept positional
        # params (and precede ``**kwargs``) or ``Signature`` rejects the ordering.
        sig = inspect.signature(endpoint)
        kept = [
            p
            for n, p in sig.parameters.items()
            if n not in injected and p.kind is not p.VAR_KEYWORD
        ]
        var_keyword = [p for p in sig.parameters.values() if p.kind is p.VAR_KEYWORD]
        new_signature = sig.replace(parameters=[*kept, *injected.values(), *var_keyword])

    # Both writes target the endpoint object; guard them together so an exotic callable
    # that rejects attribute assignment falls back to FastAPI's own handling uniformly.
    with contextlib.suppress(AttributeError, TypeError):
        if new_signature is not None:
            endpoint.__signature__ = new_signature  # type: ignore[attr-defined]
        setattr(endpoint, _INJECTED_FLAG, True)
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
        for cand in _candidate_params(route.endpoint):
            bound = cand.base is not None and Key(cand.base, cand.qualifier) in container.bindings
            if _is_injectable(cand.base, cand.meta) or bound:
                method = next(iter(route.methods or {'?'}))
                typename = getattr(cand.base, '__name__', cand.base)
                problems.append(f'{method} {route.path}  ({cand.name}: {typename})')
    if problems:
        joined = '\n  '.join(problems)
        raise RuntimeError(
            'these route parameters look injectable but were not rewritten for '
            'injection — declare the route on a GazeboRouter/LinkedRouter (or via '
            f'@app.get), or mark external types Annotated[T, Inject]:\n  {joined}',
        )


def _validate_unique_route_names(app: FastAPI) -> None:
    """Fail loudly when two routes share a name.

    starlette's ``url_for`` resolves a name to its *first* registration, so a duplicate
    name (e.g. two ``LinkedRouter``s both keeping the default ``landing_name='landing'``)
    makes a link meant for one route silently point at the other. Catch it at startup
    rather than shipping wrong URLs. Uses :func:`_iter_api_routes` so lazily-included
    routers are covered, and dedupes by route identity so a route surfaced twice by the
    traversal is not mistaken for a collision.
    """
    by_name: dict[str, list[str]] = {}
    seen: set[int] = set()
    for route in _iter_api_routes(app.routes):
        if id(route) in seen:
            continue
        seen.add(id(route))
        by_name.setdefault(route.name, []).append(route.path)
    duplicates = {name: paths for name, paths in by_name.items() if len(paths) > 1}
    if duplicates:
        joined = '\n  '.join(
            f'{name!r}: {", ".join(paths)}' for name, paths in sorted(duplicates.items())
        )
        raise RuntimeError(
            'these route names are registered more than once, so url_for/deferred links '
            'will resolve to the wrong route — give each route a distinct name (e.g. set '
            f'a distinct landing_name on each LinkedRouter):\n  {joined}',
        )


__all__ = ['Inject', 'inject_signature']
