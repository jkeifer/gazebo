"""Injectable resources: settings, databases, sessions, and per-request identity.

Demonstrates: app-scoped recipes with teardown (``Database``), a ``__health__``
probe, qualified bindings (primary vs replica), an app-scoped repository that
depends on both, an external request-scoped type provided by a standalone function
(``Session`` + ``Inject``), and request-scoped identity derived from headers
(``User``, ``Tenant``) — including raising a problem from a recipe.
"""

from __future__ import annotations

import logging

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from typing import Annotated

from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict

from gazebo.di import Qualify
from gazebo.problems import ProblemException

log = logging.getLogger('garden')

UTC = timezone.utc

# A toy in-memory store shared by the "primary" and "replica" handles, keyed by
# tenant. Reset between tests via reset_store().
_STORE: dict[str, dict[str, dict]] = {}
_IDS = count(100)

# A second, geospatial store: garden beds as GeoJSON-feature rows (lon/lat + a
# planted date) used by the OGC Features-style /collections/beds endpoints.
_BEDS: list[dict] = []


def reset_store() -> None:
    _STORE.clear()
    _STORE['public'] = {
        '1': {'id': '1', 'name': 'Fern'},
        '2': {'id': '2', 'name': 'Ivy'},
        '3': {'id': '3', 'name': 'Moss'},
    }
    _STORE['acme'] = {'10': {'id': '10', 'name': 'Bonsai'}}

    _BEDS.clear()
    _BEDS.extend(
        [
            {
                'id': 'roses',
                'name': 'Rose Bed',
                'lon': -122.6,
                'lat': 45.5,
                'planted': datetime(2021, 4, 1, tzinfo=UTC),
            },
            {
                'id': 'herbs',
                'name': 'Herb Spiral',
                'lon': 2.35,
                'lat': 48.85,
                'planted': datetime(2022, 6, 15, tzinfo=UTC),
            },
            {
                'id': 'orchard',
                'name': 'Orchard',
                'lon': 139.7,
                'lat': 35.68,
                'planted': datetime(2020, 3, 10, tzinfo=UTC),
            },
        ],
    )


def all_beds() -> list[dict]:
    return list(_BEDS)


def get_bed_row(bed_id: str) -> dict | None:
    return next((b for b in _BEDS if b['id'] == bed_id), None)


reset_store()


class Settings(BaseSettings):
    """App settings, sourced from env (``GARDEN_*``) / defaults and surfaced as CLI
    options by ``garden serve``. The ``__provide__`` recipe makes the injected
    instance the one the CLI configures (the flags set the env this reads)."""

    model_config = SettingsConfigDict(env_prefix='GARDEN_')

    primary_dsn: str = 'memory://primary'
    replica_dsn: str = 'memory://replica'

    @classmethod
    def __provide__(cls) -> Settings:
        return cls()


class Database:
    """A fake DB handle over the shared store. App-scoped, with open/close logging."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    async def __health__(self) -> bool:
        return True

    def list(self, tenant: str, limit: int, offset: int) -> list[dict]:
        rows = sorted(_STORE.get(tenant, {}).values(), key=lambda r: r['id'])
        return rows[offset : offset + limit]

    def count(self, tenant: str) -> int:
        return len(_STORE.get(tenant, {}))

    def get(self, tenant: str, plant_id: str) -> dict | None:
        return _STORE.get(tenant, {}).get(plant_id)

    def insert(self, tenant: str, name: str) -> dict:
        row = {'id': str(next(_IDS)), 'name': name}
        _STORE.setdefault(tenant, {})[row['id']] = row
        return row


@asynccontextmanager
async def provide_primary(settings: Settings) -> AsyncIterator[Database]:
    log.info('opening primary database %s', settings.primary_dsn)
    db = Database(settings.primary_dsn)
    try:
        yield db
    finally:
        log.info('closing primary database %s', db.dsn)


@asynccontextmanager
async def provide_replica(settings: Settings) -> AsyncIterator[Database]:
    log.info('opening replica database %s', settings.replica_dsn)
    db = Database(settings.replica_dsn)
    try:
        yield db
    finally:
        log.info('closing replica database %s', db.dsn)


class Catalog:
    """An app-scoped repository wiring writes to primary and reads to the replica.

    Shows qualified injection: the replica is selected with ``Qualify('replica')``.
    """

    def __init__(self, write: Database, read: Database) -> None:
        self.write = write
        self.read = read

    @classmethod
    def __provide__(
        cls,
        primary: Database,
        replica: Annotated[Database, Qualify('replica')],
    ) -> Catalog:
        return cls(write=primary, read=replica)


class Session:
    """A per-request unit of work (external type: no ``__provide__``)."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.writes = 0

    def create_plant(self, tenant: str, name: str) -> dict:
        self.writes += 1
        return self.catalog.write.insert(tenant, name)


@asynccontextmanager
async def provide_session(catalog: Catalog) -> AsyncIterator[Session]:
    session = Session(catalog)
    try:
        yield session
    finally:
        log.info('session closed (%d writes)', session.writes)


@dataclass
class User:
    """Authenticated principal, parsed from the Authorization header."""

    name: str

    @classmethod
    async def __provide__(cls, request: Request) -> User:
        auth = request.headers.get('authorization', '')
        token = auth.removeprefix('Bearer ').strip()
        if not token:
            raise ProblemException(401, detail='missing or empty Authorization header')
        return cls(name=token)


@dataclass
class Tenant:
    """Tenant derived from a header — request-derived, no FastAPI param extractors."""

    id: str

    @classmethod
    async def __provide__(cls, request: Request) -> Tenant:
        return cls(id=request.headers.get('x-tenant', 'public'))
