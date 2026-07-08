"""Typed parsers for the standard OGC query parameters.

Core layer: pydantic + stdlib only, no web framework. These models turn the raw
string values every OGC API accepts — ``bbox``, ``datetime``, ``crs`` — into typed,
validated objects. A malformed value raises :class:`ParamError`, which the FastAPI
glue renders as a ``400 application/problem+json`` response (see
:mod:`gazebo.ext.fastapi`). The framework-agnostic ``parse`` classmethods can also
be called directly from any code that already has the raw string in hand.
"""

from __future__ import annotations

import math

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, BeforeValidator, Field, model_validator

if TYPE_CHECKING:
    from pydantic import GetJsonSchemaHandler
    from pydantic.json_schema import JsonSchemaValue
    from pydantic_core import CoreSchema

CRS84 = 'http://www.opengis.net/def/crs/OGC/1.3/CRS84'
"""The OGC default CRS: WGS 84 longitude/latitude (lon, lat axis order).

Same datum as ``EPSG:4326`` but with GeoJSON's lon/lat ordering, which is why OGC
API Features uses it as the default and most common allow-list entry.
"""

# Descriptions and examples for the standard OGC query parameters. Defined once here so
# both the FastAPI ``Depends`` adapters (openapi metadata) and the composable field types
# (pydantic ``Field`` metadata) document them identically — a single source of truth.

BBOX_DESCRIPTION = (
    'A bounding box, as comma-separated numbers `minx,miny,maxx,maxy` (WGS 84 '
    'longitude/latitude), or `minx,miny,minz,maxx,maxy,maxz` for a 3D box. The x axis '
    'may wrap the antimeridian (`minx` may exceed `maxx`); the y (and z) axes must be '
    'ordered `min <= max`. Malformed values return a `400` problem.'
)
"""Human-readable description of the OGC ``bbox`` query parameter."""

BBOX_EXAMPLES = [
    '-180,-90,180,90',
    '7.0,50.0,8.0,51.0',
    '7,50,0,8,51,1000',
]
"""Example ``bbox`` values: global, a regional box, and a 3D box."""

DATETIME_DESCRIPTION = (
    'An RFC 3339 instant, or a `start/end` interval where either side may be open using '
    '`..` (or empty). An instant matches a single timestamp; an interval matches a range. '
    'Malformed values return a `400` problem.'
)
"""Human-readable description of the OGC ``datetime`` query parameter."""

DATETIME_EXAMPLES = [
    '2020-01-01T00:00:00Z',
    '2020-01-01T00:00:00Z/2020-12-31T23:59:59Z',
    '../2020-12-31T23:59:59Z',
    '2020-01-01T00:00:00Z/..',
]
"""Example ``datetime`` values: instant, closed interval, open-start, open-end."""

CRS_DESCRIPTION = (
    'The coordinate reference system, as a CRS URI from the supported set. Defaults to '
    'CRS84 (WGS 84 longitude/latitude) when it is allowed. A value outside the supported '
    'set returns a `400` problem.'
)
"""Human-readable description of the OGC ``crs``/``bbox-crs`` query parameter."""


class ParamError(Exception):
    """A query parameter failed to parse or validate.

    Carries the offending ``parameter`` name and a human ``detail``; the FastAPI
    glue maps it to a ``400`` problem, with the parameter name as an extension
    member. OGC treats a malformed query parameter as a client error (400), so
    this is deliberately distinct from request-*body* validation (422).
    """

    def __init__(self, parameter: str, detail: str) -> None:
        self.parameter = parameter
        self.detail = detail
        super().__init__(f'{parameter}: {detail}')


class BBox(BaseModel):
    """A bounding box: ``minx,miny,maxx,maxy`` (2D) or with ``minz``/``maxz`` (3D).

    Parsed from the OGC ``bbox`` query value. The x axis is allowed to wrap (``minx``
    may exceed ``maxx`` to denote a box crossing the antimeridian); the y and z axes
    must be ordered ``min <= max``.
    """

    minx: float
    miny: float
    maxx: float
    maxy: float
    minz: float | None = None
    maxz: float | None = None

    @model_validator(mode='after')
    def _check_order(self) -> BBox:
        if self.miny > self.maxy:
            raise ParamError('bbox', 'miny must not exceed maxy')
        if self.minz is not None and self.maxz is not None and self.minz > self.maxz:
            raise ParamError('bbox', 'minz must not exceed maxz')
        return self

    def contains(self, lon: float, lat: float) -> bool:
        """Whether the point ``(lon, lat)`` falls within this (2D) box.

        Handles the antimeridian case the box itself allows: when ``minx > maxx`` the
        x extent wraps across +/-180, so a longitude matches if it is east of ``minx``
        *or* west of ``maxx``. The y axis is a plain inclusive range. The z extent (if
        any) is not considered — this is a horizontal point-in-box test.
        """
        if not (self.miny <= lat <= self.maxy):
            return False
        if self.minx <= self.maxx:
            return self.minx <= lon <= self.maxx
        return lon >= self.minx or lon <= self.maxx

    @classmethod
    def parse(cls, raw: str) -> BBox:
        """Parse a ``bbox`` query value (4 or 6 comma-separated numbers)."""
        parts = [p.strip() for p in raw.split(',')]
        if len(parts) not in (4, 6):
            raise ParamError(
                'bbox',
                f'expected 4 or 6 comma-separated numbers, got {len(parts)}',
            )
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            raise ParamError('bbox', 'all bbox values must be numbers') from None
        if not all(math.isfinite(n) for n in nums):
            # reject inf/nan: float() accepts them, and nan slips past ordering checks
            raise ParamError('bbox', 'bbox values must be finite numbers')
        if len(nums) == 4:
            minx, miny, maxx, maxy = nums
            return cls(minx=minx, miny=miny, maxx=maxx, maxy=maxy)
        minx, miny, minz, maxx, maxy, maxz = nums
        return cls(minx=minx, miny=miny, maxx=maxx, maxy=maxy, minz=minz, maxz=maxz)


