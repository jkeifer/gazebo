"""Example for docs/serving.md — a self-documenting `serve` command."""

import os
import sys

from unittest import mock

import click

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
    settings=Settings,
    log_config=default_log_config(json_logs=True),
)
# --8<-- [end:serve]


flags = {opt.opts[0] for opt in serve_cmd.params if getattr(opt, 'opts', None)}
assert '--app-greeting' in flags  # documented settings flag (+ env var in --help)
assert '--workers' in flags  # uvicorn option, composed in
assert '--check' in flags  # validate-and-exit


# --8<-- [start:compose]
# The option spec is decoupled from the command: compose your own. Settings options
# propagate themselves to the env when passed (expose_value=False), so the callback
# only ever sees uvicorn's options — forward them to serve(), which reuses uvicorn's
# own value transforms. Override args as you compose: rename a settings flag, and pin a
# uvicorn option by excluding it and passing the constant.
@click.command(
    'serve',
    params=[
        *settings_options(Settings, rename={'greeting': '--message'}),
        *uvicorn_options(exclude={'workers'}),
    ],
)
def custom_serve(**uvicorn_kwargs: object) -> None:
    serve('myapp:create_app', factory=True, workers=4, **uvicorn_kwargs)


# --8<-- [end:compose]


custom_flags = {opt.opts[0] for opt in custom_serve.params if getattr(opt, 'opts', None)}
assert '--message' in custom_flags  # renamed settings flag (still writes APP_GREETING)
assert '--app-greeting' not in custom_flags  # the default name is gone
assert '--workers' not in custom_flags  # pinned, so excluded from the CLI
assert '--host' in custom_flags  # other uvicorn options still composed in

# drive the composed command end-to-end (uvicorn's real callback; only run() patched)
os.environ.pop('APP_GREETING', None)
with mock.patch.object(sys.modules['uvicorn.main'], 'run') as run:
    result = CliRunner().invoke(custom_serve, ['--message', 'yo'])
assert result.exit_code == 0, result.output
assert os.environ.pop('APP_GREETING') == 'yo'  # renamed flag propagated to the field
assert run.call_args.kwargs['workers'] == 4  # pinned constant reached uvicorn
assert run.call_args.kwargs['factory'] is True
