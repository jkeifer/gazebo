from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

import pytest

from pydantic import BaseModel, Field

from gazebo.filtering import (
    CONF_CQL2_TEXT,
    Direction,
    Filter,
    FilterError,
    FilterLang,
    Queryables,
    Sortables,
    SortBy,
    filter_conformance_classes,
    queryables_from_model,
    sortables_from_model,
    validate_properties,
)
from gazebo.filtering.cql2 import Cql2Engine, referenced_properties
from gazebo.params import ParamError

ENGINE = Cql2Engine()


def compile_text(text: str) -> Filter:
    return Filter(ENGINE.compile(text, FilterLang.CQL2_TEXT), FilterLang.CQL2_TEXT)


# --------------------------------------------------------------------------- models


class Coord(BaseModel):
    lat: float
    lon: float


class Site(BaseModel):
    zone: str
    coord: Coord
    code: str = Field(alias='site_code')


class BedProps(BaseModel):
    name: str = Field(description='Human label')
    sun: Literal['full', 'part', 'shade']
    planted: date
    last_watered: datetime | None = None
    depth_cm: Annotated[int, Field(ge=0, le=500)] = 10
    nickname: str | None = Field(default=None, alias='alt_name')
    tags: list[str] = Field(default_factory=list)
    site: Site | None = None


# --------------------------------------------------------------------- engine / cql2


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ("name = 'rose'", {'name'}),
        ("sun IN ('full', 'part')", {'sun'}),
        ('depth > 10 AND (width <= 2 OR NOT shaded = true)', {'depth', 'width', 'shaded'}),
        ('area > size / 2', {'area', 'size'}),
        ('S_INTERSECTS(footprint, POINT(0 0))', {'footprint'}),
        ("T_DURING(planted, INTERVAL('2020-01-01', '2020-12-31'))", {'planted'}),
        ("A_CONTAINS(tags, ('native', 'perennial'))", {'tags'}),
        ('site.coord.lat > 3', {'site.coord.lat'}),
    ],
)
def test_referenced_properties_across_operators(text: str, expected: set[str]) -> None:
    assert compile_text(text).properties() == expected


def test_referenced_properties_walks_raw_json() -> None:
    node = {'op': '>', 'args': [{'property': 'a.b'}, {'op': '/', 'args': [{'property': 'c'}, 2]}]}
    assert referenced_properties(node) == {'a.b', 'c'}


def test_compile_validates_lenient_parse() -> None:
    # cql2-rs parses this leniently to a bare property reference; validate() must reject it.
    with pytest.raises(FilterError):
        ENGINE.compile('depth =', FilterLang.CQL2_TEXT)


def test_compile_rejects_bogus_syntax() -> None:
    with pytest.raises(FilterError):
        ENGINE.compile('?? nope ??', FilterLang.CQL2_TEXT)


def test_compile_cql2_json() -> None:
    flt = Filter(
        ENGINE.compile('{"op": ">", "args": [{"property": "depth"}, 5]}', FilterLang.CQL2_JSON),
        FilterLang.CQL2_JSON,
    )
    assert flt.properties() == {'depth'}
    assert flt.matches({'depth': 9}) is True


def test_compile_cql2_json_dict_input() -> None:
    compiled = ENGINE.compile(
        {'op': '=', 'args': [{'property': 'sun'}, 'full']}, FilterLang.CQL2_JSON,
    )
    assert compiled.properties() == {'sun'}
    assert compiled.matches({'sun': 'full'}) is True


def test_compile_rejects_bad_json() -> None:
    with pytest.raises(FilterError):
        ENGINE.compile('{"op": "nope"}', FilterLang.CQL2_JSON)


def test_matches_present_and_dotted() -> None:
    flt = compile_text('site.coord.lat > 3')
    assert flt.matches({'site': {'coord': {'lat': 5.0}}}) is True
    assert flt.matches({'site': {'coord': {'lat': 1.0}}}) is False


def test_matches_missing_property_is_false_not_error() -> None:
    # absent / null referenced property -> "unknown" -> excluded (SQL WHERE semantics)
    assert compile_text('depth > 3').matches({'name': 'x'}) is False
    assert compile_text('site.coord.lat > 3').matches({'name': 'x'}) is False
    assert compile_text('depth > 3').matches({'depth': None}) is False


