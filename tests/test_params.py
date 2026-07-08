from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pydantic import BaseModel, ValidationError

from gazebo.params import (
    CRS84,
    BBox,
    BBoxQuery,
    CrsEnum,
    DatetimeInterval,
    DatetimeQuery,
    ParamError,
    validate_crs,
)

EPSG3857 = 'http://www.opengis.net/def/crs/EPSG/0/3857'

# --- bbox ------------------------------------------------------------------


def test_bbox_2d():
    box = BBox.parse('-10,-20,10,20')
    assert (box.minx, box.miny, box.maxx, box.maxy) == (-10, -20, 10, 20)
    assert box.minz is None
    assert box.maxz is None


def test_bbox_3d():
    box = BBox.parse('-10,-20,0,10,20,100')
    assert box.minz == 0
    assert box.maxz == 100


def test_bbox_allows_antimeridian_wrap():
    # minx > maxx is valid (the box crosses the antimeridian); not an error.
    box = BBox.parse('170,-10,-170,10')
    assert box.minx == 170
    assert box.maxx == -170


@pytest.mark.parametrize(
    'raw',
    [
        '1,2,3',  # wrong count
        '1,2,3,4,5',  # wrong count
        'a,2,3,4',  # non-numeric
        '1,20,3,4',  # miny > maxy
        '0,0,nan,10',  # non-finite (nan slips past ordering checks)
        '0,0,inf,10',  # non-finite
    ],
)
def test_bbox_bad_values_raise(raw):
    with pytest.raises(ParamError) as exc:
        BBox.parse(raw)
    assert exc.value.parameter == 'bbox'


def test_bbox_z_order_checked():
    with pytest.raises(ParamError):
        BBox.parse('0,0,100,1,1,0')  # minz 100 > maxz 0


def test_bbox_contains():
    box = BBox.parse('-10,-20,10,20')
    assert box.contains(0, 0)
    assert box.contains(-10, -20)  # inclusive on the boundary
    assert box.contains(10, 20)
    assert not box.contains(11, 0)  # east of maxx
    assert not box.contains(0, 21)  # north of maxy


def test_bbox_contains_antimeridian():
    # a box crossing the antimeridian (minx 170 > maxx -170): longitudes match if
    # east of minx OR west of maxx; the gap in between is excluded.
    box = BBox.parse('170,-10,-170,10')
    assert box.contains(175, 0)
    assert box.contains(-175, 0)
    assert box.contains(180, 0)
    assert not box.contains(0, 0)  # in the excluded middle
    assert not box.contains(175, 20)  # outside the y range


# --- datetime --------------------------------------------------------------


def test_datetime_instant():
    iv = DatetimeInterval.parse('2020-01-01T00:00:00Z')
    assert iv.is_instant
    assert iv.start == iv.end == datetime(2020, 1, 1, tzinfo=UTC)


def test_datetime_closed_interval():
    iv = DatetimeInterval.parse('2020-01-01T00:00:00Z/2020-12-31T00:00:00Z')
    assert iv.start == datetime(2020, 1, 1, tzinfo=UTC)
    assert iv.end == datetime(2020, 12, 31, tzinfo=UTC)
    assert not iv.is_instant


def test_datetime_open_start():
    iv = DatetimeInterval.parse('../2020-12-31T00:00:00Z')
    assert iv.start is None
    assert iv.end == datetime(2020, 12, 31, tzinfo=UTC)


def test_datetime_open_end():
    iv = DatetimeInterval.parse('2020-01-01T00:00:00Z/..')
    assert iv.start == datetime(2020, 1, 1, tzinfo=UTC)
    assert iv.end is None


def test_datetime_contains():
    iv = DatetimeInterval.parse('2020-01-01T00:00:00Z/2020-12-31T00:00:00Z')
    assert iv.contains(datetime(2020, 6, 1, tzinfo=UTC))
    assert not iv.contains(datetime(2019, 1, 1, tzinfo=UTC))  # before start
    assert not iv.contains(datetime(2021, 1, 1, tzinfo=UTC))  # after end
    # open end includes everything after start
    half_open = DatetimeInterval.parse('2020-01-01T00:00:00Z/..')
    assert half_open.contains(datetime(2999, 1, 1, tzinfo=UTC))


def test_datetime_naive_value_is_treated_as_utc():
    # a date-only value (no time/offset) parses to a tz-aware UTC datetime, so it
    # never trips a naive-vs-aware TypeError when compared against aware data.
    iv = DatetimeInterval.parse('2021-01-01/..')  # open-ended interval from a date
    assert iv.start is not None
    assert iv.start == datetime(2021, 1, 1, tzinfo=UTC)
    assert iv.start.tzinfo is not None
    assert iv.contains(datetime(2021, 6, 1, 12, tzinfo=UTC))


def test_datetime_contains_handles_naive_argument():
    iv = DatetimeInterval.parse('2020-01-01T00:00:00Z/2020-12-31T00:00:00Z')
    # a naive `when` is coerced to UTC rather than raising
    assert iv.contains(datetime(2020, 6, 1))  # noqa: DTZ001  (naive is the point)


@pytest.mark.parametrize(
    'raw',
    [
        'not-a-date',
        '../..',  # open at both ends
        '2021-01-01T00:00:00Z/2020-01-01T00:00:00Z',  # start after end
        '',
    ],
)
def test_datetime_bad_values_raise(raw):
    with pytest.raises(ParamError) as exc:
        DatetimeInterval.parse(raw)
    assert exc.value.parameter == 'datetime'


