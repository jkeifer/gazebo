"""Example for docs/serving.md — a self-documenting `serve` command."""

import os
import sys

from unittest import mock

import click

from click.testing import CliRunner
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from gazebo.ext.cli import SettingsGroup
from gazebo.ext.uvicorn import default_log_config, serve, serve_command


# --8<-- [start:serve]
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')

    greeting: str = 'hello'
    debug: bool = False


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI()

    @app.get('/')
    def root() -> dict[str, str]:
        return {'greeting': settings.greeting}

    return app


# Add to your click group: cli.add_command(serve_cmd)
serve_cmd = serve_command(
    create_app,
    settings_group=SettingsGroup(Settings),
    log_config=default_log_config(json_logs=True),
)
# --8<-- [end:serve]


flags = {opt.opts[0] for opt in serve_cmd.params if getattr(opt, 'opts', None)}
assert '--app-greeting' in flags  # documented settings flag (+ env var in --help)
assert '--check' in flags  # validate-and-exit
assert '--help-server' in flags  # uvicorn's own options live here
assert '--workers' not in flags  # uvicorn options are forwarded, not our own params


# --8<-- [start:compose]
# gazebo.ext.cli imports no server, so the same pieces compose atop any server. Here we
# hand-roll a command: SettingsGroup(...).options writes each setting's env var when passed
# (expose_value=False, so the callback never sees them), and ignore_unknown_options +
# allow_extra_args let every uvicorn flag fall through to ctx.args. We forward those to
# serve() after our own author defaults (--workers 4), which the operator can override.
@click.command(
    'serve',
    context_settings={'ignore_unknown_options': True, 'allow_extra_args': True},
    params=SettingsGroup(Settings, rename={'--app-greeting': '--message'}).options,
)
def custom_serve() -> None:
    ctx = click.get_current_context()
    serve('myapp:create_app', '--workers', '4', *ctx.args, factory=True)


# --8<-- [end:compose]


custom_flags = {opt.opts[0] for opt in custom_serve.params if getattr(opt, 'opts', None)}
assert '--message' in custom_flags  # renamed settings flag (still writes APP_GREETING)
assert '--app-greeting' not in custom_flags  # the default name is gone

# drive the composed command end-to-end (uvicorn's real argv parsing; only run() patched)
os.environ.pop('APP_GREETING', None)
with mock.patch.object(sys.modules['uvicorn.main'], 'run') as run:
    result = CliRunner().invoke(custom_serve, ['--message', 'yo', '--port', '9000'])
assert result.exit_code == 0, result.output
assert os.environ.pop('APP_GREETING') == 'yo'  # renamed flag propagated to the field
assert run.call_args.kwargs['workers'] == 4  # author default reached uvicorn
assert run.call_args.kwargs['port'] == 9000  # operator's forwarded flag too
assert run.call_args.kwargs['factory'] is True
