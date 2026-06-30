"""Example for docs/serving.md — a self-documenting `serve` command."""

from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from gazebo.ext.cli import default_log_config, serve_command


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


# Add to your click group: cli.add_command(serve)
serve = serve_command(
    create_app,
    settings=Settings,
    log_config=default_log_config(json_logs=True),
)
# --8<-- [end:serve]


flags = {opt.opts[0] for opt in serve.params if getattr(opt, 'opts', None)}
assert '--app-greeting' in flags  # documented settings flag (+ env var in --help)
assert '--workers' in flags  # uvicorn option, composed in
assert '--check' in flags  # validate-and-exit
