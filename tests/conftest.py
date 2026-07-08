from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pytest


@dataclass
class FakeContext:
    """A RequestContext implementation for testing core models with no framework."""

    url: str = 'https://api.example.com/things?limit=10&token=abc'
    base_url: str = 'https://api.example.com/'
    query_params: Mapping[str, str] = field(default_factory=lambda: {'limit': '10'})
    headers: Mapping[str, str] = field(default_factory=dict)

    def url_for(self, name: str, /, **path: object) -> str:
        suffix = ('/' + '/'.join(str(v) for v in path.values())) if path else ''
        return f'https://api.example.com/{name}{suffix}'

    def url_for_template(
        self,
        name: str,
        path: Mapping[str, object],
        template: Sequence[str],
        /,
    ) -> str:
        parts = [name, *(str(v) for v in path.values()), *(f'{{{v}}}' for v in template)]
        return 'https://api.example.com/' + '/'.join(parts)


@pytest.fixture
def ctx() -> FakeContext:
    return FakeContext()
