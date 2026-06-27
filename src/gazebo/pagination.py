"""Pagination link helpers.

Builds ``next``/``prev`` links as deferred resolvers: at serialization they take
the current request URL from the context and rewrite only the pagination query
params, preserving everything else. The caller owns token semantics; gazebo only
builds the links.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from gazebo.context import RequestContext
from gazebo.link import Link
from gazebo.rels import MediaType, Rel


def with_query(ctx: RequestContext, **overrides: object) -> str:
    """Return the current URL with ``overrides`` merged into the query string.

    A ``None`` value removes that parameter. Other values are stringified.
    """
    parts = urlsplit(ctx.url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in overrides.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = str(value)
    return urlunsplit(parts._replace(query=urlencode(query)))


def paginate(
    *,
    next_token: str | None = None,
    prev_token: str | None = None,
    limit: int | None = None,
    token_param: str = 'token',  # noqa: S107
    limit_param: str = 'limit',
) -> list[Link]:
    """Return ``next``/``prev`` links for the tokens provided (deferred)."""
    links: list[Link] = []
    if next_token is not None:
        links.append(
            Link(
                href=lambda ctx: with_query(
                    ctx,
                    **{token_param: next_token, limit_param: limit},
                ),
                rel=Rel.NEXT,
                type=MediaType.JSON,
            ),
        )
    if prev_token is not None:
        links.append(
            Link(
                href=lambda ctx: with_query(
                    ctx,
                    **{token_param: prev_token, limit_param: limit},
                ),
                rel=Rel.PREV,
                type=MediaType.JSON,
            ),
        )
    return links
