"""
Twelve-factor behaviour: config from the environment, attached services by
URL, port binding, logs as an event stream, nothing written to local disk.
"""

import logging
import os
import runpy
import sys

import pytest

from app import create_app
from config import database_url


@pytest.mark.parametrize("raw, expected", [
    ("postgres://u:p@db:5432/ruff", "postgresql+psycopg://u:p@db:5432/ruff"),
    ("postgresql://u@db/ruff", "postgresql+psycopg://u@db/ruff"),
    ("postgresql+psycopg://u@db/ruff", "postgresql+psycopg://u@db/ruff"),
    ("sqlite:////app/data/ruff.db", "sqlite:////app/data/ruff.db"),
])
def test_database_is_an_attached_resource(monkeypatch, raw, expected):
    """IV: the database is named by DATABASE_URL, including Heroku-style URLs."""
    monkeypatch.setenv("DATABASE_URL", raw)
    assert database_url() == expected


def test_logs_are_an_event_stream_on_stdout(tmp_path, monkeypatch):
    """XI: log to stdout only; no log files or directories."""
    monkeypatch.chdir(tmp_path)
    create_app("testing")
    handlers = [h for h in logging.getLogger().handlers if getattr(h, "ruff_handler", False)]
    assert handlers and all(type(h) is logging.StreamHandler and h.stream is sys.stdout for h in handlers)
    # (pytest itself attaches a FileHandler to os.devnull; that's not ours)
    file_targets = [h.baseFilename for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]
    assert all(target == os.path.abspath(os.devnull) for target in file_targets), file_targets
    assert not (tmp_path / "logs").exists()
    assert not os.path.exists(os.path.join(os.path.dirname(__file__), "logs"))


def test_json_log_lines(capsys, monkeypatch):
    """Production logs are one JSON object per line, with the request ID."""
    import json
    from app import setup_logging

    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        for handler in saved:
            root.removeHandler(handler)
        monkeypatch.setenv("LOG_FORMAT", "json")
        app = create_app("testing")
        setup_logging(app)
        with app.test_request_context(headers={"X-Request-ID": "req-123"}):
            from flask import g
            g.request_id = "req-123"
            logging.getLogger("ruff.test").warning("hello")
        line = capsys.readouterr().out.strip().splitlines()[-1]
        record = json.loads(line)
        assert record["message"] == "hello" and record["request_id"] == "req-123" and record["level"] == "WARNING"
    finally:
        for handler in list(root.handlers):
            if handler not in saved:
                root.removeHandler(handler)
        for handler in saved:
            root.addHandler(handler)


def test_gunicorn_settings_come_from_the_environment(monkeypatch):
    """VII and IX: port, concurrency and shutdown timing from env; logs to stdout."""
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setenv("GUNICORN_THREADS", "16")
    conf = runpy.run_path(os.path.join(os.path.dirname(__file__), "gunicorn.conf.py"))
    assert conf["bind"] == "0.0.0.0:9123"
    assert (conf["workers"], conf["threads"]) == (2, 16)
    assert conf["accesslog"] == "-" and conf["errorlog"] == "-"
    assert conf["graceful_timeout"] > 0


def test_procfile_and_image_share_the_server_config():
    """One source of truth for how the web process runs, plus a release step."""
    root = os.path.dirname(__file__)
    procfile = open(os.path.join(root, "Procfile"), encoding="utf-8").read()
    dockerfile = open(os.path.join(root, "Dockerfile"), encoding="utf-8").read()
    assert procfile.startswith("release: alembic upgrade head")
    assert 'gunicorn -c gunicorn.conf.py "app:create_app()"' in procfile
    assert 'CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]' in dockerfile
    assert "USER 10001" in dockerfile and "@sha256:" in dockerfile
