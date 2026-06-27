from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest


@dataclass
class FakeContext:
    """A RequestContext implementation for testing core models with no framework."""

    url: str = 'https://api.example.com/things?limit=10&token=abc'
    base_url: str = 'https://api.example.com/'
    query_params: Mapping[str, str] = field(default_factory=lambda: {'limit': '10'})

    def url_for(self, name: str, /, **path: object) -> str:
        suffix = ('/' + '/'.join(str(v) for v in path.values())) if path else ''
        return f'https://api.example.com/{name}{suffix}'


@pytest.fixture
def ctx() -> FakeContext:
    return FakeContext()
