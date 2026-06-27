"""Run every doc example module so the snippets in the docs can't go stale.

Each file in ``tests/examples/`` is a self-contained script whose module-level
asserts validate the snippet it backs. Docs pages include the marked region of
these files via pymdownx.snippets, so what readers see is exactly what runs here.
"""

from __future__ import annotations

import runpy

from pathlib import Path

import pytest

EXAMPLES = sorted(
    p for p in (Path(__file__).parent / 'examples').glob('*.py') if p.name != '__init__.py'
)


@pytest.mark.parametrize('path', EXAMPLES, ids=lambda p: p.stem)
def test_example_runs(path: Path) -> None:
    runpy.run_path(str(path))
