from __future__ import annotations

import json

import pytest

from gazebo.context import use_context
from gazebo.negotiation import GEOJSON, HTML, JSON, Representation, alternate_links, negotiate
from gazebo.params import ParamError
from gazebo.problems import ProblemException
from gazebo.rels import Rel

AVAILABLE = [JSON, HTML]


# --- ?f= takes precedence --------------------------------------------------


def test_f_selects_by_key():
    assert negotiate(AVAILABLE, f='html') is HTML
    assert negotiate(AVAILABLE, f='json') is JSON


def test_f_wins_over_accept():
    # f=json even though Accept prefers html
    assert negotiate(AVAILABLE, f='json', accept='text/html') is JSON


def test_unknown_f_is_param_error():
    with pytest.raises(ParamError) as exc:
        negotiate(AVAILABLE, f='xml')
    assert exc.value.parameter == 'f'


# --- Accept negotiation ----------------------------------------------------


def test_accept_exact_match():
    assert negotiate(AVAILABLE, accept='text/html') is HTML


def test_accept_respects_q_values():
    assert negotiate(AVAILABLE, accept='text/html;q=0.2, application/json;q=0.9') is JSON


def test_accept_wildcard_falls_to_default_order():
    # */* matches everything -> server-preferred first (JSON)
    assert negotiate(AVAILABLE, accept='*/*') is JSON


def test_accept_type_wildcard():
    assert negotiate([JSON, HTML], accept='text/*') is HTML


def test_accept_specificity_beats_wildcard():
    # exact application/json (q=1) should beat */*;q=0.1
    reps = [HTML, JSON]
    assert negotiate(reps, accept='*/*;q=0.1, application/json') is JSON


def test_accept_nan_qvalue_does_not_block_a_valid_type():
    # A nan qvalue on one range must not poison the max() and 406 the whole request:
    # the other, acceptable type still wins.
    assert negotiate([JSON, HTML], accept='application/json;q=nan, text/html;q=0.9') is HTML


def test_accept_inf_qvalue_does_not_outrank_a_valid_type():
    # inf must not let a malformed range jump ahead of a real preference.
    assert negotiate([JSON, HTML], accept='application/json;q=inf, text/html;q=0.9') is HTML


def test_accept_out_of_range_qvalue_is_dropped():
    # q must be 0..1; a malformed q>1 is dropped (scores 0), so a sole type with no
    # other acceptable range is a 406 rather than being served on a bad qvalue.
    with pytest.raises(ProblemException) as exc:
        negotiate([JSON], accept='application/json;q=2')
    assert exc.value.status == 406


def test_unacceptable_accept_is_406():
    with pytest.raises(ProblemException) as exc:
        negotiate(AVAILABLE, accept='application/xml')
    assert exc.value.status == 406


def test_geojson_offered():
    assert negotiate([GEOJSON, HTML], accept='application/geo+json') is GEOJSON


def test_malformed_q_value_treated_as_zero():
    # a non-numeric q drops that range to 0; the other (valid) range still wins
    assert negotiate(AVAILABLE, accept='text/html;q=oops, application/json') is JSON


def test_accept_token_without_slash_ignored():
    # a bogus media range without a '/' is skipped, leaving the valid one
    assert negotiate(AVAILABLE, accept='garbage, text/html') is HTML


# --- defaults --------------------------------------------------------------


def test_default_when_nothing_supplied():
    assert negotiate(AVAILABLE) is JSON  # first offered
    assert negotiate(AVAILABLE, default=HTML) is HTML


def test_empty_available_raises():
    with pytest.raises(ValueError, match='at least one'):
        negotiate([])


# --- alternate links -------------------------------------------------------


def test_alternate_links_point_at_other_reps(ctx):
    ctx.url = 'https://api.example.com/collections/x'
    links = alternate_links(JSON, [JSON, HTML, GEOJSON])
    # one per representation except the current (JSON)
    assert {link.type for link in links} == {HTML.media_type, GEOJSON.media_type}
    assert all(link.rel == Rel.ALTERNATE for link in links)
    with use_context(ctx):
        hrefs = [json.loads(link.model_dump_json())['href'] for link in links]
    assert any('f=html' in href for href in hrefs)
    assert any('f=geojson' in href for href in hrefs)


def test_alternate_links_empty_for_sole_representation():
    assert alternate_links(JSON, [JSON]) == []


def test_representation_is_hashable_value():
    assert Representation('json', 'application/json') == JSON
