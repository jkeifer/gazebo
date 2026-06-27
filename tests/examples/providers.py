"""Runnable examples backing ``docs/di/providers.md``."""

from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


# --8<-- [start:recipes]
@dataclass
class Settings:
    dsn: str = 'postgres://localhost/app'

    @classmethod
    def __provide__(cls) -> Settings:  # colocated recipe: built on demand
        return cls()


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @classmethod
    @asynccontextmanager
    async def __provide__(cls, settings: Settings) -> AsyncIterator[Database]:
        db = cls(settings.dsn)
        try:
            yield db  # built once (app scope)...
        finally:
            pass  # ...torn down at shutdown: await db.close()


# --8<-- [end:recipes]


@dataclass
class User:
    name: str = 'anon'

    @classmethod
    def __provide__(cls) -> User:
        return cls()


# --8<-- [start:registry]
from gazebo.di import Providers

providers = Providers().app(Settings).app(Database).request(User)
# --8<-- [end:registry]


# --8<-- [start:external]
class Session:  # third-party type: no __provide__ to add
    def __init__(self, db: Database) -> None:
        self.db = db


@asynccontextmanager
async def provide_session(database: Database) -> AsyncIterator[Session]:
    session = Session(database)
    try:
        yield session
    finally:
        pass  # await session.close()


providers.request(Session, provide_session)  # bind the external type to a recipe
# --8<-- [end:external]


from gazebo.di import Container


async def _check() -> None:
    container = Container(providers)
    async with container.open_app_scope() as app_state:
        database = await app_state.get(Database)
        assert database.dsn == 'postgres://localhost/app'
        async with container.open_request_scope(app_state, root=None) as request_scope:
            session = await request_scope.get(Session)
            assert session.db is database  # request dep wired to the app-scoped db


asyncio.run(_check())
