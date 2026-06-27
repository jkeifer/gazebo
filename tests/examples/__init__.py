"""Runnable doc-snippet modules backing the docs pages.

Marked as a package so static checkers give these files qualified module names
(``tests.examples.<page>``) rather than treating each as a top-level script. That
avoids name collisions with stdlib modules (e.g. ``collections``) under mypy's
``scripts_are_modules``. They are executed for validation by ``test_examples.py``.
"""
