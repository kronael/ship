from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Config:
    """runtime configuration for demiurg

    loads from .env file and environment variables
    CLI args override env vars which override .env file
    """

    num_workers: int
    log_dir: str
    data_dir: str
    max_turns: int
    task_timeout: int

    @staticmethod
    def load(
        workers: int | None = None,
        timeout: int | None = None,
        max_turns: int | None = None,
    ) -> Config:
        """load config from .env file and environment variables

        precedence: CLI args > env vars > .env file > defaults
        """
        # load from local .env if it exists (env vars override)
        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(env_file)

        try:
            # CLI args override env vars
            num_workers = (
                workers if workers is not None
                else int(os.getenv("NUM_WORKERS", "4"))
            )
            task_timeout = (
                timeout if timeout is not None
                else int(os.getenv("TASK_TIMEOUT", "120"))
            )
            if max_turns is None:
                max_turns = int(os.getenv("MAX_TURNS", "5"))
        except ValueError as e:
            raise RuntimeError(f"invalid config value: {e}") from e

        # validate positive integers
        if num_workers < 1:
            raise RuntimeError(f"NUM_WORKERS must be positive, got {num_workers}")
        if task_timeout < 1:
            raise RuntimeError(f"TASK_TIMEOUT must be positive, got {task_timeout}")
        if max_turns < 1:
            raise RuntimeError(f"MAX_TURNS must be positive, got {max_turns}")

        return Config(
            num_workers=num_workers,
            log_dir=os.getenv("LOG_DIR", ".demiurg/log"),
            data_dir=os.getenv("DATA_DIR", ".demiurg"),
            max_turns=max_turns,
            task_timeout=task_timeout,
        )
