"""OGC API Common models: landing page, conformance.

Pure pydantic models plus a small conformance-class registry. The framework glue
generates the actual landing-page links from the router tree.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gazebo.link import Link


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
