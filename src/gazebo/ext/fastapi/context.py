"""Adapt a FastAPI ``Request`` to gazebo's :class:`RequestContext` protocol.

The request-scope binding that lets deferred link hrefs resolve URLs from the active
request without the core ever importing FastAPI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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

    def url_for_template(
        self,
        name: str,
        path: Mapping[str, object],
        template: Sequence[str],
        /,
    ) -> str:
        # Resolve through the real router (preserving root_path and proxy
        # scheme/host) using unreserved-ASCII sentinels for the unbound vars, then
        # rewrite each sentinel back to an RFC 6570 {var}.
        subs = {v: f'__gztpl_{v}__' for v in template}
        url = str(self._request.url_for(name, **path, **subs))
        for v, token in subs.items():
            url = url.replace(token, f'{{{v}}}')
        return url


def _provide_request_context(request: Request) -> RequestContext:
    return RequestContextAdapter(request)


__all__ = ['RequestContextAdapter']
