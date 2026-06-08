from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel

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
