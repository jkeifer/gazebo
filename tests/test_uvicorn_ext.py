"""Tests for gazebo.ext.uvicorn — the argv-boundary serve command over uvicorn.

serve() forwards documented CLI argv to uvicorn's console entry point, so these tests
drive uvicorn's REAL parsing/transforms and patch only the terminal run() (via
sys.modules['uvicorn.main'], since uvicorn's callback resolves run from module globals).
The coupling canary asserts the small, documented surface we now depend on."""

import json
import os

from pathlib import Path
from typing import Any

import click
import pytest
import uvicorn

from click.testing import CliRunner
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from gazebo.ext.cli import default_log_config
from gazebo.ext.uvicorn import serve, serve_command


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')
    greeting: str = 'hello'
    debug: bool = False


def _factory() -> FastAPI:  # module-level -> has an import string
    return FastAPI()


def make_app() -> FastAPI:  # a plain import-string target for serve() tests
    return FastAPI()


def _patch_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch uvicorn's terminal run() and return a dict capturing what reaches it,
    including the parsed log-config file content (the temp file is unlinked after run)."""
    import sys

    captured: dict[str, Any] = {}

    def fake_run(app: str, **kw: Any) -> None:
        captured['app'] = app
        captured.update(kw)
        lc = kw.get('log_config')
        if isinstance(lc, str) and Path(lc).exists():
            captured['log_config_content'] = json.loads(Path(lc).read_text())

    monkeypatch.setattr(sys.modules['uvicorn.main'], 'run', fake_run)
    return captured


# --- coupling canary ---------------------------------------------------------


def test_uvicorn_cli_coupling_canary() -> None:
    # we speak argv to uvicorn's console command and read its help; assert that surface.
    assert isinstance(uvicorn.main, click.Command)
    assert callable(uvicorn.main.main)  # the console entry point we forward argv to
    help_text = uvicorn.main.get_help(click.Context(uvicorn.main))
    assert '--workers' in help_text


# --- serve() -----------------------------------------------------------------


def test_serve_forwards_argv_through_real_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_run(monkeypatch)

    serve(f'{__name__}:make_app', '--workers', '3', factory=True)

    assert captured['app'] == f'{__name__}:make_app'
    assert captured['factory'] is True
    assert captured['workers'] == 3
    assert captured['host'] == '127.0.0.1'  # uvicorn's own default for an unpassed option
    assert captured['log_config_content'] == default_log_config()  # injected default


def test_serve_dict_log_config_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_run(monkeypatch)
    cfg = default_log_config(json_logs=True)

    serve(f'{__name__}:make_app', log_config=cfg)

    assert captured['log_config_content'] == cfg


def test_serve_str_log_config_passes_through(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _patch_run(monkeypatch)
    # uvicorn's --log-config is a Path(exists=True), so the file must actually exist.
    cfg_file = tmp_path / 'logging.json'
    cfg_file.write_text('{"version": 1}')

    serve(f'{__name__}:make_app', log_config=str(cfg_file))
    assert captured['log_config'] == str(cfg_file)

    serve(f'{__name__}:make_app', log_config=cfg_file)
    assert captured['log_config'] == str(cfg_file)  # Path stringified, passed as-is


def test_serve_explicit_log_config_overrides_injected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _patch_run(monkeypatch)
    cfg_file = tmp_path / 'operator.json'
    cfg_file.write_text('{"version": 1}')
    # log_config=None injects a temp default, but an explicit --log-config in the args
    # is forwarded LAST, so click's last-value-wins lets the operator override it.
    serve(f'{__name__}:make_app', '--log-config', str(cfg_file))
    assert captured['log_config'] == str(cfg_file)


def test_serve_bad_flag_raises_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch)
    with pytest.raises(click.exceptions.UsageError):
        serve(f'{__name__}:make_app', '--wokers', '2')


def test_serve_rejects_live_app_object() -> None:
    with pytest.raises((ValueError, TypeError)):
        serve(FastAPI())  # a live instance has no import string


# --- serve_command() ---------------------------------------------------------


def test_command_has_settings_flags_not_uvicorn_flags() -> None:
    cmd = serve_command(_factory, settings=Settings)
    flags = {o.opts[0] for o in cmd.params if getattr(o, 'opts', None)}
    assert '--app-greeting' in flags  # settings option, prefixed
    assert '--app-debug' in flags  # bool -> --app-debug/--no-app-debug
    assert '--check' in flags
    assert '--help-server' in flags
    assert '--workers' not in flags  # uvicorn options are forwarded, not our own params


def test_command_end_to_end_interleaves_settings_and_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_run(monkeypatch)
    monkeypatch.delenv('APP_GREETING', raising=False)

    cmd = serve_command(_factory, settings=Settings)
    result = CliRunner().invoke(cmd, ['--app-greeting', 'hi', '--workers', '2'])

    assert result.exit_code == 0, result.output
    assert os.environ['APP_GREETING'] == 'hi'  # settings flag wrote its env var
    assert captured['app'] == f'{__name__}:_factory'  # derived import string
    assert captured['factory'] is True  # factory forced for a callable
    assert captured['workers'] == 2  # forwarded uvicorn option reached run()
    monkeypatch.delenv('APP_GREETING', raising=False)


def test_author_uvicorn_args_are_operator_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_run(monkeypatch)
    cmd = serve_command(_factory, uvicorn_args=('--workers', '2'))

    # no operator override -> author default stands
    assert CliRunner().invoke(cmd, []).exit_code == 0
    assert captured['workers'] == 2

    # operator arg comes after the author default, so last-wins gives it the edge
    assert CliRunner().invoke(cmd, ['--workers', '3']).exit_code == 0
    assert captured['workers'] == 3


def test_help_server_lists_uvicorn_options_even_with_required_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('APP_API_URL', raising=False)

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        api_url: str  # required, unset

    cmd = serve_command(_factory, settings=S)
    result = CliRunner().invoke(cmd, ['--help-server'])
    assert result.exit_code == 0, result.output
    assert '--workers' in result.output  # uvicorn's own help, eager past the required opt


def test_typo_unknown_flag_surfaces_uvicorn_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch)
    cmd = serve_command(_factory, settings=Settings)
    result = CliRunner().invoke(cmd, ['--wokers', '2'])
    assert result.exit_code != 0
    assert 'No such option' in result.output


def test_help_documents_settings_and_forwarding() -> None:
    cmd = serve_command(_factory, settings=Settings)
    help_text = CliRunner().invoke(cmd, ['--help']).output
    assert 'APP_GREETING' in help_text  # settings documented
    assert '--help-server' in help_text  # points to uvicorn's help


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


def test_rejects_live_app_object() -> None:
    with pytest.raises((ValueError, TypeError)):
        serve_command(FastAPI())  # a live instance has no import string


def test_secrets_documented_in_help_but_not_settable() -> None:
    from pydantic import SecretStr

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        db_password: SecretStr | None = None

    cmd = serve_command(_factory, settings=S)
    flags = {o.opts[0] for o in cmd.params if getattr(o, 'opts', None)}
    assert '--app-db-password' not in flags  # never a value flag

    help_text = CliRunner().invoke(cmd, ['--help']).output
    assert 'APP_DB_PASSWORD' in help_text  # documented as a config surface


def test_required_secret_marked_in_help() -> None:
    from pydantic import SecretStr

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        token: SecretStr  # required secret, no flag

    help_text = CliRunner().invoke(serve_command(_factory, settings=S), ['--help']).output
    assert 'APP_TOKEN' in help_text
    assert '(required)' in help_text


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
