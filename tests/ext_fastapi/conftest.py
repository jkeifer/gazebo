"""Package-wide fixtures for the FastAPI-glue tests.

Only the ``client`` fixture lives here, since it is shared across the injection, router,
CORS, problem, and health test modules. Per-concern clients (params, folded, filtering,
loc) are defined in the single module that uses them.
"""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from .support import TORN, make_app


@pytest.fixture
def client():
    TORN.clear()
    with TestClient(make_app()) as c:
        yield c
