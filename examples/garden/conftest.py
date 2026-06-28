"""Opt into gazebo's pytest plugin for the example's test suite.

One line in the top-level ``conftest.py`` enables the ``gazebo.testing`` fixtures
and pytest's assertion rewriting for its helpers (it no longer auto-registers).
"""

pytest_plugins = ['gazebo.testing']
