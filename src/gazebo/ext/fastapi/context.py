"""Adapt a FastAPI ``Request`` to gazebo's :class:`RequestContext` protocol.

The request-scope binding that lets deferred link hrefs resolve URLs from the active
request without the core ever importing FastAPI.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import Request

from gazebo.context import RequestContext


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


__all__ = ['RequestContextAdapter']