def _as_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC (the OGC default temporal reference system).

    A bare date or offset-less time is technically not a full RFC 3339 date-time;
    rather than reject it (or, worse, let a later naive-vs-aware comparison raise a
    ``TypeError`` -> 500), we interpret it as UTC so intervals are always comparable.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _parse_instant(value: str, parameter: str) -> datetime | None:
    """Parse one side of a ``datetime`` value; ``''`` or ``'..'`` mean open."""
    value = value.strip()
    if value in ('', '..'):
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError:
        raise ParamError(parameter, f'invalid RFC 3339 datetime: {value!r}') from None


class DatetimeInterval(BaseModel):
    """An RFC 3339 instant or interval, as accepted by the OGC ``datetime`` param.

    ``start``/``end`` of ``None`` denote an open (unbounded) end. An instant
    (a single timestamp with no ``/``) is represented as ``start == end``.
    """

    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode='after')
    def _check_order(self) -> DatetimeInterval:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ParamError('datetime', 'interval start is after end')
        return self

    @property
    def is_instant(self) -> bool:
        return self.start is not None and self.start == self.end

    def contains(self, when: datetime) -> bool:
        """Whether ``when`` falls within the (possibly half-open) interval.

        A naive ``when`` (or naive bound) is treated as UTC, so this never raises a
        naive-vs-aware ``TypeError`` regardless of how the interval was built.
        """
        when = _as_utc(when)
        if self.start is not None and when < _as_utc(self.start):
            return False
        return not (self.end is not None and when > _as_utc(self.end))

    @classmethod
    def parse(cls, raw: str) -> DatetimeInterval:
        """Parse a ``datetime`` query value (an instant or a ``start/end`` interval)."""
        raw = raw.strip()
        if '/' in raw:
            start_s, _, end_s = raw.partition('/')
            start = _parse_instant(start_s, 'datetime')
            end = _parse_instant(end_s, 'datetime')
            if start is None and end is None:
                raise ParamError('datetime', 'interval cannot be open at both ends')
            return cls(start=start, end=end)
        instant = _parse_instant(raw, 'datetime')
        if instant is None:
            raise ParamError('datetime', 'datetime value cannot be empty')
        return cls(start=instant, end=instant)


def validate_crs(
    value: str | None,
    allowed: tuple[str, ...],
    *,
    parameter: str = 'crs',
    default: str | None = CRS84,
) -> str:
    """Resolve and validate a ``crs``/``bbox-crs`` URI against an allow-list.

    A present ``value`` must be in ``allowed`` (the OGC conformance requirement);
    otherwise raises :class:`ParamError` (-> 400). When ``value`` is unset it
    resolves to ``default`` — which must itself be in ``allowed``. Pass
    ``default=None`` to require the parameter when there is no safe default: an
    absent value then raises :class:`ParamError` rather than assuming one.

    Raises :class:`ValueError` if a non-``None`` ``default`` is not in ``allowed``
    (a server misconfiguration, not bad client input).
    """
    if value is None:
        if default is None:
            allowed_list = ', '.join(allowed)
            raise ParamError(
                parameter,
                f'{parameter} is required (no default CRS); one of: {allowed_list}',
            )
        if default not in allowed:
            raise ValueError(f'crs default {default!r} is not in allowed')
        return default
    if value not in allowed:
        allowed_list = ', '.join(allowed)
        raise ParamError(parameter, f'unsupported crs {value!r}; allowed: {allowed_list}')
    return value


# --- Composable field types ------------------------------------------------
#
# Annotated types a consumer can fold into their *own* pydantic query model (used as
# ``Annotated[MyQuery, Query()]``, which FastAPI explodes into individual query params).
# They are pydantic-only (BeforeValidator + Field metadata, no web-framework import), so
# they live in the core alongside the parsers they wrap. Because they run inside pydantic
# validation, a bad value must surface as a plain ``ValueError`` (which pydantic wraps into
# a ``ValidationError``): the ``ParamError`` the parsers raise is deliberately *not* a
# ``ValueError`` (see below), so these validators translate it. The FastAPI glue maps the
# resulting query-field ``RequestValidationError`` back to a `400` problem, preserving the
# OGC "malformed query param is a client error" semantics.


