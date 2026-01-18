from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Config:
    num_planners: int
    num_workers: int
    target_dir: str
    log_dir: str
    data_dir: str
    port: int

    @staticmethod
    def load() -> Config:
        """load config from .env file and environment variables"""
        # load from local .env if it exists (env vars override)
        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(env_file)

        try:
            num_planners = int(os.getenv("NUM_PLANNERS", "2"))
            num_workers = int(os.getenv("NUM_WORKERS", "4"))
            port = int(os.getenv("PORT", "8080"))
        except ValueError as e:
            raise RuntimeError(f"invalid config value: {e}") from e

        target_dir = os.getenv("TARGET_DIR", ".")

        return Config(
            num_planners=num_planners,
            num_workers=num_workers,
            target_dir=target_dir,
            log_dir=os.getenv("LOG_DIR", f"{target_dir}/.demiurg/log"),
            data_dir=os.getenv("DATA_DIR", f"{target_dir}/.demiurg"),
            port=port,
        )
