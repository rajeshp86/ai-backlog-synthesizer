"""Shared logger config — keeps log setup consistent across modules.

Environment variables
---------------------
LOG_LEVEL   INFO (default) | DEBUG | WARNING | ERROR
LOG_FORMAT  text (default) | json

Set LOG_FORMAT=json in production containers so logs are structured
and queryable in Azure Monitor / Log Analytics / Datadog.

JSON output fields
------------------
  timestamp  ISO-8601 UTC
  level      INFO / WARNING / ERROR / ...
  logger     module name (e.g. "orchestrator", "tools.claude_tool")
  message    log message text
  + any extra keyword arguments passed to log calls

Log shipping (no code changes needed — infrastructure only)
-----------------------------------------------------------
  Azure Container Apps  — logs stream to the Log Analytics workspace
      attached to the Container Apps Environment (set in azure_setup.sh).
      Query with: az containerapp logs show ... or Log Analytics KQL.
      With LOGS_DIR set, logs are also written to ${LOGS_DIR}/app.log on the
      mounted Azure Files share so they persist across restarts/scale-to-zero.

  Datadog  — set DD_AGENT_HOST + DD_SERVICE env vars and add the
      datadog-agent sidecar; structured JSON lines are auto-parsed.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

# Persist diagnostic logs to a file in addition to stderr when LOGS_DIR is set
# (e.g. on Azure, where LOGS_DIR points at the mounted Azure Files share so the
# logs survive restarts/scale-to-zero). Disable explicitly with LOG_TO_FILE=0.
# Rotation keeps the share from filling: 10 MB × 5 files per logger config.
_LOG_FILE_MAX_BYTES = int(os.environ.get("LOG_FILE_MAX_BYTES", str(10 * 1024 * 1024)))
_LOG_FILE_BACKUPS = int(os.environ.get("LOG_FILE_BACKUP_COUNT", "5"))


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

        if os.environ.get("LOG_FORMAT", "text").lower() == "json":
            _configure_json(level)
        else:
            _configure_text(level)

        _attach_file_handler(level)

        _CONFIGURED = True
    return logging.getLogger(name)


def _file_handler_path() -> Path | None:
    """Resolve the log file path, or None if file logging is disabled/unset.

    Honours LOG_FILE (explicit path) first, then LOGS_DIR/app.log. Returns None
    when LOG_TO_FILE=0 or no destination is configured (e.g. local dev)."""
    if os.environ.get("LOG_TO_FILE", "1").strip().lower() in ("0", "false", "no"):
        return None
    explicit = os.environ.get("LOG_FILE", "").strip()
    if explicit:
        return Path(explicit)
    logs_dir = os.environ.get("LOGS_DIR", "").strip()
    if logs_dir:
        return Path(logs_dir) / "app.log"
    return None


def _attach_file_handler(level: int) -> None:
    """Add a rotating file handler to the root logger when configured.

    Reuses the formatter already installed by _configure_text/_configure_json so
    the file lines match the console format (text or JSON)."""
    path = _file_handler_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            path, maxBytes=_LOG_FILE_MAX_BYTES, backupCount=_LOG_FILE_BACKUPS,
            encoding="utf-8",
        )
        fh.setLevel(level)
        root = logging.getLogger()
        existing = root.handlers[0].formatter if root.handlers else None
        if existing is not None:
            fh.setFormatter(existing)
        root.addHandler(fh)
    except OSError as exc:
        # Never let a bad/unwritable log path crash the app — keep stderr logging.
        logging.getLogger(__name__).warning(
            "Could not open log file %s (%s); continuing with stderr only.", path, exc
        )


def _configure_text(level: int) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _configure_json(level: int) -> None:
    try:
        from pythonjsonlogger.jsonlogger import JsonFormatter

        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            JsonFormatter(
                # These fields are renamed in rename_fields below so the
                # output keys match the conventions of common log aggregators.
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={
                    "asctime": "timestamp",
                    "levelname": "level",
                    "name": "logger",
                },
                # ISO-8601 UTC so timestamps are sortable in every log system.
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        # force=True replaces any handlers that basicConfig may have added.
        logging.basicConfig(handlers=[handler], level=level, force=True)
    except ImportError:
        # python-json-logger not installed — fall back to text gracefully.
        _configure_text(level)
