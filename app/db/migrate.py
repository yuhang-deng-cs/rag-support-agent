"""Run Alembic migrations from code (app startup, tests) or the CLI (`alembic upgrade head`)."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BASELINE_REVISION = "0001"


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        cfg.attributes["connection"] = connection  # reuse the caller's connection/transaction
    return cfg


def upgrade_to_head(connection: Connection) -> None:
    """Upgrade on an existing (sync) connection, e.g. via `AsyncConnection.run_sync`.

    Databases created before migrations existed (tables present, no `alembic_version`) are
    stamped at the baseline first, so upgrading them only applies the newer revisions.
    """
    tables = set(inspect(connection).get_table_names())
    cfg = alembic_config(connection)
    if "tenants" in tables and "alembic_version" not in tables:
        logger.info("Existing schema without migration history: stamping %s", BASELINE_REVISION)
        command.stamp(cfg, BASELINE_REVISION)
    command.upgrade(cfg, "head")
