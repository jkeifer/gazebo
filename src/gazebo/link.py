"""The ``Link`` model with deferred-href resolution.

A link's ``href`` may be a plain URL *or* a callable taking the active
:class:`~gazebo.context.RequestContext` and returning a URL. Callable hrefs are
resolved during JSON serialization, so links can be constructed in business logic
with no request in hand. Resolution pulls the context from
:data:`~gazebo.context.link_context` (set by the framework glue), falling back to
a pydantic serialization ``context``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    AnyUrl,
    ConfigDict,
    Field,
    FieldSerializationInfo,
    PlainSerializer,
    WithJsonSchema,
)

from gazebo.context import RequestContext, resolve_context
from gazebo.rels import MediaType, Rel
from gazebo.serialization import OmitNullModel

type UrlResolver = Callable[[RequestContext], object]
"""A callable that, given the request context, returns a URL (str or AnyUrl)."""


def _resolve_href(value: UrlResolver, info: FieldSerializationInfo) -> str:
    ctx = resolve_context(info.context)
    if ctx is None:
        raise ValueError(
            'no request context available to resolve a callable link href; '
            'set gazebo.context.link_context or pass model_dump(context={"request": ...})',
        )
    try:
        result = value(ctx)
    except Exception as e:
        raise ValueError('link href resolver raised') from e
    return str(result)


def _to_url(value: object) -> AnyUrl:
    return value if isinstance(value, AnyUrl) else AnyUrl(str(value))


type Url = Annotated[
    (
        Annotated[
            UrlResolver,
            PlainSerializer(_resolve_href, return_type=str, when_used='json'),
        ]
        | Annotated[Any, AfterValidator(_to_url)]
    ),
    Field(union_mode='left_to_right'),
    WithJsonSchema({'type': 'string', 'format': 'uri'}),
]
"""A URL field that accepts either a resolver callable or a concrete URL value."""


class Link(OmitNullModel):
    """An OGC-style link. Null fields are omitted on JSON serialization."""

    model_config = ConfigDict(extra='allow')

    href: Url
    rel: str
    type: str | None = None
    title: str | None = None
    method: str | None = None
    headers: dict[str, str | list[str]] | None = None
    body: Any = None

    # --- factories (framework-agnostic; resolve via RequestContext) -------

    @classmethod
    def self_link(
        cls,
        href: Url | None = None,
        *,
        rel: str = Rel.SELF,
        type: str | None = MediaType.JSON,
        **kwargs: Any,
    ) -> Self:
        """Link to the current request URL (absolute, proxy-correct)."""
        return cls.model_validate(
            {
                'href': href if href is not None else (lambda ctx: ctx.url),
                'rel': rel,
                'type': type,
                **kwargs,
            },
        )

    @classmethod
    def root_link(
        cls,
        *,
        landing: str = 'landing',
        rel: str = Rel.ROOT,
        type: str | None = MediaType.JSON,
        **kwargs: Any,
    ) -> Self:
        """Link to the API root/landing page, resolved by route name."""
        return cls.model_validate(
            {
                'href': lambda ctx: ctx.url_for(landing),
                'rel': rel,
                'type': type,
                **kwargs,
            },
        )

    @classmethod
    def to_route(
        cls,
        name: str,
        *,
        rel: str,
        type: str | None = MediaType.JSON,
        path: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        """Link to a named route (resolved via ``ctx.url_for(name, **path)``).

        Args:
            name: The route name to resolve.
            rel: The link relation.
            type: The target media type.
            path: Path parameters for the route. Bound into the deferred
                resolver; not stored on the link itself.
            **kwargs: Extra link fields (e.g. ``title``).
        """
        path = path or {}
        return cls.model_validate(
            {
                'href': lambda ctx: ctx.url_for(name, **path),
                'rel': rel,
                'type': type,
                **kwargs,
            },
        )
