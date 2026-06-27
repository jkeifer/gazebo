"""FastAPI glue.

Turns a central :class:`~gazebo.di.Providers` registry into a working app:
``GazeboApp`` enters the app scope in its lifespan, opens a request scope per
request (publishing the link ``RequestContext``), and resolves bound types injected
into routes. Routes opt into bare-type injection by being declared on a
``GazeboRouter`` (or directly on the app): any parameter whose type carries a
``__provide__`` recipe, or is marked ``Annotated[T, Inject]``, is resolved from the
per-request DI scope.

Importing this module requires ``fastapi`` (the ``gazebo[fastapi]`` extra).
"""

from __future__ import annotations

import inspect

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError

from gazebo.asgi import (
    ProxyHeadersMiddleware,
    Receive,
    Scope,
    Send,
    TrustPolicy,
    trust_none,
)
from gazebo.context import RequestContext, use_context
from gazebo.di import Container, Key, Overrides, Providers, Qualify, ScopeState
from gazebo.link import Link
from gazebo.ogc import LandingPage
from gazebo.problems import ProblemDetail, ProblemException
from gazebo.rels import MediaType

_SCOPE_KEY = 'gazebo_request_scope'
_STATE_ATTR = 'gazebo_app_state'
_RUNTIME_ATTR = 'gazebo_runtime'


# --- injection marker + signature rewriting -------------------------------


@dataclass(frozen=True, slots=True)
class _Inject:
    """Marker for ``Annotated[T, Inject]`` to force injection of external types."""


Inject = _Inject()

_resolvers: dict[Key, Callable[..., Any]] = {}


def _resolver(key: Key) -> Callable[..., Any]:
    if key not in _resolvers:

        async def resolve(request: Request) -> Any:
            state: ScopeState = request.scope[_SCOPE_KEY]
            return await state.get(key.type, key.qualifier)

        _resolvers[key] = resolve
    return _resolvers[key]


def _parse(ann: Any) -> tuple[type | None, str | None, tuple[Any, ...]]:
    if get_origin(ann) is Annotated:
        args = get_args(ann)
        base = args[0]
        meta = args[1:]
        qualifier = next((m.qualifier for m in meta if isinstance(m, Qualify)), None)
        return (base if isinstance(base, type) else None), qualifier, meta
    return (ann if isinstance(ann, type) else None), None, ()


def _is_injectable(base: type | None, meta: tuple[Any, ...]) -> bool:
    if any(isinstance(m, _Inject) for m in meta):
        return True
    return base is not None and hasattr(base, '__provide__')


