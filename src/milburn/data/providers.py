from typing import Protocol

from dataclasses import dataclass

import pandas as pd

from milburn.data.models import CandleMetadata, CandleRequest

@dataclass(frozen=True)
class CandleResponse:
    frame: pd.DataFrame
    metadata: CandleMetadata

class CandleProvider(Protocol):
    def fetch_candles(self, request: CandleRequest) -> CandleResponse:
        raise NotImplementedError("fetch_candles must be implemented by subclasses")