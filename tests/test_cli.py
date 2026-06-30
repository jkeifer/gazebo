"""Tests for gazebo.ext.cli.

The coupling canary is the load-bearing one: it fails loudly if a uvicorn upgrade
moves the internals we delegate to, instead of breaking mysteriously at runtime."""

import os
import sys

import pytest
import uvicorn

from click.testing import CliRunner
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from gazebo.ext.cli import default_log_config, serve_command


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')
    greeting: str = 'hello'
    debug: bool = False


def _factory() -> FastAPI:  # module-level -> has an import string
    return FastAPI()


def test_uvicorn_coupling_canary() -> None:
    # we pin `app`/`factory` and delegate to the CLI callback; assert those still
    # exist so a uvicorn change trips a test rather than a runtime surprise.
    names = {p.name for p in uvicorn.main.params}
    assert {'app', 'factory'} <= names
    assert callable(uvicorn.main.callback)


def test_builds_and_composes() -> None:
    cmd = serve_command(_factory, settings=Settings)
    flags = {o.opts[0] for o in cmd.params if getattr(o, 'opts', None)}
    assert '--app-greeting' in flags  # settings option, prefixed
    assert '--app-debug' in flags  # bool -> --app-debug/--no-app-debug
    assert '--workers' in flags  # uvicorn option composed in
    assert '--check' in flags


def test_requires_env_prefix() -> None:
    class NoPrefix(BaseSettings):
        host: str = 'x'

    with pytest.raises(ValueError, match='env_prefix'):
        serve_command(_factory, settings=NoPrefix)


def test_rejects_duplicate_prefix() -> None:
    class A(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='X_')
        a: int = 1

    class B(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='X_')
        b: int = 2

    with pytest.raises(ValueError, match='duplicate env_prefix'):
        serve_command(_factory, settings=[A, B])


def test_rejects_unknown_fixed() -> None:
    with pytest.raises(ValueError, match=r'not uvicorn\.run options'):
        serve_command(_factory, settings=Settings, not_a_real_kwarg=1)


def test_rejects_live_app_object() -> None:
    with pytest.raises((ValueError, TypeError)):
        serve_command(FastAPI())  # a live instance has no import string


def test_passed_flag_sets_env_and_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn.main, 'callback', lambda **kw: captured.update(kw))
    monkeypatch.delenv('APP_GREETING', raising=False)

    cmd = serve_command(_factory, settings=Settings)
    result = CliRunner().invoke(cmd, ['--app-greeting', 'hi'])

    assert result.exit_code == 0, result.output
    assert os.environ['APP_GREETING'] == 'hi'  # flag wrote its env var
    assert captured['app'] == f'{__name__}:_factory'  # derived import string
    assert captured['factory'] is True  # factory forced for a callable


def test_delegates_through_real_uvicorn_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    # drive uvicorn's REAL CLI callback (its value transforms) without binding a
    # socket: patch the run() it ultimately calls and assert what reaches it. The
    # callback resolves `run` from the uvicorn.main *module*. We reach that module via
    # sys.modules, because the ``uvicorn.main`` attribute is the re-exported Command
    # (so both attribute access and monkeypatch's string form would resolve wrongly).
    uvicorn_main_mod = sys.modules['uvicorn.main']
    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn_main_mod, 'run', lambda app, **kw: captured.update(app=app, **kw))

    cmd = serve_command(_factory, settings=Settings)
    result = CliRunner().invoke(cmd, ['--workers', '2', '--header', 'x-foo:bar'])

    assert result.exit_code == 0, result.output
    assert captured['app'] == f'{__name__}:_factory'
    assert captured['factory'] is True
    assert captured['workers'] == 2
    # uvicorn's own callback splits '--header x-foo:bar' into a (name, value) pair:
    assert ['x-foo', 'bar'] in captured['headers']  # type: ignore[operator]


def test_check_reports_missing_required() -> None:
    from pydantic import SecretStr

    class Secret(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='SVC_')
        api_key: SecretStr  # required secret, no flag, not set

    cmd = serve_command(_factory, settings=Secret)
    result = CliRunner().invoke(cmd, ['--check'])
    assert result.exit_code == 1
    assert 'api_key' in result.output


def test_check_ok() -> None:
    cmd = serve_command(_factory, settings=Settings)
    result = CliRunner().invoke(cmd, ['--check'])
    assert result.exit_code == 0
    assert 'OK' in result.output


def test_json_log_config_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    import logging
    import logging.config

    cfg = default_log_config(json_logs=True)
    logging.config.dictConfig(cfg)
    logging.getLogger('uvicorn.error').warning('hello %s', 'world')
    err = capsys.readouterr().err
    import json

    assert json.loads(err.strip().splitlines()[-1])['message'] == 'hello world'