def _iter_api_routes(routes: list[Any]) -> Iterator[Any]:
    """Yield every APIRoute, recursing into lazily-included routers.

    FastAPI may keep an included router as a lazy wrapper (``_IncludedRouter`` with
    an ``original_router``) instead of flattening its routes into the parent.
    """
    from fastapi.routing import APIRoute

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
        base, qualifier, meta = _parse(hints.get(name, param.annotation))
        if _is_injectable(base, meta):
            injected.append(
                param.replace(
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=Depends(_resolver(Key(base, qualifier))),  # type: ignore[arg-type]
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


# --- request context adapter ----------------------------------------------


class RequestContextAdapter:
    """Adapts a FastAPI ``Request`` to the :class:`RequestContext` protocol."""

    def __init__(self, request: Request) -> None:
        self._request = request

    @property
    def base_url(self) -> str:
        return str(self._request.base_url)

    @property
    def url(self) -> str:
        return str(self._request.url)

    @property
    def query_params(self) -> Mapping[str, str]:
        return dict(self._request.query_params)

    def url_for(self, name: str, /, **path: object) -> str:
        return str(self._request.url_for(name, **path))


def _provide_request_context(request: Request) -> RequestContext:
    return RequestContextAdapter(request)


# --- problem handlers -----------------------------------------------------


def _problem_response(problem: ProblemDetail) -> Response:
    return Response(
        content=problem.model_dump_json(),
        status_code=problem.status,
        media_type=MediaType.PROBLEM,
    )


async def problem_exception_handler(request: Request, exc: ProblemException) -> Response:
    return _problem_response(exc.problem)


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> Response:
    from fastapi.encoders import jsonable_encoder

    problem = ProblemDetail(
        title='Unprocessable Entity',
        status=422,
        detail=f'request validation failed: {len(exc.errors())} error(s)',
        errors=jsonable_encoder(exc.errors()),  # type: ignore[call-arg]
    )
    return _problem_response(problem)


# --- runtime + request-scope middleware -----------------------------------


class _Runtime:
    """Shared injection state attached to an app (the container + open app scope)."""

    def __init__(self, container: Container) -> None:
        self.container = container
        self.app_state: ScopeState | None = None


class _RequestScopeMiddleware:
    """Opens a DI request scope per request and publishes the link context."""

    def __init__(self, app: Any, *, runtime: _Runtime) -> None:
        self.app = app
        self.runtime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        if self.runtime.app_state is None:
            raise RuntimeError('gazebo app scope is not open (is the app started?)')
        request = Request(scope, receive)
        async with self.runtime.container.open_request_scope(
            self.runtime.app_state,
            root=request,
        ) as state:
            scope[_SCOPE_KEY] = state
            ctx = await state.get(RequestContext)
            with use_context(ctx):
                await self.app(scope, receive, send)


# --- routers --------------------------------------------------------------


class GazeboRouter(APIRouter):
    """An ``APIRouter`` that rewrites routes for bare-type injection at decoration."""

    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        return super().add_api_route(path, inject_signature(endpoint), **kwargs)


class LinkedRouter(GazeboRouter):
    """A :class:`GazeboRouter` that auto-generates a hierarchical landing page.

    Mounts a landing endpoint at its root; ``include_router`` of another
    ``LinkedRouter`` (that declares a ``rel``) adds a link to that child's landing
    page, so the hierarchy falls out of router nesting.
    """

    def __init__(
        self,
        *args: Any,
        rel: str | None = None,
        title: str = '',
        description: str = '',
        landing_name: str = 'landing',
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.rel = rel
        self.title = title
        self.description = description
        self.landing_name = landing_name
        self._link_specs: list[tuple[str, str, str | None, str]] = []
        self._mount_landing()

    def _mount_landing(self) -> None:
        router = self

        @self.get('/', name=self.landing_name, response_model=LandingPage)
        async def landing() -> LandingPage:
            links = [Link.self_link(), Link.root_link()]
            for rel, name, title, media in router._link_specs:
                links.append(Link.to_route(name, rel=rel, title=title, type=media))
            return LandingPage(
                title=router.title,
                description=router.description,
                links=links,
            )

    def add_link(
        self,
        rel: str,
        route_name: str,
        *,
        title: str | None = None,
        type: str = MediaType.JSON,
    ) -> None:
        self._link_specs.append((rel, route_name, title, type))

    def include_router(self, router: Any, *, prefix: str = '', **kwargs: Any) -> None:
        super().include_router(router, prefix=prefix, **kwargs)
        if isinstance(router, LinkedRouter) and router.rel:
            self.add_link(router.rel, router.landing_name, title=router.title or None)


# --- upgrading any FastAPI app + the GazeboApp subclass -------------------


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
            base, qualifier, meta = _parse(hints.get(name, param.annotation))
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


def _add_health(app: FastAPI, runtime: _Runtime, path: str) -> None:
    @app.get(path, name='gazebo_health', include_in_schema=False)
    async def health() -> dict[str, Any]:
        checks: dict[str, str] = {}
        ok = True
        state = runtime.app_state
        if state is not None:
            for key, value in list(state.cache.items()):
                probe = getattr(value, '__health__', None)
                if probe is None:
                    continue
                try:
                    result = probe()
                    if inspect.isawaitable(result):
                        result = await result
                    checks[str(key)] = 'ok' if result else 'fail'
                    ok = ok and bool(result)
                except Exception:  # noqa: BLE001
                    checks[str(key)] = 'error'
                    ok = False
        return {'status': 'healthy' if ok else 'unhealthy', 'checks': checks}


def upgrade(
    app: FastAPI,
    providers: Providers | None = None,
    *,
    overrides: Overrides | None = None,
    trust: TrustPolicy = trust_none,
    health_path: str | None = '/health',
) -> FastAPI:
    """Add gazebo's injection/context machinery to an *existing* FastAPI app.

    Equivalent to constructing a :class:`GazeboApp`, but applied to an app you did
    not create (e.g. one built by a framework or with custom config). Wraps the
    app's lifespan (opening the app scope), installs the proxy-headers and
    request-scope middleware, registers the problem handlers, and rewrites
    ``@app.get`` routes for injection. Injectable routes still belong on a
    ``GazeboRouter`` (or ``@app.get`` on this app). Idempotent.
    """
    if getattr(app.state, _RUNTIME_ATTR, None) is not None:
        return app

    providers = providers or Providers()
    if Key(RequestContext) not in providers.bindings:  # type: ignore[type-abstract]
        providers.request(RequestContext, _provide_request_context)  # type: ignore[type-abstract]
    container = Container(providers, overrides=overrides, roots={'request': Request})
    runtime = _Runtime(container)
    setattr(app.state, _RUNTIME_ATTR, runtime)

    original_add = app.router.add_api_route

    def add_api_route(path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        return original_add(path, inject_signature(endpoint), **kwargs)

    app.router.add_api_route = add_api_route  # type: ignore[method-assign]

    app.add_middleware(ProxyHeadersMiddleware, trust=trust)
    app.add_middleware(_RequestScopeMiddleware, runtime=runtime)
    app.add_exception_handler(ProblemException, problem_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: FastAPI) -> AsyncIterator[None]:
        _validate_routes(a, container)
        async with container.open_app_scope() as app_state:
            runtime.app_state = app_state
            setattr(a.state, _STATE_ATTR, app_state)
            try:
                async with previous_lifespan(a):
                    yield
            finally:
                runtime.app_state = None

    app.router.lifespan_context = lifespan  # type: ignore[assignment]

    if health_path is not None:
        _add_health(app, runtime, health_path)
    return app


def _runtime_of(app: FastAPI) -> _Runtime:
    runtime = getattr(app.state, _RUNTIME_ATTR, None)
    if runtime is None:
        raise RuntimeError(
            'app has not been upgraded with gazebo (call upgrade() or use GazeboApp)',
        )
    return runtime


class GazeboApp(FastAPI):
    """A FastAPI app wired from a :class:`Providers` registry (thin over :func:`upgrade`)."""

    def __init__(
        self,
        providers: Providers | None = None,
        *,
        overrides: Overrides | None = None,
        trust: TrustPolicy = trust_none,
        health_path: str | None = '/health',
        **fastapi_kwargs: Any,
    ) -> None:
        super().__init__(**fastapi_kwargs)
        upgrade(
            self,
            providers,
            overrides=overrides,
            trust=trust,
            health_path=health_path,
        )

    @property
    def container(self) -> Container:
        return _runtime_of(self).container

    @property
    def app_state(self) -> ScopeState:
        state = _runtime_of(self).app_state
        if state is None:
            raise RuntimeError('app scope is not open (is the app started?)')
        return state


def forward_lifespans(*subapps: FastAPI) -> Callable[[FastAPI], Any]:
    """A lifespan that runs each mounted sub-app's lifespan.

    Use when mounting a ``GazeboApp`` under a root app, since a mounted sub-app's
    lifespan is not run automatically::

        root = FastAPI(lifespan=forward_lifespans(sub))
        root.mount('/api', sub)
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for sub in subapps:
                await stack.enter_async_context(sub.router.lifespan_context(sub))
            yield

    return lifespan


def link_to(endpoint: Callable[..., Any] | str, *, rel: str, **kwargs: Any) -> Link:
    """Build a deferred link to a route, by endpoint callable or route name."""
    name = endpoint if isinstance(endpoint, str) else endpoint.__name__
    return Link.to_route(name, rel=rel, **kwargs)


__all__ = [
    'GazeboApp',
    'GazeboRouter',
    'Inject',
    'LinkedRouter',
    'Overrides',
    'Providers',
    'RequestContextAdapter',
    'forward_lifespans',
    'inject_signature',
    'link_to',
    'problem_exception_handler',
    'upgrade',
    'validation_exception_handler',
]
