"""Runnable examples backing ``docs/di/scopes.md``."""

from __future__ import annotations

import asyncio

from dataclasses import dataclass


class Request:
    """Stand-in for the framework request object (the request-scope root)."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


# --8<-- [start:request_dep]
@dataclass
class User:
    name: str

    @classmethod
    def __provide__(cls, request: Request) -> User:
        # A parameter typed as the scope root receives it directly.
        return cls(request.headers.get('authorization', 'anon'))


# --8<-- [end:request_dep]


from gazebo.di import Container, Providers


async def _check() -> None:
    container = Container(Providers().request(User), roots={'request': Request})
    async with container.open_app_scope() as app_state:
        request = Request({'authorization': 'alice'})
        async with container.open_request_scope(app_state, root=request) as scope:
            user = await scope.get(User)
            assert user.name == 'alice'


asyncio.run(_check())
