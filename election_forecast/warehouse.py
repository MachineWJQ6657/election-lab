"""Parquet snapshots and a small DuckDB analytical warehouse."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .settings import Settings, settings


class Warehouse:
    def __init__(self, project_settings: Settings = settings) -> None:
        self.settings = project_settings
        self.settings.ensure_directories()
        self.database_path = self.settings.data_dir / "elex.duckdb"

    def write(self, name: str, frame: pd.DataFrame) -> Path:
        if not name.replace("_", "").isalnum():
            raise ValueError("dataset name must contain only letters, digits, and underscores")
        path = self.settings.processed_dir / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        with duckdb.connect(str(self.database_path)) as connection:
            connection.register("incoming_frame", frame)
            connection.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM incoming_frame')
            connection.unregister("incoming_frame")
        return path

    def read(self, name: str) -> pd.DataFrame:
        path = self.settings.processed_dir / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        return pd.read_parquet(path)

    def exists(self, name: str) -> bool:
        return (self.settings.processed_dir / f"{name}.parquet").exists()
