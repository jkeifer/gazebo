"""Application wiring: the provider registry, the ``GazeboApp``, and run helpers.

Demonstrates: central scope binding (incl. a qualified replica), a typed override
seam for tests, OpenAPI tags, pluggable proxy trust, and a small request-id ASGI
middleware feeding gazebo's logging filter.
"""

from __future__ import annotations

import logging
import uuid

from gazebo.asgi import ASGIApp, Receive, Scope, Send, trust_all
from gazebo.context import RequestIdFilter, use_request_id
from gazebo.ext.fastapi import GazeboApp, Overrides, Providers
from gazebo.tags import Tag, tags_metadata

from .api import root_router
from .resources import (
    Catalog,
    Database,
    Session,
    Settings,
    Tenant,
    User,
    provide_primary,
    provide_replica,
    provide_session,
)

TAGS = [Tag(name='plants', description='Browse and create plants.')]


class RequestIdMiddleware:
    """Pure-ASGI middleware binding a per-request id for the logging filter."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        with use_request_id(uuid.uuid4().hex[:8]):
            await self.app(scope, receive, send)


def build_providers() -> Providers:
    """The composition root for injection — one central place binding type -> scope."""
    providers = Providers()
    providers.app(Settings)
    providers.app(Database, provide_primary)
    providers.app(Database, provide_replica, qualifier='replica')
    providers.app(Catalog)
    providers.request(User)
    providers.request(Tenant)
    providers.request(Session, provide_session)
    return providers


def create_app(*, overrides: Overrides | None = None) -> GazeboApp:
    app = GazeboApp(
        build_providers(),
        overrides=overrides,
        # DEMO ONLY: trust every client's forwarded headers. In production use
        # TrustedClient(...) and/or SharedSecret(...).
        trust=trust_all,
        title='Gazebo Gardens',
        description='A tiny OGC-style plant catalog built with gazebo.',
        openapi_tags=tags_metadata(*TAGS),
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(root_router)
    return app


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter('%(levelname)s [%(request_id)s] %(name)s: %(message)s'),
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


app = create_app()


def main() -> None:
    import uvicorn

    configure_logging()
    uvicorn.run('garden.app:app', host='127.0.0.1', port=8000, reload=False)