def test_matches_is_null_works() -> None:
    assert compile_text('depth IS NULL').matches({'name': 'x'}) is True
    assert compile_text('depth IS NOT NULL').matches({'depth': 5}) is True


def test_matches_type_mismatch_is_false_not_error() -> None:
    # a parseable-but-type-mismatched comparison stays "unknown" -> no match, never a 500
    assert compile_text("depth > 'abc'").matches({'depth': 5}) is False


# ----------------------------------------------------------------------- queryables


def test_queryables_scalar_mapping() -> None:
    q = queryables_from_model(BedProps, id='beds')
    props = q.properties
    assert props['name'] == {'type': 'string', 'title': 'Name', 'description': 'Human label'}
    assert props['sun']['enum'] == ['full', 'part', 'shade']
    assert props['planted'] == {'type': 'string', 'format': 'date', 'title': 'Planted'}
    assert props['depth_cm']['minimum'] == 0
    assert props['depth_cm']['maximum'] == 500


def test_queryables_unwraps_optional() -> None:
    props = queryables_from_model(BedProps).properties
    # Optional[datetime] -> the date-time branch, not an anyOf wrapper
    assert props['last_watered']['format'] == 'date-time'
    assert 'anyOf' not in props['last_watered']


def test_queryables_keys_on_wire_alias() -> None:
    props = queryables_from_model(BedProps).properties
    assert 'alt_name' in props  # the field's alias, what a filter references
    assert 'nickname' not in props


def test_queryables_flattens_nested_with_aliases() -> None:
    names = queryables_from_model(BedProps).names
    assert {'site.zone', 'site.coord.lat', 'site.coord.lon', 'site.site_code'} <= names
    assert 'site' not in names  # the whole object is not itself queryable


def test_queryables_array_surfaces_item_type() -> None:
    tags = queryables_from_model(BedProps).properties['tags']
    assert tags['type'] == 'array'
    assert tags['items'] == {'type': 'string'}


def test_queryables_max_depth_guard() -> None:
    names = queryables_from_model(BedProps, max_depth=2).names
    assert 'site.zone' in names  # depth 2 reached
    assert 'site.coord.lat' not in names  # depth 3 cut off


def test_queryables_geometry_union_special_case() -> None:
    geojson_pydantic = pytest.importorskip('geojson_pydantic')

    class FeatProps(BaseModel):
        name: str
        footprint: geojson_pydantic.geometries.Geometry  # type: ignore[name-defined]

    props = queryables_from_model(FeatProps).properties
    assert props['footprint'] == {'$ref': 'https://geojson.org/schema/Geometry.json'}
    # geometry is filterable but never sortable
    assert 'footprint' not in sortables_from_model(FeatProps).names


def test_queryables_concrete_geometry_not_flattened() -> None:
    # a concrete geometry type (not the union) must also be advertised as geometry, not
    # flattened into loc.type / loc.coordinates / loc.bbox nonsense
    geojson_pydantic = pytest.importorskip('geojson_pydantic')

    class FeatProps(BaseModel):
        name: str
        loc: geojson_pydantic.geometries.Point  # type: ignore[name-defined]

    names = queryables_from_model(FeatProps).names
    assert names == {'name', 'loc'}
    assert queryables_from_model(FeatProps).properties['loc'] == {
        '$ref': 'https://geojson.org/schema/Geometry.json',
    }


def test_queryables_model_named_like_geometry_still_flattens() -> None:
    # a plain nested model that merely lacks geometry's shape must NOT be mistaken for one
    class Point(BaseModel):  # same name as a geometry, but no `coordinates`
        x: float
        y: float

    class FeatProps(BaseModel):
        name: str
        loc: Point

    assert queryables_from_model(FeatProps).names == {'name', 'loc.x', 'loc.y'}


