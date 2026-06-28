"""OGC API Common models: landing page, conformance.

Pure pydantic models plus a small conformance-class registry. The framework glue
generates the actual landing-page links from the router tree.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from gazebo.collection import LinkedCollection
from gazebo.jsonschema import OmitNullModel
from gazebo.link import Link
from gazebo.params import CRS84

DEFAULT_TRS = 'http://www.opengis.net/def/uom/ISO-8601/0/Gregorian'
"""The OGC default temporal reference system (the Gregorian calendar / UTC)."""


def _world_bbox() -> list[list[float]]:
    return [[-180.0, -90.0, 180.0, 90.0]]


def _open_interval() -> list[list[datetime | None]]:
    return [[None, None]]


class LandingPage(BaseModel):
    """OGC API Common landing page (``GET /``)."""

    model_config = ConfigDict(extra='allow')

    title: str = ''
    description: str = ''
    links: list[Link] = Field(default_factory=list)


class ConformanceDeclaration(BaseModel):
    """OGC API Common conformance declaration (``GET /conformance``)."""

    conforms_to: list[str] = Field(
        default_factory=list,
        alias='conformsTo',
        serialization_alias='conformsTo',
    )


class SpatialExtent(BaseModel):
    """The spatial extent of a collection: one or more bounding boxes in ``crs``.

    Per OGC, the first bbox is the overall extent; further entries may partition it.
    Each bbox is ``[minx, miny, maxx, maxy]`` (or the 6-number 3D form).
    """

    bbox: list[list[float]] = Field(default_factory=_world_bbox)
    crs: str = CRS84


class TemporalExtent(BaseModel):
    """The temporal extent: one or more intervals in ``trs``.

    Each interval is a ``[start, end]`` pair; ``null`` on either side means open.
    """

    interval: list[list[datetime | None]] = Field(default_factory=_open_interval)
    trs: str = DEFAULT_TRS


class Extent(OmitNullModel):
    """A collection's spatial and/or temporal extent.

    An unset ``spatial``/``temporal`` is omitted on the wire rather than emitted as
    ``null`` (OGC treats them as optional members).
    """

    spatial: SpatialExtent | None = None
    temporal: TemporalExtent | None = None


class Collection(OmitNullModel):
    """OGC API Common collection metadata (``GET /collections/{id}``).

    An unset ``extent`` is omitted on the wire rather than emitted as ``null``.
    """

    model_config = ConfigDict(extra='allow')

    id: str
    title: str = ''
    description: str = ''
    extent: Extent | None = None
    item_type: str = Field(default='feature', serialization_alias='itemType')
    crs: list[str] = Field(default_factory=lambda: [CRS84])
    links: list[Link] = Field(default_factory=list)


class Collections(
    LinkedCollection[Collection],
    items_alias='collections',
    number_returned=False,
):
    """The ``/collections`` envelope: a list of :class:`Collection` under ``collections``.

    Omits ``numberReturned`` — the OGC ``/collections`` object does not define it.
    """


class Conformance:
    """A small registry of conformance-class URIs.

    >>> conformance = Conformance(Conformance.CORE)
    >>> conformance.add(Conformance.JSON)
    >>> conformance.declaration()
    """

    # A few common OGC API Common conformance classes.
    CORE = 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core'
    LANDING_PAGE = 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page'
    JSON = 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json'
    OAS30 = 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30'
    HTML = 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/html'

    def __init__(self, *uris: str) -> None:
        self._uris: list[str] = []
        self.add(*uris)

    def add(self, *uris: str) -> Conformance:
        for uri in uris:
            if uri not in self._uris:
                self._uris.append(uri)
        return self

    @property
    def uris(self) -> list[str]:
        return list(self._uris)

    def declaration(self) -> ConformanceDeclaration:
        return ConformanceDeclaration(conformsTo=self.uris)
