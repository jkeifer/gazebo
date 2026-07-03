"""Tests for gazebo.ext.cli — the server-agnostic CLI toolkit.

The layering canary is load-bearing: importing the core must NOT pull in uvicorn, so
the same pieces can build a serve command atop any server."""

import os
import subprocess
import sys

import click
import pytest

from click.testing import CliRunner
from pydantic_settings import BaseSettings, SettingsConfigDict

from gazebo.ext.cli import (
    default_log_config,
    secrets_epilog,
    settings_options,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')
    greeting: str = 'hello'
    debug: bool = False


def test_core_does_not_import_uvicorn() -> None:
    # the core must be usable atop any server (granian, ...), so importing it must not
    # drag uvicorn in. A subprocess is the only honest check (uvicorn may already be
    # imported in-process by other tests).
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            "import sys, gazebo.ext.cli; assert 'uvicorn' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_settings_options_self_propagate_on_a_plain_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the whole point of the split: drop the options onto *any* command and they
    # export their env var themselves — the callback takes no settings args at all.
    monkeypatch.delenv('APP_GREETING', raising=False)
    cmd = click.Command('x', params=settings_options(Settings), callback=lambda: None)
    result = CliRunner().invoke(cmd, ['--app-greeting', 'hi'])
    assert result.exit_code == 0, result.output
    assert os.environ['APP_GREETING'] == 'hi'


def test_settings_options_compose_multiple_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    class A(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='A_')
        one: str = 'x'

    class B(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='B_')
        two: str = 'y'

    monkeypatch.delenv('A_ONE', raising=False)
    monkeypatch.delenv('B_TWO', raising=False)
    params = [*settings_options(A), *settings_options(B)]
    cmd = click.Command('x', params=params, callback=lambda: None)
    result = CliRunner().invoke(cmd, ['--a-one', '1', '--b-two', '2'])
    assert result.exit_code == 0, result.output
    assert os.environ['A_ONE'] == '1'
    assert os.environ['B_TWO'] == '2'


def test_settings_option_left_alone_does_not_touch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # env/default-sourced values are left untouched, so the app's own resolution wins.
    monkeypatch.delenv('APP_GREETING', raising=False)
    cmd = click.Command('x', params=settings_options(Settings), callback=lambda: None)
    assert CliRunner().invoke(cmd, []).exit_code == 0
    assert 'APP_GREETING' not in os.environ


def test_settings_options_requires_env_prefix() -> None:
    class NoPrefix(BaseSettings):
        host: str = 'x'

    with pytest.raises(ValueError, match='env_prefix'):
        settings_options(NoPrefix)


def test_settings_options_rename_keeps_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('APP_GREETING', raising=False)
    opts = settings_options(Settings, rename={'greeting': '--message'})
    flags = {o.opts[0] for o in opts}
    assert '--message' in flags
    assert '--app-greeting' not in flags
    # the renamed flag still propagates to the field's original env var
    cmd = click.Command('x', params=opts, callback=lambda: None)
    result = CliRunner().invoke(cmd, ['--message', 'hi'])
    assert result.exit_code == 0, result.output
    assert os.environ['APP_GREETING'] == 'hi'


def test_settings_options_rename_bool_becomes_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('APP_DEBUG', raising=False)
    opts = settings_options(Settings, rename={'debug': '--verbose'})
    verbose = next(o for o in opts if o.opts == ['--verbose'])
    assert verbose.secondary_opts == ['--no-verbose']  # toggle derived automatically
    cmd = click.Command('x', params=opts, callback=lambda: None)
    result = CliRunner().invoke(cmd, ['--no-verbose'])
    assert result.exit_code == 0, result.output
    assert os.environ['APP_DEBUG'] == 'False'  # still propagates to the original field


def test_settings_options_exclude_drops_field() -> None:
    opts = settings_options(Settings, exclude={'greeting'})
    flags = {o.opts[0] for o in opts}
    assert '--app-greeting' not in flags
    assert '--app-debug' in flags  # other fields untouched


def test_non_scalar_and_optional_fields_get_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    monkeypatch.delenv('APP_SNOWDB_CONFIG', raising=False)

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        snowdb_config: Path = Path('/etc/snow.cfg')  # scalar, but not str/int/float
        retries: int | None = None  # Optional unwraps to int
        tags: list[str] = []  # complex -> string flag (JSON), not skipped

    opts = settings_options(S)
    flags = {o.opts[0] for o in opts}
    assert {'--app-snowdb-config', '--app-retries', '--app-tags'} <= flags

    # the Path flag writes its env var verbatim; pydantic turns it back into a Path
    cmd = click.Command('x', params=opts, callback=lambda: None)
    CliRunner().invoke(cmd, ['--app-snowdb-config', '/srv/snow.cfg'])
    assert os.environ['APP_SNOWDB_CONFIG'] == '/srv/snow.cfg'
    assert S().snowdb_config == Path('/srv/snow.cfg')


def test_required_field_is_click_required_satisfiable_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('APP_API_URL', raising=False)

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        api_url: str  # required (no default)

    opts = settings_options(S)
    opt = next(o for o in opts if getattr(o, 'opts', None) == ['--app-api-url'])
    assert opt.required is True
    cmd = click.Command('x', params=opts, callback=lambda: None)
    help_text = CliRunner().invoke(cmd, ['--help']).output
    api_line = next(line for line in help_text.splitlines() if '--app-api-url' in line)
    assert 'required' in api_line

    # neither flag nor env -> error; env alone satisfies it (click reads envvar)
    assert CliRunner().invoke(cmd, []).exit_code != 0
    assert CliRunner().invoke(cmd, [], env={'APP_API_URL': 'http://x'}).exit_code == 0


def test_secrets_not_settable_but_documented() -> None:
    from pydantic import SecretStr

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        db_password: SecretStr | None = None

    flags = {o.opts[0] for o in settings_options(S)}
    assert '--app-db-password' not in flags  # never a value flag (no shell-history leak)
    assert 'APP_DB_PASSWORD' in (secrets_epilog(S) or '')  # documented instead


def test_secrets_epilog_single_and_sequence_forms() -> None:
    from pydantic import SecretStr

    class A(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='A_')
        token: SecretStr  # required secret

    class B(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='B_')
        key: SecretStr | None = None  # optional secret

    single = secrets_epilog(A)
    assert single is not None
    assert 'A_TOKEN' in single
    assert '(required)' in single  # required marked (no flag to carry [required])

    both = secrets_epilog([A, B])
    assert both is not None
    assert 'A_TOKEN' in both
    assert 'B_KEY' in both

    # no secrets -> None, so a command can use it as its epilog unconditionally
    class Plain(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='P_')
        host: str = 'x'

    assert secrets_epilog(Plain) is None


def test_json_log_config_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    import json
    import logging
    import logging.config

    cfg = default_log_config(json_logs=True)
    logging.config.dictConfig(cfg)
    logging.getLogger('uvicorn.error').warning('hello %s', 'world')
    err = capsys.readouterr().err
    assert json.loads(err.strip().splitlines()[-1])['message'] == 'hello world'
