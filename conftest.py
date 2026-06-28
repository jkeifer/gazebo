"""Opt into gazebo's pytest plugin for this project's own test suite.

``gazebo.testing`` no longer auto-registers via a ``pytest11`` entry point (that
would import gazebo, and impose its fixtures, on every downstream pytest session).
Projects opt in explicitly with this one line in their top-level ``conftest.py`` —
which also enables pytest's assertion rewriting for the helpers.

It must live at the project root: pytest only honors ``pytest_plugins`` in the
rootdir conftest, not a sub-directory one. (Loading the plugin here — rather than via
``-p`` in ``addopts`` — also lets pytest-cov start instrumenting *before* gazebo is
imported, so the coverage report isn't skewed by the import happening too early.)
"""

pytest_plugins = ['gazebo.testing']
