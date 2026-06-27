"""Runnable examples backing ``docs/di/qualifiers-overrides.md``."""

from __future__ import annotations

import asyncio


# --8<-- [start:qualify]
from typing import Annotated

from gazebo.di import Providers, Qualify


class Database:
    def __init__(self, role: str) -> None:
        self.role = role


providers = Providers()
providers.app(Database, lambda: Database('primary'))  # the default
providers.app(Database, lambda: Database('replica'), qualifier='replica')  # disambiguated


class Catalog:
    db: Database

    @classmethod
    def __provide__(cls, db: Annotated[Database, Qualify('replica')]) -> Catalog:
        catalog = cls()
        catalog.db = db  # resolves the 'replica' binding
        return catalog


# --8<-- [end:qualify]


providers.app(Catalog)

from gazebo.di import Container


async def _check_qualify() -> None:
    async with Container(providers).open_app_scope() as state:
        assert (await state.get(Catalog)).db.role == 'replica'
        assert (await state.get(Database)).role == 'primary'  # unqualified default


asyncio.run(_check_qualify())


# --8<-- [start:overrides]
from gazebo.di import Container, Overrides

# In a test: replace a binding by parameter, never by mutating a global.
overrides = Overrides().set(Database, Database('in-memory'), qualifier='replica')
container = Container(providers, overrides=overrides)
# --8<-- [end:overrides]


async def _check_override() -> None:
    async with container.open_app_scope() as state:
        assert (await state.get(Catalog)).db.role == 'in-memory'


asyncio.run(_check_override())
