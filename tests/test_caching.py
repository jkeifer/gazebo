from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from gazebo.caching import (
    etag_for,
    http_date,
    if_none_match_satisfied,
    is_not_modified,
    parse_http_date,
)


class _Model(BaseModel):
    a: int
    b: str


# --- etag_for --------------------------------------------------------------


def test_etag_is_weak_by_default():
    tag = etag_for({'x': 1})
    assert tag.startswith('W/"')
    assert tag.endswith('"')


def test_etag_strong_when_requested():
    tag = etag_for({'x': 1}, weak=False)
    assert not tag.startswith('W/')
    assert tag.startswith('"')


def test_etag_is_stable_for_equal_values():
    assert etag_for({'a': 1, 'b': 2}) == etag_for({'b': 2, 'a': 1})  # key order irrelevant


def test_etag_differs_for_different_values():
    assert etag_for({'a': 1}) != etag_for({'a': 2})


def test_etag_accepts_model_str_bytes():
    assert etag_for(_Model(a=1, b='x')).startswith('W/')
    assert etag_for('hello') == etag_for(b'hello')


# --- http date round-trip --------------------------------------------------


def test_http_date_round_trips():
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    formatted = http_date(dt)
    assert formatted.endswith('GMT')
    assert parse_http_date(formatted) == dt


def test_parse_bad_http_date_is_none():
    assert parse_http_date('not a date') is None


# --- if-none-match comparison ----------------------------------------------


def test_if_none_match_star():
    assert if_none_match_satisfied('"abc"', '*')


def test_if_none_match_weak_comparison_ignores_prefix():
    assert if_none_match_satisfied('W/"abc"', '"abc"')
    assert if_none_match_satisfied('"abc"', 'W/"abc"')


def test_if_none_match_list():
    assert if_none_match_satisfied('"b"', '"a", "b", "c"')
    assert not if_none_match_satisfied('"z"', '"a", "b"')


# --- precondition resolution -----------------------------------------------


def test_not_modified_on_etag_match():
    assert is_not_modified(etag='"x"', if_none_match='"x"')


def test_modified_when_etag_differs():
    assert not is_not_modified(etag='"x"', if_none_match='"y"')


def test_non_get_method_never_304():
    assert not is_not_modified(method='POST', etag='"x"', if_none_match='"x"')


def test_if_none_match_takes_precedence_over_modified_since():
    # If-None-Match present (and not matching) -> ignore If-Modified-Since entirely
    lm = datetime(2020, 1, 1, tzinfo=UTC)
    assert not is_not_modified(
        etag='"x"',
        last_modified=lm,
        if_none_match='"other"',
        if_modified_since=http_date(datetime(2030, 1, 1, tzinfo=UTC)),
    )


def test_not_modified_on_modified_since():
    lm = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    # last-modified is at or before the client's cached copy -> 304
    assert is_not_modified(last_modified=lm, if_modified_since=http_date(lm))


def test_modified_after_since():
    lm = datetime(2025, 1, 1, tzinfo=UTC)
    assert not is_not_modified(
        last_modified=lm,
        if_modified_since=http_date(datetime(2020, 1, 1, tzinfo=UTC)),
    )


def test_malformed_if_modified_since_is_not_304():
    lm = datetime(2020, 1, 1, tzinfo=UTC)
    assert not is_not_modified(last_modified=lm, if_modified_since='?')


def test_no_validators_is_not_304():
    assert not is_not_modified()
