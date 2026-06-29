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


# --8<-- [start:registry]
from gazebo.problems import ProblemRegistry

problems = ProblemRegistry()

# Define each problem kind once: a stable `type` URI, a title, a default status.
PLANT_NOT_FOUND = problems.define(
    'plant-not-found',
    type='https://errors.example/plant-not-found',
    title='Plant not found',
    status=404,
)


def get_plant_or_404(plant_id: int) -> dict:
    # Raise it by reference; only the per-occurrence detail/instance vary.
    raise PLANT_NOT_FOUND.exception(
        detail=f'no plant with id {plant_id}',
        instance=f'/plants/{plant_id}',
    )


# Serve the whole catalog (key -> ProblemType) so a client can resolve a `type` URI.
catalog = problems.catalog()
# --8<-- [end:registry]


with pytest.raises(ProblemException) as caught:
    get_plant_or_404(99)

assert caught.value.problem.type == 'https://errors.example/plant-not-found'
assert caught.value.problem.title == 'Plant not found'  # from the registered default
assert catalog['plant-not-found'].status == 404
