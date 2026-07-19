"""Routers that opt routes into bare-type injection and hierarchical landing pages.

``GazeboRouter`` rewrites each route's signature for injection at decoration time.
``LinkedRouter`` adds an auto-generated landing page whose links fall out of router
nesting, so an OGC-style link hierarchy mirrors how the routers are mounted.
``RootRouter`` is the service-root variant: its landing additionally carries the
service-level wiring (``service-desc``/``service-doc`` links, app title/description,
and an auto-mounted ``/conformance`` whose baseline is derived from the running app).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from fastapi import APIRouter, Request

from gazebo.ext.fastapi.injection import fold_negotiated_responses, inject_signature
from gazebo.link import Link
from gazebo.ogc import Conformance, ConformanceDeclaration, LandingPage
from gazebo.rels import MediaType, Rel


class GazeboRouter(APIRouter):
    """An ``APIRouter`` that rewrites routes for bare-type injection at decoration."""

    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        kwargs = fold_negotiated_responses(endpoint, kwargs)
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
        async def landing(request: Request) -> LandingPage:
            return router._landing_page(request)

    def _landing_page(self, request: Request) -> LandingPage:
        """Build this router's landing page. Subclasses extend the link set here."""
        links = [Link.self_link(), Link.root_link()]
        for rel, name, title, media in self._link_specs:
            links.append(Link.to_route(name, rel=rel, title=title, type=media))
        return LandingPage(title=self.title, description=self.description, links=links)

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


class RootRouter(LinkedRouter):
    """The service's root landing page: hierarchy plus service-level wiring.

    A :class:`LinkedRouter` for the top of the tree. Beyond the hierarchical landing
    page, its landing page additionally:

    - emits ``service-desc``/``service-doc`` links to the app's OpenAPI document and
      its docs UI (each omitted when the app has that URL disabled),
    - falls back its ``title``/``description`` to the app's when not set explicitly
      (so the service name lives in one place — on the app), and
    - links to a ``/conformance`` declaration it auto-mounts. That declaration's
      baseline (``core``/``landing-page``/``json``, plus ``oas30`` when the app exposes
      OpenAPI) is derived from the *running app*, then merged with any conformance
      classes you contribute — so the declaration stays honest instead of drifting
      from what's actually wired.

    Contribute feature-level classes via ``conformance=`` (a :class:`Conformance` or a
    list of class URIs), e.g. ``conformance=[*filter_conformance_classes()]``.
    """

    def __init__(
        self,
        *args: Any,
        conformance: Conformance | Iterable[str] | None = None,
        conformance_name: str = 'conformance',
        conformance_path: str | None = '/conformance',
        **kwargs: Any,
    ) -> None:
        self._extra_conformance = (
            conformance
            if isinstance(conformance, Conformance)
            else Conformance(*(conformance or ()))
        )
        self._conformance_name = conformance_name
        self._conformance_path = conformance_path
        super().__init__(*args, **kwargs)
        if conformance_path is not None:
            self._mount_conformance(conformance_path)

    def _mount_conformance(self, path: str) -> None:
        router = self

        @self.get(path, name=self._conformance_name, response_model=ConformanceDeclaration)
        async def conformance(request: Request) -> ConformanceDeclaration:
            return router._conformance_declaration(request)

    def _conformance_declaration(self, request: Request) -> ConformanceDeclaration:
        # Baseline derived from the running app: a landing page + JSON are always true
        # here; OAS30 holds only when the app actually exposes an OpenAPI document.
        conf = Conformance(Conformance.CORE, Conformance.LANDING_PAGE, Conformance.JSON)
        if request.app.openapi_url:
            conf.add(Conformance.OAS30)
        conf.add(*self._extra_conformance.uris)
        return conf.declaration()

    def _landing_page(self, request: Request) -> LandingPage:
        page = super()._landing_page(request)
        if not self.title:
            # Falls back to the app's title — which is FastAPI's default ('FastAPI')
            # when the app sets none either, so the service name belongs on the app.
            page.title = request.app.title
        if not self.description and request.app.description:
            page.description = request.app.description
        page.links.extend(self._service_links(request))
        return page

    def _service_links(self, request: Request) -> list[Link]:
        base = str(request.base_url).rstrip('/')
        openapi_url = request.app.openapi_url
        links: list[Link] = []
        if self._conformance_path is not None:
            links.append(
                Link.to_route(
                    self._conformance_name,
                    rel=Rel.CONFORMANCE,
                    type=MediaType.JSON,
                    title='Conformance',
                ),
            )
        if openapi_url:
            links.append(
                Link(
                    href=base + openapi_url,
                    rel=Rel.SERVICE_DESC,
                    type=MediaType.OPENAPI,
                    title='API definition',
                ),
            )
        # The docs UI fetches the OpenAPI document, so FastAPI only mounts it when
        # openapi_url is set too — don't advertise a service-doc that 404s without it.
        if openapi_url and request.app.docs_url:
            links.append(
                Link(
                    href=base + request.app.docs_url,
                    rel=Rel.SERVICE_DOC,
                    type=MediaType.HTML,
                    title='API documentation',
                ),
            )
        return links


__all__ = ['GazeboRouter', 'LinkedRouter', 'RootRouter']