# --- crs -------------------------------------------------------------------


def test_crs_defaults_to_crs84_when_absent():
    assert validate_crs(None, (CRS84,)) == CRS84


def test_crs_in_allowlist_passes():
    other = 'http://www.opengis.net/def/crs/EPSG/0/3857'
    assert validate_crs(other, (CRS84, other)) == other


def test_crs_outside_allowlist_raises():
    with pytest.raises(ParamError) as exc:
        validate_crs('http://example.com/crs/nope', (CRS84,))
    assert exc.value.parameter == 'crs'


def test_crs_custom_parameter_name_in_error():
    with pytest.raises(ParamError) as exc:
        validate_crs('bad', (CRS84,), parameter='bbox-crs')
    assert exc.value.parameter == 'bbox-crs'


def test_crs_absent_uses_explicit_default():
    epsg3857 = 'http://www.opengis.net/def/crs/EPSG/0/3857'
    # an allow-list without CRS84: an absent value must fall back to an *allowed* crs
    assert validate_crs(None, (epsg3857,), default=epsg3857) == epsg3857


def test_crs_default_not_in_allowlist_raises():
    epsg3857 = 'http://www.opengis.net/def/crs/EPSG/0/3857'
    # the implicit CRS84 default is not in this allow-list: resolving an absent value
    # to it would emit a disallowed crs, so it must raise rather than bypass the list
    with pytest.raises(ValueError, match='not in allowed'):
        validate_crs(None, (epsg3857,))


def test_crs_absent_with_no_default_is_required():
    epsg3857 = 'http://www.opengis.net/def/crs/EPSG/0/3857'
    with pytest.raises(ParamError) as exc:
        validate_crs(None, (epsg3857,), default=None)
    assert exc.value.parameter == 'crs'


# --- composable field types ------------------------------------------------


def test_paramerror_is_not_a_valueerror():
    # Critical: several core @model_validators raise ParamError and rely on it
    # propagating out of construction (not being wrapped into a ValidationError). The
    # folded field types translate ParamError -> ValueError themselves instead.
    assert not issubclass(ParamError, ValueError)


class _Crs(CrsEnum):
    CRS84 = CRS84
    WEB_MERCATOR = EPSG3857


class _Query(BaseModel):
    bbox: BBoxQuery = None
    datetime: DatetimeQuery = None
    # A real class (a CrsEnum subclass): a usable field type with NO type: ignore.
    crs: _Crs = _Crs.CRS84


def test_field_types_parse_good_values():
    q = _Query.model_validate(
        {
            'bbox': '-1,-2,3,4',
            'datetime': '2020-01-01T00:00:00Z/..',
            'crs': CRS84,
        },
    )
    assert isinstance(q.bbox, BBox)
    assert (q.bbox.minx, q.bbox.maxy) == (-1, 4)
    assert isinstance(q.datetime, DatetimeInterval)
    assert q.crs == CRS84
    # members are real strings (the URIs), usable downstream as such
    assert q.crs == _Crs.CRS84
    assert isinstance(q.crs, str)


def test_field_types_absent_resolve():
    q = _Query.model_validate({})
    assert q.bbox is None
    assert q.datetime is None
    assert q.crs == CRS84  # absent crs falls back to the field default


def test_bad_bbox_field_is_valueerror():
    with pytest.raises(ValidationError) as exc:
        _Query.model_validate({'bbox': '1,2,3'})
    # a folded field failure becomes a clean ValidationError located on the field name
    assert exc.value.errors()[0]['loc'] == ('bbox',)


def test_bad_datetime_field_is_valueerror():
    with pytest.raises(ValidationError) as exc:
        _Query.model_validate({'datetime': 'not-a-date'})
    assert exc.value.errors()[0]['loc'] == ('datetime',)


def test_bad_crs_field_is_valueerror():
    with pytest.raises(ValidationError) as exc:
        _Query.model_validate({'crs': 'http://example.com/crs/nope'})
    assert exc.value.errors()[0]['loc'] == ('crs',)


def test_crs_enum_members_are_uri_strings():
    # members compare and behave as their URI value (StrEnum), so they flow downstream
    assert _Crs.WEB_MERCATOR == EPSG3857
    assert _Crs('http://www.opengis.net/def/crs/OGC/1.3/CRS84') is _Crs.CRS84


def test_bbox_field_order_check_translates_to_valueerror():
    # the model_validator ParamError (miny > maxy) is caught by the field validator too
    with pytest.raises(ValidationError) as exc:
        _Query.model_validate({'bbox': '1,20,3,4'})
    assert exc.value.errors()[0]['loc'] == ('bbox',)


def test_folded_fields_have_string_input_schema():
    # bbox/datetime parse into models, but a client *sends* them as strings; the field
    # schema must advertise the string input (a Swagger text box), not the parsed model's
    # object schema, while keeping the Field description/examples.
    props = _Query.model_json_schema()['properties']
    for name in ('bbox', 'datetime'):
        assert props[name]['type'] == 'string'
        assert 'anyOf' not in props[name]  # no $ref to the parsed model
        assert props[name]['description']
        assert props[name]['examples']
