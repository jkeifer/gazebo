"""Tests for gazebo.ext.cli.

The coupling canary is the load-bearing one: it fails loudly if a uvicorn upgrade
moves the internals we delegate to, instead of breaking mysteriously at runtime."""

import os
import sys

import click
import pytest
import uvicorn

from click.testing import CliRunner
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from gazebo.ext.cli import (
    default_log_config,
    serve,
    serve_command,
    settings_options,
    uvicorn_options,
)


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


def test_non_scalar_and_optional_fields_get_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    monkeypatch.setattr(uvicorn.main, 'callback', lambda **kw: None)
    monkeypatch.delenv('APP_SNOWDB_CONFIG', raising=False)

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        snowdb_config: Path = Path('/etc/snow.cfg')  # scalar, but not str/int/float
        retries: int | None = None  # Optional unwraps to int
        tags: list[str] = []  # complex -> string flag (JSON), not skipped

    cmd = serve_command(_factory, settings=S)
    flags = {o.opts[0] for o in cmd.params if getattr(o, 'opts', None)}
    assert {'--app-snowdb-config', '--app-retries', '--app-tags'} <= flags

    # the Path flag writes its env var verbatim; pydantic turns it back into a Path
    CliRunner().invoke(cmd, ['--app-snowdb-config', '/srv/snow.cfg'])
    assert os.environ['APP_SNOWDB_CONFIG'] == '/srv/snow.cfg'
    assert S().snowdb_config == Path('/srv/snow.cfg')


def test_secrets_documented_in_help_but_not_settable() -> None:
    from pydantic import SecretStr

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        db_password: SecretStr | None = None

    cmd = serve_command(_factory, settings=S)
    flags = {o.opts[0] for o in cmd.params if getattr(o, 'opts', None)}
    assert '--app-db-password' not in flags  # never a value flag (no shell-history leak)

    help_text = CliRunner().invoke(cmd, ['--help']).output
    assert 'APP_DB_PASSWORD' in help_text  # but documented as a config surface


def test_required_field_is_click_required_satisfiable_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uvicorn.main, 'callback', lambda **kw: None)
    monkeypatch.delenv('APP_API_URL', raising=False)

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        api_url: str  # required (no default)

    cmd = serve_command(_factory, settings=S)
    opt = next(o for o in cmd.params if getattr(o, 'opts', None) == ['--app-api-url'])
    assert opt.required is True
    help_text = CliRunner().invoke(cmd, ['--help']).output
    api_line = next(line for line in help_text.splitlines() if '--app-api-url' in line)
    assert 'required' in api_line

    # neither flag nor env -> error; env alone satisfies it (click reads envvar)
    assert CliRunner().invoke(cmd, []).exit_code != 0
    assert CliRunner().invoke(cmd, [], env={'APP_API_URL': 'http://x'}).exit_code == 0


def test_required_secret_marked_in_help() -> None:
    from pydantic import SecretStr

    class S(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_')
        token: SecretStr  # required secret, no flag

    help_text = CliRunner().invoke(serve_command(_factory, settings=S), ['--help']).output
    assert 'APP_TOKEN' in help_text
    assert '(required)' in help_text


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


def test_uvicorn_options_exclude_app_and_factory_by_default() -> None:
    opts = uvicorn_options()  # no exclude given
    names = {o.name for o in opts}
    assert 'app' not in names  # always excluded — you supply it via serve()
    assert 'factory' not in names
    assert 'workers' in names  # a real uvicorn option composed in


def test_uvicorn_options_exclude_is_additive_and_copies() -> None:
    opts = uvicorn_options(exclude={'workers'})
    names = {o.name for o in opts}
    assert 'workers' not in names  # pinned by the caller
    assert {'app', 'factory'}.isdisjoint(names)  # still excluded
    assert 'host' in names
    # copies, never uvicorn's process-global originals
    originals = {id(p) for p in uvicorn.main.params}
    assert all(id(o) not in originals for o in opts)


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


def test_settings_options_exclude_drops_field() -> None:
    opts = settings_options(Settings, exclude={'greeting'})
    flags = {o.opts[0] for o in opts}
    assert '--app-greeting' not in flags
    assert '--app-debug' in flags  # other fields untouched


def test_serve_partial_kwargs_through_real_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    # through uvicorn's REAL callback (which has no parameter defaults of its own):
    # serve() must fill unpassed options with uvicorn's CLI defaults, so a partial
    # call like serve(app, workers=3) is complete. Patch only the final run().
    uvicorn_main_mod = sys.modules['uvicorn.main']
    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn_main_mod, 'run', lambda app, **kw: captured.update(app=app, **kw))

    serve('pkg.mod:make_app', factory=True, workers=3)

    assert captured['app'] == 'pkg.mod:make_app'
    assert captured['factory'] is True
    assert captured['workers'] == 3
    assert captured['host'] == '127.0.0.1'  # unpassed option got uvicorn's CLI default
    assert captured['log_config'] is not None  # default log config injected


def test_serve_rejects_unknown_kwarg() -> None:
    with pytest.raises(ValueError, match='wokers'):
        serve('pkg.mod:make_app', wokers=2)


def test_settings_options_rename_bool_becomes_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('APP_DEBUG', raising=False)
    opts = settings_options(Settings, rename={'debug': '--verbose'})
    verbose = next(o for o in opts if o.opts == ['--verbose'])
    assert verbose.secondary_opts == ['--no-verbose']  # toggle derived automatically
    cmd = click.Command('x', params=opts, callback=lambda: None)
    result = CliRunner().invoke(cmd, ['--no-verbose'])
    assert result.exit_code == 0, result.output
    assert os.environ['APP_DEBUG'] == 'False'  # still propagates to the original field


def test_json_log_config_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    import logging
    import logging.config

    cfg = default_log_config(json_logs=True)
    logging.config.dictConfig(cfg)
    logging.getLogger('uvicorn.error').warning('hello %s', 'world')
    err = capsys.readouterr().err
    import json

    assert json.loads(err.strip().splitlines()[-1])['message'] == 'hello world'
