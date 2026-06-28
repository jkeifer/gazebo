"""App wiring: the request-scope middleware, ``upgrade``, and ``GazeboApp``.

Ties the pieces together. ``upgrade`` adds gazebo's machinery to any FastAPI app —
proxy headers, the per-request DI scope (which publishes the link ``RequestContext``),
the problem handlers, route injection, CORS, and a health endpoint. ``GazeboApp`` is a
thin ``FastAPI`` subclass over ``upgrade``; ``forward_lifespans`` runs a mounted
sub-app's lifespan.
"""

from __future__ import annotations

import inspect

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
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
from gazebo.di import Container, Key, Overrides, Providers, ScopeState
from gazebo.ext.fastapi.context import _provide_request_context
from gazebo.ext.fastapi.cors import Cors, CorsConfig
from gazebo.ext.fastapi.injection import _SCOPE_KEY, _validate_routes, inject_signature
from gazebo.ext.fastapi.problems import (
    param_exception_handler,
    problem_exception_handler,
    validation_exception_handler,
)
from gazebo.params import ParamError
from gazebo.problems import ProblemException

_STATE_ATTR = 'gazebo_app_state'
_RUNTIME_ATTR = 'gazebo_runtime'


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


def _add_health(app: FastAPI, runtime: _Runtime, path: str) -> None:
    @app.get(path, name='gazebo_health', include_in_schema=False)
    async def health() -> dict[str, Any]:
        checks: dict[str, str] = {}
        ok = True
        state = runtime.app_state
        if state is not None:
            for name, probe in state.health_probes():
                try:
                    result = probe()
                    if inspect.isawaitable(result):
                        result = await result
                    checks[name] = 'ok' if result else 'fail'
                    ok = ok and bool(result)
                except Exception:  # noqa: BLE001
                    checks[name] = 'error'
                    ok = False
        return {'status': 'healthy' if ok else 'unhealthy', 'checks': checks}


def upgrade(
    app: FastAPI,
    providers: Providers | None = None,
    *,
    overrides: Overrides | None = None,
    trust: TrustPolicy = trust_none,
    cors: Cors = None,
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
    # Added last so it is the outermost middleware: CORS then handles preflight
    # requests and attaches headers to every response, including problem responses.
    if (cors_config := CorsConfig.resolve(cors)) is not None:
        cors_config.apply(app)
    app.add_exception_handler(ProblemException, problem_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ParamError, param_exception_handler)  # type: ignore[arg-type]

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
        cors: Cors = None,
        health_path: str | None = '/health',
        **fastapi_kwargs: Any,
    ) -> None:
        super().__init__(**fastapi_kwargs)
        upgrade(
            self,
            providers,
            overrides=overrides,
            trust=trust,
            cors=cors,
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


__all__ = ['GazeboApp', 'forward_lifespans', 'upgrade']
