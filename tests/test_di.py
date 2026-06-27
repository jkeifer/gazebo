from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

import pytest

from gazebo.di import (
    CircularDependencyError,
    Container,
    Overrides,
    Providers,
    Qualify,
    ScopeMismatchError,
    UnresolvedDependencyError,
)

TORN: list[str] = []


class Root:
    def __init__(self, who: str = 'anon') -> None:
        self.who = who


@dataclass
class Settings:
    dsn: str = 'real'

    @classmethod
    def __provide__(cls) -> Settings:
        return cls()


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @classmethod
    @asynccontextmanager
    async def __provide__(cls, settings: Settings) -> AsyncIterator[Database]:
        try:
            yield cls(settings.dsn)
        finally:
            TORN.append('db')


class Session:
    def __init__(self, db: Database) -> None:
        self.db = db

    @classmethod
    @asynccontextmanager
    async def __provide__(cls, database: Database) -> AsyncIterator[Session]:
        try:
            yield cls(database)
        finally:
            TORN.append('session')


class User:
    def __init__(self, who: str) -> None:
        self.who = who

    @classmethod
    async def __provide__(cls, root: Root) -> User:
        return cls(root.who)


class FakeDatabase(Database):
    @classmethod
    @asynccontextmanager
    async def __provide__(cls, settings: Settings) -> AsyncIterator[FakeDatabase]:
        yield cls('fake')


async def test_app_singleton_and_request_distinct():
    TORN.clear()
    providers = Providers().app(Settings).app(Database).request(Session)
    container = Container(providers, roots={'request': Root})

    async with container.open_app_scope() as app_state:
        db1 = await app_state.get(Database)
        async with container.open_request_scope(app_state, root=Root()) as r1:
            assert await r1.get(Database) is db1
            s1a = await r1.get(Session)
            assert await r1.get(Session) is s1a
        r2_cm = container.open_request_scope(app_state, root=Root())
        async with r2_cm as r2:
            assert await r2.get(Session) is not s1a

    assert TORN == ['session', 'session', 'db']


async def test_root_injection():
    providers = Providers().request(User)
    container = Container(providers, roots={'request': Root})
    async with container.open_app_scope() as app_state:
        request_scope = container.open_request_scope(app_state, root=Root('alice'))
        async with request_scope as r:
            assert (await r.get(User)).who == 'alice'


async def test_override_instance_and_class():
    TORN.clear()
    providers = Providers().app(Settings).app(Database)
    overrides = Overrides().set(Settings, Settings(dsn='test')).set(Database, FakeDatabase)
    container = Container(providers, overrides=overrides, roots={'request': Root})
    async with container.open_app_scope() as app_state:
        assert (await app_state.get(Database)).dsn == 'fake'


async def test_override_with_plain_instance():
    overrides = Overrides().set(Settings, Settings(dsn='X'))
    container = Container(Providers().app(Settings), overrides=overrides)
    async with container.open_app_scope() as app_state:
        assert (await app_state.get(Settings)).dsn == 'X'


def test_scope_mismatch_detected():
    providers = Providers().request(Session).app(Settings).app(Database)

    # rebind Database as app but depending on request Session via a bad recipe
    def bad(session: Session) -> Database:
        return Database('x')

    providers.app(Database, bad)
    with pytest.raises(ScopeMismatchError):
        Container(providers, roots={'request': Root})


class Unbound:
    pass


class Needy:
    @classmethod
    def __provide__(cls, missing: Unbound) -> Needy:
        return cls()


def test_missing_dependency_detected():
    providers = Providers().app(Needy)  # Unbound not bound
    with pytest.raises(UnresolvedDependencyError):
        Container(providers)


class CycleA:
    @classmethod
    def __provide__(cls, b: CycleB) -> CycleA:
        return cls()


class CycleB:
    @classmethod
    def __provide__(cls, a: CycleA) -> CycleB:
        return cls()


def test_cycle_detected():
    providers = Providers().app(CycleA).app(CycleB)
    with pytest.raises(CircularDependencyError):
        Container(providers)


class Db:
    def __init__(self, tag: str) -> None:
        self.tag = tag


def _primary() -> Db:
    return Db('primary')


def _replica() -> Db:
    return Db('replica')


class Service:
    def __init__(self, p: Db, r: Db) -> None:
        self.p, self.r = p, r

    @classmethod
    def __provide__(cls, primary: Db, replica: Annotated[Db, Qualify('replica')]) -> Service:
        return cls(primary, replica)


async def test_qualified_types():
    providers = Providers()
    providers.app(Db, _primary)
    providers.app(Db, _replica, qualifier='replica')
    providers.app(Service)
    container = Container(providers)
    async with container.open_app_scope() as app_state:
        svc = await app_state.get(Service)
        assert svc.p.tag == 'primary'
        assert svc.r.tag == 'replica'


def test_graph_shape():
    container = Container(Providers().app(Settings).app(Database))
    graph = container.graph()
    assert any('Settings' in key for key in graph)
    assert any('Settings' in deps for deps in graph.values())
