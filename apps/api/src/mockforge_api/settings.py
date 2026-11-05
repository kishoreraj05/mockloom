from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("MOCKFORGE_DATABASE_URL", "sqlite:///./mockforge.db")
    )
    # 0 disables it. Meant for the public hosted demo; a local install has no need for it.
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(os.getenv("MOCKFORGE_RATE_LIMIT_PER_MINUTE", "0"))
    )
    web_dist: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "MOCKFORGE_WEB_DIST", Path(__file__).resolve().parents[3] / "web" / "dist"
            )
        )
    )
    log_ring_size: int = 1000
    log_retention_days: int = 7
    log_retention_rows: int = 10_000
    log_flush_seconds: float = 0.5
    log_prune_seconds: float = 60.0
