from __future__ import annotations

import json

import pytest

from pydantic import ValidationError

from gazebo.problems import ProblemException, ProblemRegistry, ProblemType


def test_problemtype_problem_uses_defaults():
    pt = ProblemType(type='https://e/x', title='X', status=404, detail='default')
    p = pt.problem()
    assert (p.type, p.title, p.status, p.detail) == ('https://e/x', 'X', 404, 'default')


def test_problemtype_per_occurrence_detail_and_extensions():
    pt = ProblemType(type='https://e/x', title='X', status=409)
    data = json.loads(
        pt.problem(detail='conflict on 5', instance='/things/5', trace='abc').model_dump_json(),
    )
    assert data['detail'] == 'conflict on 5'
    assert data['instance'] == '/things/5'
    assert data['trace'] == 'abc'  # extension member rides alongside the standard ones


def test_problemtype_exception_is_raisable_and_carries_type():
    pt = ProblemType(type='https://e/nf', title='Not found', status=404)
    with pytest.raises(ProblemException) as caught:
        raise pt.exception(detail='no 9')
    assert caught.value.status == 404
    assert caught.value.problem.type == 'https://e/nf'
    assert caught.value.problem.detail == 'no 9'


def test_problemtype_is_frozen():
    pt = ProblemType(type='https://e/x', title='X', status=400)
    with pytest.raises(ValidationError):
        pt.title = 'Y'


def test_registry_register_get_and_catalog():
    reg = ProblemRegistry()
    nf = reg.define('nf', type='https://e/nf', title='Not found', status=404)
    assert reg['nf'] is nf
    assert reg.get('nf') is nf
    assert reg.get('missing') is None
    assert set(reg.catalog()) == {'nf'}


def test_registry_rejects_duplicate_key():
    reg = ProblemRegistry()
    reg.define('nf', type='https://e/nf', title='Not found', status=404)
    with pytest.raises(ValueError, match='already registered'):
        reg.define('nf', type='https://e/other', title='Other', status=400)


def test_registry_catalog_is_a_copy():
    reg = ProblemRegistry()
    reg.define('nf', type='https://e/nf', title='Not found', status=404)
    reg.catalog().clear()
    assert 'nf' in reg.catalog()  # mutating the returned dict can't corrupt the registry
