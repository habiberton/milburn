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

class GraphNode(StrEnum):
    PARSE_REQUEST = "parse_request"
    LOAD_OHLCV = "load_ohlcv"
    GENERATE_REPORT = "generate_report"
    SAVE_TRACE="save_trace"
    
class Effort(StrEnum):
    none="none"
    low="low"
    medium="medium"
    high="high"

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

class CandleSummary(BaseModel):
    symbol: str
    frequency: str
    start: date
    end: date
    first_close: float = None
    last_close: float = None
    min_close: float = None
    max_close: float = None
    volume_present: bool = False
    missing: dict[str, int] = {}

@dataclass(frozen=True)
class CandleResponse:
    frame: pd.DataFrame
    metadata: CandleMetadata

class EvidenceRef(BaseModel):
    tool: str
    field: str
    value: str | float | bool

class SignalClaim(BaseModel):
    category: Literal["trend", "momentum", "volatility", "volume", "levels"]
    claim: str
    evidence: list[EvidenceRef]
    confidence: Literal["low", "medium", "high"]

class AnalysisReport(BaseModel):
    summary: str
    data: dict[str, Any]
    signals: list[SignalClaim]
    conflicts: list[str]
    warnings: list[str]
    next_steps: list[str]

