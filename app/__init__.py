import os
import sys
from pathlib import Path
from flask import Flask


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "artillery-dev-secret"),
        TASK_DIR=Path(os.environ.get("TASK_DIR", "/tasks")),
        DOWNLOAD_DIR=Path(os.environ.get("DOWNLOAD_DIR", "/downloads")),
        LOG_DIR=Path(os.environ.get("LOG_DIR", "/logs")),
        CONFIG_FILE=Path(os.environ.get("CONFIG_FILE", "/config/config.json")),
        PYTHON_BIN=os.environ.get("PYTHON_BIN", sys.executable),
        RUNNER_TASK=Path(os.environ.get("RUNNER_TASK", "/app/runner_task.py")),
        RUNNER_SINGLE=Path(os.environ.get("RUNNER_SINGLE", "/app/runner_single.py")),
    )

    for directory in (app.config["TASK_DIR"], app.config["DOWNLOAD_DIR"], app.config["LOG_DIR"], app.config["CONFIG_FILE"].parent):
        directory.mkdir(parents=True, exist_ok=True)

    from .routes import bp

    app.register_blueprint(bp)

    return app


__all__ = ["create_app"]
