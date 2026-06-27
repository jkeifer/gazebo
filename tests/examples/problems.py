"""Runnable examples backing ``docs/core/problems.md``."""

from __future__ import annotations

import pytest

# --8<-- [start:raise]
from gazebo.problems import ProblemException


def get_plant(plant_id: int) -> dict:
    raise ProblemException(
        404,
        detail=f'no plant with id {plant_id}',
        instance=f'/plants/{plant_id}',
    )


# --8<-- [end:raise]


with pytest.raises(ProblemException) as caught:
    get_plant(99)

assert caught.value.status == 404
assert caught.value.problem.title == 'Not Found'  # defaulted from the status phrase
assert caught.value.problem.detail == 'no plant with id 99'
