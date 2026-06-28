"""Routers that opt routes into bare-type injection and hierarchical landing pages.

``GazeboRouter`` rewrites each route's signature for injection at decoration time.
``LinkedRouter`` adds an auto-generated landing page whose links fall out of router
nesting, so an OGC-style link hierarchy mirrors how the routers are mounted.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from gazebo.ext.fastapi.injection import inject_signature
from gazebo.link import Link
from gazebo.ogc import LandingPage
from gazebo.rels import MediaType


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


__all__ = ['GazeboRouter', 'LinkedRouter']
