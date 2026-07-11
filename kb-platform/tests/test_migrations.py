"""Alembic migration foundation tests."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url


def test_alembic_has_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert len(script.get_heads()) == 1


def test_alembic_accepts_percent_encoded_database_url():
    env = os.environ.copy()
    password = make_url(env["DATABASE_URL"]).password
    assert password is not None
    encoded_password = f"{password[:-1]}%{ord(password[-1]):02X}"
    env["DATABASE_URL"] = env["DATABASE_URL"].replace(
        f":{password}@", f":{encoded_password}@", 1
    )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_alembic_upgrade_head_creates_existing_tables():
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"kbplatform_migration_{uuid.uuid4().hex}"
    admin_url = source_url.set(database="postgres").render_as_string(hide_password=False)
    target_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    admin_dsn = admin_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    target_dsn = target_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    admin_connection = await asyncpg.connect(admin_dsn)
    try:
        await admin_connection.execute(f'CREATE DATABASE "{database_name}"')
        env = os.environ.copy()
        env["DATABASE_URL"] = target_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        target_connection = await asyncpg.connect(target_dsn)
        try:
            existing_tables = {
                row["table_name"]
                for row in await target_connection.fetch(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    """
                )
            }
        finally:
            await target_connection.close()

        assert {"agents", "capabilities", "knowledge_bases", "audit_logs"} <= existing_tables
    finally:
        await admin_connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
            database_name,
        )
        await admin_connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin_connection.close()
