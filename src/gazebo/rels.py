"""Typed constants for link relations and media types.

Kills stringly-typed ``rel``/``type`` bugs. ``StrEnum`` members are ``str``
subclasses, so they drop into ``Link(rel=Rel.SELF, type=MediaType.JSON)`` and
serialize as their plain string value.
"""

from __future__ import annotations

from enum import StrEnum


class Rel(StrEnum):
    """Common IANA / OGC link relation types."""

    SELF = 'self'
    ROOT = 'root'
    UP = 'up'
    PARENT = 'parent'
    CHILD = 'child'
    NEXT = 'next'
    PREV = 'prev'
    FIRST = 'first'
    LAST = 'last'
    COLLECTION = 'collection'
    ITEMS = 'items'
    ITEM = 'item'
    DATA = 'data'
    CONFORMANCE = 'conformance'
    SERVICE_DESC = 'service-desc'
    SERVICE_DOC = 'service-doc'
    DESCRIBEDBY = 'describedby'
    ALTERNATE = 'alternate'
    STATUS = 'status'


class MediaType(StrEnum):
    """Common media types for OGC-style APIs."""

    JSON = 'application/json'
    GEOJSON = 'application/geo+json'
    PROBLEM = 'application/problem+json'
    HTML = 'text/html'
    CSV = 'text/csv'
    XML = 'application/xml'
    TEXT = 'text/plain'
    OPENAPI = 'application/vnd.oai.openapi+json;version=3.0'
    OPENAPI_YAML = 'application/vnd.oai.openapi;version=3.0'
