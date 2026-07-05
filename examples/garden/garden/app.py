"""Application wiring: the provider registry, the ``GazeboApp``, and run helpers.

Demonstrates: central scope binding (incl. a qualified replica), a typed override
seam for tests, OpenAPI tags, pluggable proxy trust, and a small request-id ASGI
middleware feeding gazebo's logging filter.
"""

from __future__ import annotations

import uuid

import click

from gazebo.asgi import ASGIApp, Receive, Scope, Send, trust_all
from gazebo.ext.cli import SettingsGroup
from gazebo.ext.uvicorn import default_log_config, serve_command
from gazebo.ext.fastapi import GazeboApp, Overrides, Providers
from gazebo.requestid import use_request_id
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
        # DEMO ONLY: permissive CORS so a browser app can call from any origin.
        # In production pass an explicit origin list, e.g. cors=['https://app.example'].
        cors=True,
        title='Gazebo Gardens',
        description='A tiny OGC-style plant catalog built with gazebo.',
        openapi_tags=tags_metadata(*TAGS),
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(root_router)
    return app


@click.group()
def main() -> None:
    """Gazebo Gardens CLI."""


# `garden serve` documents GARDEN_* settings in --help, runs uvicorn (with
# --workers/--reload), and wires the request-id into logs via gazebo's filter.
# The SettingsGroup owns the option composition and its `rename`: it maps the generated
# `--garden-replica-dsn` flag to a plain `--replica` so it matches the rest of the CLI's
# naming (the env var, GARDEN_REPLICA_DSN, is unchanged).
main.add_command(
    serve_command(
        create_app,
        settings_group=SettingsGroup(Settings, rename={'--garden-replica-dsn': '--replica'}),
        log_config=default_log_config(request_id=True),
    ),
)