def test_queryables_serializes_with_json_schema_aliases() -> None:
    dumped = queryables_from_model(BedProps, id='beds').model_dump(mode='json', by_alias=True)
    assert dumped['$schema'].startswith('https://json-schema.org/')
    assert dumped['$id'] == 'beds'
    assert dumped['type'] == 'object'
    assert dumped['additionalProperties'] is False


def test_sortables_exclude_arrays_keep_nested_scalars() -> None:
    names = sortables_from_model(BedProps).names
    assert 'tags' not in names  # arrays have no total order
    assert {'name', 'planted', 'site.coord.lat'} <= names


# ---------------------------------------------------------------- validate_properties


def test_validate_properties_passes_known() -> None:
    q = queryables_from_model(BedProps)
    validate_properties(compile_text('site.coord.lat > 3'), q)  # no raise


def test_validate_properties_rejects_unknown() -> None:
    q = queryables_from_model(BedProps)
    with pytest.raises(FilterError, match='color'):
        validate_properties(compile_text("color = 'red'"), q)


def test_validate_properties_rejects_unknown_nested() -> None:
    q = queryables_from_model(BedProps)
    with pytest.raises(FilterError, match='elevation'):
        validate_properties(compile_text('site.coord.elevation > 1'), q)


# ----------------------------------------------------------------------------- sortby


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('name', [('name', Direction.ASC)]),
        ('+name', [('name', Direction.ASC)]),
        ('-planted', [('planted', Direction.DESC)]),
        ('-planted,name', [('planted', Direction.DESC), ('name', Direction.ASC)]),
        (' name , -planted ', [('name', Direction.ASC), ('planted', Direction.DESC)]),
    ],
)
def test_sortby_parse(raw: str, expected: list[tuple[str, Direction]]) -> None:
    sb = SortBy.parse(raw)
    assert [(s.field, s.direction) for s in sb.sorts] == expected


@pytest.mark.parametrize('raw', ['', 'name,,planted', '-', 'name,name'])
def test_sortby_parse_errors(raw: str) -> None:
    with pytest.raises(ParamError):
        SortBy.parse(raw)


def test_sortby_parse_validates_against_sortables() -> None:
    with pytest.raises(ParamError, match='not sortable'):
        SortBy.parse('color', sortables={'name', 'planted'})


def test_sortby_apply_multikey_mixed_direction() -> None:
    rows = [
        {'name': 'b', 'planted': '2021'},
        {'name': 'a', 'planted': '2021'},
        {'name': 'a', 'planted': '2020'},
    ]
    ordered = SortBy.parse('-planted,name').apply(rows)
    assert [r['name'] for r in ordered] == ['a', 'b', 'a']
    assert [r['planted'] for r in ordered] == ['2021', '2021', '2020']


def test_sortby_apply_dotted_and_nulls_last() -> None:
    rows: list[dict[str, Any]] = [
        {'name': 'b', 'site': {'coord': {'lat': 5.0}}},
        {'name': 'c'},  # null lat
        {'name': 'a', 'site': {'coord': {'lat': 1.0}}},
    ]
    ascending = SortBy.parse('site.coord.lat').apply(rows)
    assert [r['name'] for r in ascending] == ['a', 'b', 'c']  # null last
    descending = SortBy.parse('-site.coord.lat').apply(rows)
    assert [r['name'] for r in descending] == ['c', 'b', 'a']  # null first under reverse


def test_sortby_apply_multiple_nulls_are_stable() -> None:
    # two missing-value rows exercise the _Last sentinel comparing against itself
    rows: list[dict[str, Any]] = [{'name': 'x'}, {'name': 'y'}, {'name': 'a', 'depth': 1}]
    ordered = SortBy.parse('depth').apply(rows)
    assert [r['name'] for r in ordered] == ['a', 'x', 'y']  # nulls last, original order kept


# ------------------------------------------------------------------------ conformance


def test_filter_conformance_classes() -> None:
    uris = filter_conformance_classes()
    assert CONF_CQL2_TEXT in uris
    assert filter_conformance_classes(cql2_text=False).count(CONF_CQL2_TEXT) == 0


def test_resources_are_typed() -> None:
    assert isinstance(queryables_from_model(BedProps), Queryables)
    assert isinstance(sortables_from_model(BedProps), Sortables)
