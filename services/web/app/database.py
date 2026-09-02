from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import psycopg


class DatabaseConfigurationError(RuntimeError):
    """Raised when required PostgreSQL configuration is unavailable."""


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_environment(cls) -> DatabaseSettings:
        names = (
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "WEB_DB_USER",
            "WEB_DB_PASSWORD",
        )
        values = {name: os.getenv(name) for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise DatabaseConfigurationError(
                "Missing required PostgreSQL configuration: " + ", ".join(missing)
            )

        try:
            port = int(values["POSTGRES_PORT"])
        except ValueError as error:
            raise DatabaseConfigurationError(
                "POSTGRES_PORT must be a valid integer"
            ) from error

        return cls(
            host=values["POSTGRES_HOST"],
            port=port,
            database=values["POSTGRES_DB"],
            user=values["WEB_DB_USER"],
            password=values["WEB_DB_PASSWORD"],
        )


def connect() -> Any:
    """Open a PostgreSQL connection using runtime environment configuration."""
    settings = DatabaseSettings.from_environment()
    return psycopg.connect(
        host=settings.host,
        port=settings.port,
        dbname=settings.database,
        user=settings.user,
        password=settings.password,
    )
