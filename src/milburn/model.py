from enum import StrEnum
from datetime import date
from typing import Optional

from dataclasses import dataclass

import pandas as pd
from pydantic import BaseModel
from typing import Any, Literal

class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"

class CandleRequest(BaseModel):
    symbol: str
    frequency: str
    start: date
    end: date
    columns: Optional[list[str]] = None

class CandleMetadata(BaseModel):
    provider: str
    symbol: str
    frequency: str
    start: date
    end: date
    rows: int
    cache_key: str | None
    source: Literal["cache", "api"]
    request_count: int = 0
    raw_metadata: dict[str, Any] = {}

@dataclass(frozen=True)
class CandleResponse:
    frame: pd.DataFrame
    metadata: CandleMetadata