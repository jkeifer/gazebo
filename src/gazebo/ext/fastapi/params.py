"""Ready-made ``Depends`` adapters for the standard OGC query parameters.

Each adapter parses a standard OGC query value into a typed model, raising
``ParamError`` (-> 400 problem) on bad input. Drop one into a route signature as
``Annotated[BBox | None, BBoxParam] = None``. ``Negotiate`` is the content-negotiation
companion, resolving the requested representation from ``?f=``/``Accept``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Depends, Query, Request

from gazebo.negotiation import Representation, f_description, negotiate
from gazebo.params import (
    BBOX_DESCRIPTION,
    BBOX_EXAMPLES,
    CRS84,
    CRS_DESCRIPTION,
    DATETIME_DESCRIPTION,
    DATETIME_EXAMPLES,
    BBox,
    DatetimeInterval,
    validate_crs,
)


def _openapi_examples(values: Sequence[str]) -> Any:
    """Turn a list of raw example values into OpenAPI ``openapi_examples`` entries."""
    return {value: {'value': value} for value in values}


async def _bbox_dep(
    bbox: Annotated[
        str | None,
        Query(description=BBOX_DESCRIPTION, openapi_examples=_openapi_examples(BBOX_EXAMPLES)),
    ] = None,
) -> BBox | None:
    return BBox.parse(bbox) if bbox is not None else None


BBoxParam = Depends(_bbox_dep)
"""Parses the OGC ``bbox`` query value into a :class:`~gazebo.params.BBox`."""


async def _datetime_dep(
    datetime: Annotated[
        str | None,
        Query(
            description=DATETIME_DESCRIPTION,
            openapi_examples=_openapi_examples(DATETIME_EXAMPLES),
        ),
    ] = None,
) -> DatetimeInterval | None:
    return DatetimeInterval.parse(datetime) if datetime is not None else None


DatetimeParam = Depends(_datetime_dep)
"""Parses the OGC ``datetime`` query value into a :class:`~gazebo.params.DatetimeInterval`."""


def CrsParam(  # noqa: N802  (factory returning a Depends, named like one)
    allowed: Sequence[str] = (CRS84,),
    *,
    name: str = 'crs',
    default: str | None = None,
) -> Any:
    """Build a ``Depends`` validating a ``crs``/``bbox-crs`` URI against an allow-list.

    Pass ``name='bbox-crs'`` for the companion parameter. A value outside ``allowed``
    raises ``ParamError`` (-> 400). When the parameter is **absent**, it resolves to:

    - the explicit ``default`` (which must be in ``allowed``), if given; else
    - :data:`~gazebo.params.CRS84` — the OGC default output CRS — if it is allowed; else
    - nothing: with a non-default allow-list and no marked default there is no safe
      assumption, so the parameter is **required** and an absent value is a 400.
    """
    allowed_uris = tuple(allowed)
    if not allowed_uris:
        raise ValueError('CrsParam requires at least one allowed CRS')
    if default is not None and default not in allowed_uris:
        raise ValueError(f'CrsParam default {default!r} is not in allowed')
    resolved_default = default or (CRS84 if CRS84 in allowed_uris else None)

    # ``Query`` is passed as the runtime default (not embedded in the annotation):
    # under ``from __future__ import annotations`` an ``Annotated[..., Query(alias=name)]``
    # string can't be resolved by ``get_type_hints`` because ``name`` is a closure
    # variable, which silently drops the query binding.
    async def _crs_dep(
        value: str | None = Query(
            default=None,
            alias=name,
            description=CRS_DESCRIPTION,
            # The allow-list is a closed set; emit it as an OpenAPI enum.
            json_schema_extra={'enum': list(allowed_uris)},
        ),
    ) -> str:
        # validate_crs owns the full resolution: an absent value resolves to
        # resolved_default (or 400s when that is None), a present one is checked
        # against the allow-list.
        return validate_crs(value, allowed_uris, parameter=name, default=resolved_default)

    return Depends(_crs_dep)


def Negotiate(  # noqa: N802  (factory returning a Depends, named like one)
    available: Sequence[Representation],
    *,
    default: Representation | None = None,
    name: str = 'f',
) -> Any:
    """Build a ``Depends`` resolving the negotiated representation from ``?f=``/``Accept``.

    Drop the result into a route as ``rep: Annotated[Representation, Negotiate([JSON,
    HTML])]``: the endpoint then branches on ``rep`` (e.g. render HTML vs return the
    model) and can attach :func:`~gazebo.negotiation.alternate_links`. An unknown ``?f=``
    becomes a ``400`` and an unsatisfiable ``Accept`` a ``406``, both as problem+json.
    """
    reps = tuple(available)

    # Query is the runtime default (not embedded in the annotation) for the same reason
    # as CrsParam: under `from __future__ import annotations` a closure-variable alias
    # can't be resolved by get_type_hints, which would drop the binding.
    async def _negotiate_dep(
        request: Request,
        value: str | None = Query(
            default=None,
            alias=name,
            # The available reps are known here, so name their actual keys.
            description=f_description(rep.key for rep in reps),
            # The representation keys are a closed set; emit them as an OpenAPI enum.
            json_schema_extra={'enum': [rep.key for rep in reps]},
        ),
    ) -> Representation:
        return negotiate(
            reps,
            f=value,
            accept=request.headers.get('accept'),
            default=default,
            f_param=name,
        )

    # Publish the reps on the dependency callable so route registration can discover them
    # (GazeboRouter / upgrade()'s add_api_route) and fold an OpenAPI response content map
    # documenting every negotiated media type — one source of truth with `negotiate`.
    _negotiate_dep.__gazebo_representations__ = reps  # type: ignore[attr-defined]

    return Depends(_negotiate_dep)


__all__ = ['BBoxParam', 'CrsParam', 'DatetimeParam', 'Negotiate']