def _parse_bbox_field(value: str | None) -> BBox | None:
    if value is None:
        return None
    try:
        return BBox.parse(value)
    except ParamError as exc:
        # ParamError is intentionally not a ValueError, so raise a plain one here for
        # pydantic to collect; the field's ``loc`` becomes the offending param name.
        raise ValueError(exc.detail) from None


BBoxQuery = Annotated[
    BBox | None,
    # A client sends the ``bbox`` param as a string; the validator parses it into a
    # :class:`BBox`. Tell pydantic the *input* is a string so the field's JSON schema is a
    # string (a Swagger text box) rather than the parsed model's object schema. Description
    # and examples still come from the ``Field`` below.
    BeforeValidator(_parse_bbox_field, json_schema_input_type=str),
    Field(default=None, description=BBOX_DESCRIPTION, examples=BBOX_EXAMPLES),
]
"""A folded ``bbox`` query field: parses to a :class:`BBox` (or ``None``), fully documented.

Put it on a consumer's own pydantic query model (used as ``Annotated[MyQuery, Query()]``);
a malformed value becomes a `400` ``application/problem+json`` under a :class:`GazeboApp`.
"""


def _parse_datetime_field(value: str | None) -> DatetimeInterval | None:
    if value is None:
        return None
    try:
        return DatetimeInterval.parse(value)
    except ParamError as exc:
        raise ValueError(exc.detail) from None


DatetimeQuery = Annotated[
    DatetimeInterval | None,
    # As with ``BBoxQuery``: the client sends a string, the validator parses it into a
    # :class:`DatetimeInterval`. Declaring the string input keeps the OpenAPI schema a
    # string (a text box) instead of the parsed model's object schema.
    BeforeValidator(_parse_datetime_field, json_schema_input_type=str),
    Field(default=None, description=DATETIME_DESCRIPTION, examples=DATETIME_EXAMPLES),
]
"""A folded ``datetime`` query field: parses to a :class:`DatetimeInterval` (or ``None``)."""


# --- Composable closed-set field: CRS enum --------------------------------
#
# The closed set of allowed CRS URIs is a *consumer* decision, so it must be spelled by
# the consumer as a real ``StrEnum`` subclass (a class definition is the only construct a
# static type checker accepts as a usable field type — a gazebo helper *call* in
# annotation position never is). :class:`CrsEnum` is the base to subclass: members are
# CRS URI strings, so a folded field validates membership natively (a bad value → a
# ``ValidationError`` that the FastAPI glue renders as a `400` problem), serializes as the
# URI, and FastAPI renders it as an ``enum`` query param. The base injects
# :data:`CRS_DESCRIPTION` into the field's JSON schema so it self-documents in OpenAPI.


class CrsEnum(StrEnum):
    """Base ``StrEnum`` for a folded ``crs``/``bbox-crs`` query field's closed CRS set.

    Subclass it, spelling each allowed CRS as a member whose value is the CRS URI, then
    fold the subclass into a pydantic query model as a real field type (no ``type: ignore``
    needed — it is an ordinary class)::

        class BedCrs(CrsEnum):
            CRS84 = CRS84
            WEB_MERCATOR = 'http://www.opengis.net/def/crs/EPSG/0/3857'

        class BedQuery(BaseModel):
            crs: BedCrs = BedCrs.CRS84

    Because members are real strings (the URIs), the field value is usable downstream as a
    URI and serializes as one. Pydantic validates membership natively: an unknown value is
    a ``ValidationError`` that a :class:`~gazebo.ext.fastapi.GazeboApp` renders as a `400`
    ``application/problem+json`` citing the parameter. FastAPI renders the field as an
    ``enum`` query param, and the base carries :data:`CRS_DESCRIPTION` so it self-documents
    in the generated OpenAPI. Give the field a default (typically ``CRS84``) so an absent
    value resolves to it.
    """

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        # Force the shared OGC description onto the enum's schema so a folded field
        # self-documents in OpenAPI with the *parameter's* meaning. FastAPI reads the
        # parameter description from the (possibly $ref'd) enum schema, so it must live on
        # the schema itself, not only on a Field(...) the consumer would otherwise add. We
        # overwrite rather than setdefault: pydantic pre-fills ``description`` from the
        # subclass docstring (developer-facing), but the API parameter wants CRS_DESCRIPTION.
        schema = handler(core_schema)
        schema['description'] = CRS_DESCRIPTION
        return schema


__all__ = [
    'BBOX_DESCRIPTION',
    'BBOX_EXAMPLES',
    'CRS84',
    'CRS_DESCRIPTION',
    'DATETIME_DESCRIPTION',
    'DATETIME_EXAMPLES',
    'BBox',
    'BBoxQuery',
    'CrsEnum',
    'DatetimeInterval',
    'DatetimeQuery',
    'ParamError',
    'validate_crs',
]
